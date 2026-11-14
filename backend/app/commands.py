"""Owner-reviewed commands using existing jobs, budgets and local workflow only."""

import hashlib
import json
import math
import re
import textwrap
from decimal import Decimal
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.providers import MockProvider
from app.rendering import Scene, Storyboard

CATEGORIES = ("research", "script", "media", "voiceover", "render")


def micro(amount):
    value = Decimal(str(amount))
    if not value.is_finite() or value < 0 or value.as_tuple().exponent < -6:
        raise ValueError("Finite nonnegative money with at most 6 decimal places required")
    return int(value * 1_000_000)


def money(value):
    return format(Decimal(value) / 1_000_000, ".6f")


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=3, max_length=180)
    count: int = Field(ge=1, le=10)
    language: Literal["de", "en"] = "de"
    format: Literal["9:16"] = "9:16"
    budget_chf: Decimal = Field(ge=0, le=3, max_digits=9, decimal_places=6)
    source_period: str = Field(default="last 7 days requested; no live research", max_length=200)
    platform: Literal["youtube", "tiktok", "instagram"] = "youtube"
    channel_id: str = Field(default="local-youtube", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    audience: str = Field(default="Einsteiger", max_length=160)
    tone: str = Field(default="sachlich", max_length=100)
    length_seconds: int = Field(default=20, ge=10, le=60)
    included_topics: list[str] = Field(default_factory=list, max_length=10)
    excluded_topics: list[str] = Field(default_factory=list, max_length=10)
    references: list[str] = Field(default_factory=list, max_length=10)
    notes: str = Field(default="", max_length=300)
    own_text: str = Field(default="", max_length=600)
    own_text_rights: str = Field(
        default="Owner supplied; rights not independently verified", max_length=200
    )
    review_required: bool = False

    @field_validator("references")
    @classmethod
    def references_safe(cls, values):
        for value in values:
            parsed = urlparse(value)
            if (
                len(value) > 1000
                or parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Store plain HTTP(S) inspiration links only; no retrieval")
        return values

    @field_validator("included_topics", "excluded_topics")
    @classmethod
    def topics_short(cls, values):
        if any(not v.strip() or len(v) > 120 for v in values):
            raise ValueError("Topic constraints must be short nonempty text")
        return values


class Input(BaseModel):
    text: str = Field(min_length=3, max_length=3000)


def parse(text):
    match = re.fullmatch(
        r"\s*Erstelle\s+(\d+)\s+Videos\s+über\s+aktuelle\s+KI-Trends\.\s*Maximal\s+CHF\s+(\d+(?:[.,]\d{1,6})?)\s+Budget\.?\s*",
        text,
        re.I,
    )
    if match and 1 <= int(match[1]) <= 10 and Decimal(match[2].replace(",", ".")) <= 3:
        return Plan(
            topic="KI-Trends — synthetische Testhypothesen",
            count=int(match[1]),
            budget_chf=Decimal(match[2].replace(",", ".")),
        )
    return Plan(topic="Auftrag zur Bearbeitung", count=1, budget_chf=0, review_required=True)


class OrderBudget:
    """Same SQLite BEGIN IMMEDIATE admission pattern; CHF is never converted from USD."""

    def __init__(self, store, daily=0, monthly=0):
        self.store = store
        self.daily = micro(daily)
        self.monthly = micro(monthly)

    def reserve(self, order_id, key, prices=None, *, attempts=3, verified=False, source=None):
        # All paid categories and retry allowance must be known before any reservation.
        if (
            not prices
            or set(prices) != set(CATEGORIES)
            or not 1 <= attempts <= 3
            or not verified
            or not source
        ):
            raise HTTPException(
                402, "Complete CHF prices including retries required; no FX assumption"
            )
        amount = sum(micro(prices[k]) for k in CATEGORIES) * attempts
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM order_budget WHERE key=?", (key,)).fetchone()
            if existing:
                if existing["order_id"] != order_id or existing["estimate_micro"] != amount:
                    raise HTTPException(409, "Reservation key conflict")
                return dict(existing)
            order = db.execute("SELECT plan FROM commands WHERE id=?", (order_id,)).fetchone()
            if not order:
                raise HTTPException(404, "Order missing")
            if db.execute("SELECT paused FROM system_state WHERE id=1").fetchone()[0]:
                raise HTTPException(423, "System paused")
            cap = micro(Plan.model_validate_json(order[0]).budget_chf)
            charge = "MAX(reserved_micro,actual_micro)"
            order_spent = db.execute(
                f"SELECT COALESCE(SUM({charge}),0) FROM order_budget WHERE order_id=?", (order_id,)
            ).fetchone()[0]
            day = db.execute(
                f"SELECT COALESCE(SUM({charge}),0) FROM order_budget WHERE created_at>=date('now')"
            ).fetchone()[0]
            month = db.execute(
                f"SELECT COALESCE(SUM({charge}),0) FROM order_budget WHERE created_at>=date('now','start of month')"
            ).fetchone()[0]
            if order_spent + amount > cap or (
                amount
                and (
                    not self.daily
                    or not self.monthly
                    or day + amount > self.daily
                    or month + amount > self.monthly
                )
            ):
                raise HTTPException(402, "CHF order/day/month budget exhausted or not configured")
            db.execute(
                "INSERT INTO order_budget(key,order_id,estimate_micro,reserved_micro) VALUES(?,?,?,?)",
                (key, order_id, amount, amount),
            )
            return {"reserved_micro": amount, "estimate_micro": amount}


class Commands:
    def __init__(self, store, workflow, settings):
        self.store, self.workflow = store, workflow
        with store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,input TEXT NOT NULL,
              plan TEXT NOT NULL,approved_plan TEXT,status TEXT NOT NULL DEFAULT 'draft',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS command_videos(order_id TEXT NOT NULL REFERENCES commands(id),number INTEGER NOT NULL,
              job_id TEXT UNIQUE NOT NULL REFERENCES video_jobs(id),plan_hash TEXT NOT NULL,PRIMARY KEY(order_id,number));
            CREATE TABLE IF NOT EXISTS order_budget(key TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES commands(id),
              estimate_micro INTEGER NOT NULL,reserved_micro INTEGER NOT NULL,actual_micro INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)
        self.budget = OrderBudget(
            store, settings.command_daily_limit_chf, settings.command_monthly_limit_chf
        )

    def get(self, order_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM commands WHERE id=?", (order_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Order not found")
            result = dict(row)
            result["plan"] = json.loads(row["plan"])
            result["paused"] = bool(
                db.execute("SELECT paused FROM system_state WHERE id=1").fetchone()[0]
            )
            result["videos"] = [
                dict(r)
                for r in db.execute(
                    "SELECT v.*,j.status AS script_status FROM command_videos v JOIN video_jobs j ON j.id=v.job_id WHERE v.order_id=? ORDER BY v.number",
                    (order_id,),
                )
            ]
            for video in result["videos"]:
                video["workflow"] = self.workflow.snapshot(video["job_id"])
            totals = db.execute(
                "SELECT COALESCE(SUM(estimate_micro),0),COALESCE(SUM(reserved_micro),0),COALESCE(SUM(actual_micro),0) FROM order_budget WHERE order_id=?",
                (order_id,),
            ).fetchone()
            result["costs"] = {
                "currency": "CHF",
                "cap": str(result["plan"]["budget_chf"]),
                "estimated_external_api": money(totals[0]),
                "reserved": money(totals[1]),
                "actual_recorded": money(totals[2]),
                "paid_execution": "blocked — no verified provider/FX prices; CHF daily/monthly defaults zero",
                "local_compute_energy_cost": "unknown",
                "pricing_scope": "local/mock incremental external API calls only",
            }
            result["research"] = {
                "synthetic": True,
                "retrieved_at": None,
                "references_fetched": False,
                "references": [
                    {"url": url, "usage": "inspiration only", "rights": "unknown", "fetched": False}
                    for url in result["plan"]["references"]
                ],
                "own_text_rights": result["plan"].get("own_text_rights", "unknown"),
                "current_trends_verified": False,
            }
            result["platforms"] = {
                "youtube": "prepared adapter, live disabled",
                "tiktok": "future; no adapter",
                "instagram": "future; no adapter",
            }
            return result

    def create(self, text, key):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id,input FROM commands WHERE request_key=?", (key,)
            ).fetchone()
            if existing:
                if existing["input"] != text:
                    raise HTTPException(409, "Request key reused for different command")
                order_id = existing["id"]
            else:
                order_id = str(uuid4())
                db.execute(
                    "INSERT INTO commands(id,request_key,input,plan) VALUES(?,?,?,?)",
                    (order_id, key, text, parse(text).model_dump_json()),
                )
        return self.get(order_id)

    def update(self, order_id, plan):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT plan FROM commands WHERE id=?", (order_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Order not found")
            old = Plan.model_validate_json(row[0])
            if plan.budget_chf > old.budget_chf:
                raise HTTPException(403, "Budget increases require separate approval")
            videos = db.execute(
                "SELECT job_id FROM command_videos WHERE order_id=?", (order_id,)
            ).fetchall()
            if videos and plan.count != old.count:
                raise HTTPException(409, "Video count immutable after production starts")
            for video in videos:
                steps = db.execute(
                    "SELECT name,status FROM workflow_steps WHERE job_id=?", (video[0],)
                ).fetchall()
                if any(
                    s["status"] == "running" or (s["name"] == "upload" and s["status"] != "pending")
                    for s in steps
                ):
                    raise HTTPException(409, "Running/attempted upload prevents plan edits")
            for video in videos:
                db.execute(
                    "UPDATE workflow_steps SET status='pending',result=NULL,attempts=0,next_retry=0,error=NULL WHERE job_id=?",
                    (video[0],),
                )
            db.execute(
                "UPDATE commands SET plan=?,approved_plan=NULL,status='draft' WHERE id=?",
                (plan.model_dump_json(), order_id),
            )
            db.execute(
                "INSERT INTO audit_events(action) VALUES(?)",
                ("command_plan_changed_approvals_invalidated",),
            )
        return self.get(order_id)

    def approve(self, order_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT plan FROM commands WHERE id=?", (order_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Order not found")
            plan = Plan.model_validate_json(row[0])
            if plan.review_required:
                raise HTTPException(409, "Edit and review unsupported command first")
            if any(t.casefold() in plan.topic.casefold() for t in plan.excluded_topics):
                raise HTTPException(409, "Topic conflicts with exclusions")
            for number in range(1, plan.count + 1):
                self.video(plan, number)
            digest = hashlib.sha256(row[0].encode()).hexdigest()
            db.execute(
                "UPDATE commands SET approved_plan=?,status='approved' WHERE id=?",
                (digest, order_id),
            )
        return self.get(order_id)

    def video(self, plan, number):
        aspects_de = [
            "kleine Sprachmodelle",
            "KI-Assistenten",
            "multimodale Systeme",
            "lokale KI",
            "Qualitätsprüfung",
        ]
        aspects_en = [
            "small language models",
            "AI assistants",
            "multimodal systems",
            "local AI",
            "quality checks",
        ]
        choices = plan.included_topics or (aspects_de if plan.language == "de" else aspects_en)
        choices = [
            value
            for value in choices
            if not any(t.casefold() in value.casefold() for t in plan.excluded_topics)
        ]
        if not choices or any(
            t.casefold() in (plan.own_text + " " + plan.notes).casefold()
            for t in plan.excluded_topics
        ):
            raise HTTPException(409, "Content constraints conflict; owner edit required")
        aspect = choices[(number - 1) % len(choices)]
        concept = MockProvider().generate(plan.topic).concept
        concept.title = (
            f"{number}. {aspect} — lokaler Test"
            if plan.language == "de"
            else f"{number}. {aspect} — local test"
        )
        concept.hook = (
            f"Testhypothese {number}: {aspect}."
            if plan.language == "de"
            else f"Test hypothesis {number}: {aspect}."
        )
        concept.audience = plan.audience or "Owner-defined audience"
        prefix = (
            "Synthetisches Beispiel, keine aktuelle Recherche."
            if plan.language == "de"
            else "Synthetic example, not current research."
        )
        own = plan.own_text or (
            "Ein kleines Experiment planen, Ergebnisse prüfen und Grenzen dokumentieren."
            if plan.language == "de"
            else "Plan a small experiment, check the result and document its limits."
        )
        concept.script = f"{concept.hook} {prefix} {own} {plan.notes}".strip()
        concept.duration_seconds = plan.length_seconds
        pieces = textwrap.wrap(concept.script, width=140)
        n = max(2, math.ceil(plan.length_seconds / 15), len(pieces))
        if n > 8 or len(concept.script) > 20 * plan.length_seconds:
            raise HTTPException(
                422, "Text too long for readable target duration; shorten or extend"
            )
        while len(pieces) < n:
            pieces.append(concept.title)
        scenes = []
        start = 0
        for index in range(n):
            duration = plan.length_seconds // n + (index < plan.length_seconds % n)
            scenes.append(
                Scene(start_seconds=start, duration_seconds=int(duration), text=pieces[index])
            )
            start += duration
        return concept, Storyboard(scenes=scenes)

    def run(self, order_id):
        self.budget.reserve(
            order_id,
            "local:" + order_id,
            {name: 0 for name in CATEGORIES},
            verified=True,
            source="local/mock zero incremental API fees; compute unknown",
        )
        # Only creates deterministic mock scripts; no configurable external provider is consulted.
        for number in range(1, 11):
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM commands WHERE id=?", (order_id,)).fetchone()
                if not row:
                    raise HTTPException(404, "Order not found")
                plan = Plan.model_validate_json(row["plan"])
                digest = hashlib.sha256(row["plan"].encode()).hexdigest()
                if row["approved_plan"] != digest:
                    raise HTTPException(409, "Production approval required for current plan")
                if number > plan.count:
                    break
                if db.execute("SELECT paused FROM system_state WHERE id=1").fetchone()[0]:
                    raise HTTPException(423, "System paused; existing progress retained")
                previous = db.execute(
                    "SELECT * FROM command_videos WHERE order_id=? AND number=?", (order_id, number)
                ).fetchone()
                concept, board = self.video(plan, number)
                job_id = previous["job_id"] if previous else str(uuid4())
                if not previous:
                    db.execute(
                        "INSERT INTO video_jobs(id,topic,provider,status,result) VALUES(?,?,?,'succeeded',?)",
                        (job_id, concept.title, "mock", concept.model_dump_json()),
                    )
                    db.execute(
                        "INSERT INTO job_metadata VALUES(?,?,?)",
                        (job_id, "deterministic", "command-v1"),
                    )
                    db.execute(
                        "INSERT INTO ai_usage(job_id,cost_usd,cost_kind) VALUES(?,0,'mock')",
                        (job_id,),
                    )
                    db.execute(
                        "INSERT INTO command_videos VALUES(?,?,?,?)",
                        (order_id, number, job_id, digest),
                    )
                    db.execute(
                        "INSERT INTO storyboards VALUES(?,?)", (job_id, board.model_dump_json())
                    )
                elif previous["plan_hash"] != digest:
                    db.execute(
                        "UPDATE video_jobs SET topic=?,result=? WHERE id=?",
                        (concept.title, concept.model_dump_json(), job_id),
                    )
                    db.execute(
                        "INSERT OR REPLACE INTO storyboards VALUES(?,?)",
                        (job_id, board.model_dump_json()),
                    )
                    db.execute(
                        "UPDATE command_videos SET plan_hash=? WHERE job_id=?", (digest, job_id)
                    )
                db.execute("UPDATE commands SET status='producing' WHERE id=?", (order_id,))
            try:
                self.workflow.run(job_id, production_only=True)
            except HTTPException:
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE commands SET status='partial_or_blocked' WHERE id=?", (order_id,)
                    )
                return self.get(order_id)
        with self.store.connect() as db:
            db.execute("UPDATE commands SET status='previews_ready' WHERE id=?", (order_id,))
        return self.get(order_id)


def register_commands(app, settings, store, workflow, authorize):
    service = Commands(store, workflow, settings)

    def owner():
        if not settings.api_token or len(settings.api_token.get_secret_value()) < 32:
            raise HTTPException(503, "Strong owner API token required")

    protected = [Depends(authorize), Depends(owner)]

    @app.post("/commands", dependencies=protected)
    def create(body: Input, idempotency_key: str = Header(min_length=1, max_length=200)):
        return service.create(body.text, idempotency_key)

    @app.get("/commands", dependencies=protected)
    def listing():
        with store.connect() as db:
            ids = [
                r[0]
                for r in db.execute("SELECT id FROM commands ORDER BY created_at DESC LIMIT 50")
            ]
        return [service.get(key) for key in ids]

    @app.get("/commands/{order_id}", dependencies=protected)
    def state(order_id: str):
        return service.get(order_id)

    @app.post("/commands/{order_id}/plan", dependencies=protected)
    def edit(order_id: str, body: Plan):
        return service.update(order_id, body)

    @app.post("/commands/{order_id}/approve", dependencies=protected)
    def approve(order_id: str):
        return service.approve(order_id)

    @app.post("/commands/{order_id}/run", dependencies=protected)
    def run(order_id: str):
        return service.run(order_id)

    return service
