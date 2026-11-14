"""Owner-reported platform signals, never inferred strikes or mailbox scraping."""

import json
from datetime import datetime
from typing import Literal

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

CAPABILITIES = {
    "youtube": {
        "adapter": "prepared_disabled",
        "live_upload_enabled": False,
        "simulated_upload_supported": True,
    },
    "tiktok": {
        "adapter": "future_none",
        "live_upload_enabled": False,
        "simulated_upload_supported": False,
    },
    "instagram": {
        "adapter": "future_none",
        "live_upload_enabled": False,
        "simulated_upload_supported": False,
    },
}


class PlatformEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["youtube", "tiktok", "instagram"] = "youtube"
    channel_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: Literal[
        "copyright_strike",
        "community_strike",
        "platform_warning",
        "account_restriction",
        "upload_error",
    ]
    occurred_at: datetime
    source: Literal["owner_report", "mock_platform_signal"] = "owner_report"
    verification: Literal["owner_reported", "unverified", "mock"] = "owner_reported"
    note: str = Field(min_length=3, max_length=500)

    @field_validator("occurred_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone required")
        return value


class Review(BaseModel):
    platform: Literal["youtube", "tiktok", "instagram"] = "youtube"
    channel_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    owner_confirmed: Literal[True]
    reason: str = Field(min_length=10, max_length=500)


def ensure(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS platform_events(id TEXT PRIMARY KEY,platform TEXT NOT NULL,channel_id TEXT NOT NULL,
      kind TEXT NOT NULL,payload TEXT NOT NULL,audit_id INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS platform_blocks(platform TEXT NOT NULL,channel_id TEXT NOT NULL,blocked INTEGER NOT NULL,
      review_note TEXT,PRIMARY KEY(platform,channel_id));
    """)


def channel_for(db, job_id):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='command_videos'").fetchone():
        row = db.execute(
            "SELECT c.plan FROM command_videos v JOIN commands c ON c.id=v.order_id WHERE v.job_id=?",
            (job_id,),
        ).fetchone()
        if row:
            plan = json.loads(row[0])
            return plan["platform"], plan["channel_id"]
    return "youtube", "local-youtube"


def publication_guard(db, job_id):
    platform, channel = channel_for(db, job_id)
    if platform != "youtube":
        raise HTTPException(409, "Future platform has no publishing adapter")
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='platform_blocks'").fetchone():
        row = db.execute(
            "SELECT blocked FROM platform_blocks WHERE platform=? AND channel_id=?",
            (platform, channel),
        ).fetchone()
        if row and row[0]:
            raise HTTPException(423, "Channel publication locked; explicit owner review required")


class Platforms:
    def __init__(self, store, reports):
        self.store, self.reports = store, reports
        with store.connect() as db:
            ensure(db)

    def record(self, event, key):
        payload = event.model_dump_json()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload FROM platform_events WHERE id=?", (key,)
            ).fetchone()
            if existing:
                if existing[0] != payload:
                    raise HTTPException(409, "Platform event key conflict")
                return {"duplicate": True, "simulation": event.source == "mock_platform_signal"}
            critical = event.kind != "upload_error"
            label = "platform_critical" if critical else "platform_upload_error"
            action = f"{label}:{event.platform}:{event.channel_id}:" + (
                "mock" if event.source == "mock_platform_signal" else "owner_reported"
            )
            cursor = db.execute("INSERT INTO audit_events(action) VALUES(?)", (action,))
            db.execute(
                "INSERT INTO platform_events(id,platform,channel_id,kind,payload,audit_id) VALUES(?,?,?,?,?,?)",
                (key, event.platform, event.channel_id, event.kind, payload, cursor.lastrowid),
            )
            if critical:
                db.execute(
                    "INSERT INTO platform_blocks(platform,channel_id,blocked) VALUES(?,?,1) ON CONFLICT(platform,channel_id) DO UPDATE SET blocked=1,review_note=NULL",
                    (event.platform, event.channel_id),
                )
        # Mock alert dispatch only; errors never create another platform or job event.
        try:
            self.reports.tick(alerts_only=True)
        except Exception:
            pass
        return {
            "duplicate": False,
            "channel_blocked": critical,
            "simulation": event.source == "mock_platform_signal",
        }

    def overview(self):
        with self.store.connect() as db:
            return {
                "events": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM platform_events ORDER BY created_at DESC LIMIT 100"
                    )
                ],
                "channels": [dict(r) for r in db.execute("SELECT * FROM platform_blocks")],
                "coverage": "Manual owner reports and synthetic test signals only. No automatic strike feed, mailbox, scraping or new OAuth scope.",
                "platforms": CAPABILITIES,
            }


def register_platforms(app, settings, store, reports, authorize):
    service = Platforms(store, reports)

    def owner():
        if not settings.api_token or len(settings.api_token.get_secret_value()) < 32:
            raise HTTPException(503, "Strong owner authorization required")

    protected = [Depends(authorize), Depends(owner)]

    @app.get("/platforms", dependencies=protected)
    def overview():
        return service.overview()

    @app.post("/platforms/events", dependencies=protected)
    def record(body: PlatformEvent, idempotency_key: str = Header(min_length=1, max_length=200)):
        return service.record(body, idempotency_key)

    @app.post("/platforms/review", dependencies=protected)
    def review(body: Review):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT 1 FROM platform_blocks WHERE platform=? AND channel_id=?",
                (body.platform, body.channel_id),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Channel lock missing")
            db.execute(
                "UPDATE platform_blocks SET blocked=0,review_note=? WHERE platform=? AND channel_id=?",
                (body.reason, body.platform, body.channel_id),
            )
            db.execute(
                "INSERT INTO audit_events(action) VALUES(?)",
                (f"owner_channel_review:{body.platform}:{body.channel_id}",),
            )
        return {"blocked": False, "owner_reviewed": True}

    return service
