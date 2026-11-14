import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from app.commands import register_commands
from app.config import Settings
from app.oauth import register_oauth
from app.platforms import register_platforms
from app.postgres import DatabaseUnavailable
from app.providers import MockProvider, OpenAIProvider, Provider
from app.reporting import register_reporting
from app.store import Store
from app.workflow import Workflow, register_routes

logger = logging.getLogger("lazy_capitalist")
logging.basicConfig(level=logging.INFO, format="%(message)s")


class Topic(BaseModel):
    topic: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300, strict=True)
    ]


def create_app(settings: Settings | None = None, provider: Provider | None = None, youtube=None):
    settings = settings or Settings()
    store = Store(
        settings.database_path,
        mode=settings.database_mode,
        database_url=settings.database_url.get_secret_value() if settings.database_url else None,
        artifact_dir=settings.artifact_dir,
    )
    provider = provider or (
        MockProvider() if settings.ai_provider == "mock" else OpenAIProvider(settings)
    )

    @asynccontextmanager
    async def lifespan(application):
        async def scheduled():
            while True:
                try:
                    await asyncio.to_thread(reports.tick)
                except Exception:
                    logger.warning('{"event":"local_report_tick_failed"}')
                await asyncio.sleep(60)

        task = asyncio.create_task(scheduled()) if settings.reporting_scheduler_enabled else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(lifespan=lifespan, title="Lazy Capitalist", version="0.1.0")

    def authorize(authorization: str | None = Header(default=None)):
        if settings.api_token and not hmac.compare_digest(
            authorization or "", f"Bearer {settings.api_token.get_secret_value()}"
        ):
            raise HTTPException(401, "Unauthorized")

    reports = register_reporting(app, settings, store, authorize)
    register_platforms(app, settings, store, reports, authorize)

    @app.exception_handler(HTTPException)
    async def known_error(request: Request, exc: HTTPException):
        if exc.status_code == 402:
            with store.connect() as db:
                db.execute("INSERT INTO audit_events(action) VALUES('budget_blocked')")
        if exc.status_code in (402, 502):
            try:
                reports.tick(alerts_only=True)
            except Exception:
                logger.warning('{"event":"report_alert_processing_failed"}')
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
        )

    @app.exception_handler(DatabaseUnavailable)
    async def database_unavailable(request: Request, exc: DatabaseUnavailable):
        logger.error('{"event":"database_unavailable"}')
        return JSONResponse(
            status_code=503, content={"detail": "Database unavailable; no fallback"}
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logger.error(json.dumps({"event": "request_failed", "type": type(exc).__name__}))
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.get("/health")
    def health():
        with store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok", "provider": settings.ai_provider}

    @app.post("/jobs", status_code=201, dependencies=[Depends(authorize)])
    def create_job(body: Topic, idempotency_key: str | None = Header(default=None, max_length=200)):
        if settings.ai_provider == "openai" and not idempotency_key:
            raise HTTPException(400, "Paid jobs require Idempotency-Key")
        if idempotency_key is None:
            idempotency_key = str(uuid4())
        job_id = str(uuid4())
        reservation = settings.request_reservation_usd if settings.ai_provider == "openai" else 0
        # Serialize budget reservation across processes; committed BEFORE any paid call.
        with store.connect() as db:
            db.begin("submission:" + idempotency_key)
            if idempotency_key:
                prior = db.execute(
                    "SELECT * FROM submissions WHERE key=?", (idempotency_key,)
                ).fetchone()
                if prior:
                    if prior["topic"] != body.topic:
                        raise HTTPException(409, "Idempotency key belongs to another topic")
                    return store.job(prior["job_id"])
            if db.execute("SELECT paused FROM system_state WHERE id=1").fetchone()[0]:
                raise HTTPException(423, "System paused")
            if reservation:
                db.lock("budget:USD")
                for limit, cutoff in [
                    (settings.job_budget_usd, None),
                    (settings.daily_budget_usd, "date('now')"),
                    (settings.monthly_budget_usd, "date('now','start of month')"),
                ]:
                    spent = (
                        0
                        if cutoff is None
                        else db.execute(
                            "SELECT COALESCE(SUM(u.cost_usd),0) FROM ai_usage u JOIN video_jobs j "
                            f"ON j.id=u.job_id WHERE j.created_at >= {cutoff}"
                        ).fetchone()[0]
                    )
                    if limit <= 0 or Decimal(str(spent)) + Decimal(str(reservation)) > Decimal(
                        str(limit)
                    ):
                        raise HTTPException(402, "Job/day/month budget missing or exhausted")
            total = db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM ai_usage").fetchone()[0]
            if reservation and Decimal(str(total)) + Decimal(str(reservation)) > Decimal(
                str(settings.lifetime_budget_usd)
            ):
                raise HTTPException(402, "Lifetime AI budget exhausted")
            db.execute(
                "INSERT INTO video_jobs(id,topic,provider,status) VALUES(?,?,?,?)",
                (job_id, body.topic.strip(), settings.ai_provider, "running"),
            )
            db.execute(
                "INSERT INTO job_metadata VALUES(?,?,?)",
                (
                    job_id,
                    settings.openai_model if settings.ai_provider == "openai" else "deterministic",
                    "concept-v1",
                ),
            )
            db.execute(
                "INSERT INTO submissions VALUES(?,?,?)", (idempotency_key, body.topic, job_id)
            )
            db.execute(
                "INSERT INTO ai_usage(job_id,cost_usd,cost_kind) VALUES(?,?,?)",
                (job_id, reservation, "reserved" if reservation else "mock"),
            )
            db.execute(
                "INSERT INTO audit_events(job_id,action) VALUES(?,?)", (job_id, "job_started")
            )
        try:
            generation = provider.generate(body.topic.strip())
            with store.connect() as db:
                db.begin("budget:USD" if reservation else "job:" + job_id)
                db.execute(
                    "UPDATE video_jobs SET status='succeeded',result=? WHERE id=?",
                    (generation.concept.model_dump_json(), job_id),
                )
                db.execute(
                    "INSERT OR REPLACE INTO cost_estimates VALUES(?,?)",
                    (job_id, generation.cost_usd),
                )
                db.execute(
                    "UPDATE ai_usage SET cost_usd=?,cost_kind=?,input_tokens=?,output_tokens=? "
                    "WHERE job_id=?",
                    (
                        max(reservation, generation.cost_usd),
                        "reserved" if reservation else generation.cost_kind,
                        generation.input_tokens,
                        generation.output_tokens,
                        job_id,
                    ),
                )
                db.execute(
                    "INSERT INTO audit_events(job_id,action) VALUES(?,?)", (job_id, "job_succeeded")
                )
        except Exception as exc:
            # Retain reservation on ambiguous provider errors to avoid untracked spend.
            with store.connect() as db:
                db.execute(
                    "UPDATE video_jobs SET status='failed',error=? WHERE id=?",
                    ("Generation failed; see audit event", job_id),
                )
                db.execute(
                    "INSERT INTO audit_events(job_id,action) VALUES(?,?)", (job_id, "job_failed")
                )
            logger.warning(
                json.dumps({"event": "job_failed", "job_id": job_id, "type": type(exc).__name__})
            )
            raise HTTPException(502, {"message": "Generation failed", "job_id": job_id}) from None
        logger.info(json.dumps({"event": "job_succeeded", "job_id": job_id}))
        return store.job(job_id)

    @app.get("/jobs", dependencies=[Depends(authorize)])
    def jobs():
        with store.connect() as db:
            ids = db.execute(
                "SELECT id FROM video_jobs ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [store.job(row[0]) for row in ids]

    @app.get("/jobs/{job_id}", dependencies=[Depends(authorize)])
    def get_job(job_id: str):
        result = store.job(job_id)
        if result is None:
            raise HTTPException(404, "Job not found")
        return result

    @app.get("/finance", dependencies=[Depends(authorize)])
    def finance():
        with store.connect() as db:
            rows = db.execute(
                "SELECT cost_kind,SUM(cost_usd) AS usd FROM ai_usage GROUP BY cost_kind"
            )
            return {
                "currency": "USD",
                "costs": [dict(row) for row in rows],
                "lifetime_budget_usd": settings.lifetime_budget_usd,
                "job_budget_usd": settings.job_budget_usd,
                "daily_budget_usd": settings.daily_budget_usd,
                "monthly_budget_usd": settings.monthly_budget_usd,
                "estimates": [dict(r) for r in db.execute("SELECT * FROM cost_estimates")],
                "revenue": None,
            }

    workflow = Workflow(store)
    register_commands(app, settings, store, workflow, authorize)
    register_routes(app, workflow, authorize)
    register_oauth(app, settings, store, youtube)
    return app
