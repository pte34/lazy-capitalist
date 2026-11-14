import hmac
import json
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from app.config import Settings
from app.providers import MockProvider, OpenAIProvider, Provider
from app.store import Store

logger = logging.getLogger("lazy_capitalist")
logging.basicConfig(level=logging.INFO, format="%(message)s")


class Topic(BaseModel):
    topic: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300, strict=True)
    ]


def create_app(settings: Settings | None = None, provider: Provider | None = None):
    settings = settings or Settings()
    store = Store(settings.database_path)
    provider = provider or (
        MockProvider() if settings.ai_provider == "mock" else OpenAIProvider(settings)
    )
    app = FastAPI(title="Lazy Capitalist", version="0.1.0")

    def authorize(authorization: str | None = Header(default=None)):
        if settings.api_token and not hmac.compare_digest(
            authorization or "", f"Bearer {settings.api_token.get_secret_value()}"
        ):
            raise HTTPException(401, "Unauthorized")

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
    def create_job(body: Topic):
        job_id = str(uuid4())
        reservation = settings.request_reservation_usd if settings.ai_provider == "openai" else 0
        # Serialize budget reservation across processes; committed BEFORE any paid call.
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM ai_usage").fetchone()[0]
            if reservation and total + reservation > settings.lifetime_budget_usd:
                raise HTTPException(402, "Lifetime AI budget exhausted")
            db.execute(
                "INSERT INTO video_jobs(id,topic,provider,status) VALUES(?,?,?,?)",
                (job_id, body.topic.strip(), settings.ai_provider, "running"),
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
                db.execute(
                    "UPDATE video_jobs SET status='succeeded',result=? WHERE id=?",
                    (generation.concept.model_dump_json(), job_id),
                )
                db.execute(
                    "UPDATE ai_usage SET cost_usd=?,cost_kind=?,input_tokens=?,output_tokens=? "
                    "WHERE job_id=?",
                    (
                        generation.cost_usd,
                        generation.cost_kind,
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
                "revenue": None,
            }

    return app
