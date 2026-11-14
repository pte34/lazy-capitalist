"""Deterministic local reporting, UTC storage and Zurich schedules. Mock delivery only."""

import calendar
import hashlib
import json
import re
import time
from datetime import UTC, datetime, timedelta
from datetime import time as daytime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

ZONE = ZoneInfo("Europe/Zurich")
CHANNELS = ("email", "whatsapp")


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str | None = None
    whatsapp: str | None = None
    channels: list[Literal["email", "whatsapp"]] = ["email", "whatsapp"]
    immediate_alerts: bool = True
    live_delivery: Literal[False] = False

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        if value is not None and not re.fullmatch(r"[^\s@]{1,64}@[^\s@.]+(?:\.[^\s@.]+)+", value):
            raise ValueError("Invalid email")
        if value is not None and len(value) > 254:
            raise ValueError("Email too long")
        return value

    @field_validator("whatsapp")
    @classmethod
    def phone_valid(cls, value):
        if value is not None and not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
            raise ValueError("E.164 number required")
        return value


def stamp(value):
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def boundaries(kind, day):
    if kind == "daily":
        first, after = day, day + timedelta(days=1)
    elif kind == "weekly":
        first = day - timedelta(days=day.weekday())
        after = first + timedelta(days=7)
    else:
        first = day.replace(day=1)
        after = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return datetime.combine(first, daytime(), ZONE), datetime.combine(after, daytime(), ZONE)


def comparison(kind, start, end):
    if kind == "monthly":
        prior = (start.date().replace(day=1) - timedelta(days=1)).replace(day=1)
    else:
        prior = start.date() - timedelta(days=1 if kind == "daily" else 7)
    previous, previous_end = boundaries(kind, prior)
    seconds = min(
        (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds(),
        (previous_end.astimezone(UTC) - previous.astimezone(UTC)).total_seconds(),
    )
    return (
        seconds,
        start.astimezone(UTC) + timedelta(seconds=seconds),
        previous,
        previous.astimezone(UTC) + timedelta(seconds=seconds),
    )


class MockDelivery:
    def send(self, channel, recipient, payload, key):
        if channel not in CHANNELS:
            raise ValueError("Unsupported mock channel")
        return {
            "simulation": True,
            "confirmed_real_delivery": False,
            "provider": "mock_" + channel,
            "receipt": "mock:" + hashlib.sha256(key.encode()).hexdigest()[:20],
        }


class Reporting:
    def __init__(self, store, delivery=None):
        self.store = store
        self.delivery = delivery or MockDelivery()
        with store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS report_settings(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, kind TEXT NOT NULL, scheduled_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS report_alerts(event_id INTEGER PRIMARY KEY, category TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS report_cooldowns(category TEXT PRIMARY KEY, last_sent REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS report_deliveries(id TEXT PRIMARY KEY, channel TEXT NOT NULL, status TEXT NOT NULL,
              payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL DEFAULT 0,
              retry_at REAL NOT NULL DEFAULT 0, result TEXT, error TEXT);
            """)
            db.execute(
                "INSERT OR IGNORE INTO report_settings VALUES(1,?)",
                (Preferences().model_dump_json(),),
            )

    def preferences(self, db):
        return Preferences.model_validate_json(
            db.execute("SELECT value FROM report_settings WHERE id=1").fetchone()[0]
        )

    def aggregate(self, db, start, end):
        lo, hi = stamp(start), stamp(end)
        rows = db.execute(
            "SELECT j.*,u.cost_kind,u.cost_usd FROM video_jobs j LEFT JOIN ai_usage u ON j.id=u.job_id WHERE j.created_at>=? AND j.created_at<?",
            (lo, hi),
        ).fetchall()
        money = {kind: Decimal("0") for kind in ("actual", "reserved", "estimated", "mock")}
        for row in rows:
            if row["cost_kind"] in money:
                money[row["cost_kind"]] += Decimal(str(row["cost_usd"]))
        events = db.execute(
            "SELECT action FROM audit_events WHERE created_at>=? AND created_at<?", (lo, hi)
        ).fetchall()
        action = [r[0] for r in events]
        return {
            "jobs_created": len(rows),
            "mock_script_jobs": sum(r["provider"] == "mock" for r in rows),
            "jobs_failed_current": sum(r["status"] == "failed" for r in rows),
            "local_script_renders": action.count("render_succeeded"),
            "simulated_renders": action.count("render_succeeded:simulated"),
            "simulated_private_uploads": action.count("upload_succeeded:simulated"),
            "real_private_uploads": action.count("youtube_real_complete"),
            "public_publications": None,
            "currency": "USD",
            "costs": {k: format(v, ".8f") for k, v in money.items()},
            "actual_costs_source": "owner-reconciled ledger attributed by job creation time",
            "revenue": None,
            "profit": None,
            "roi": None,
            "reach": None,
            "availability": None,
        }

    def generate(self, db, kind, scheduled, now):
        key = kind + ":" + scheduled.date().isoformat()
        if db.execute("SELECT 1 FROM reports WHERE id=?", (key,)).fetchone():
            return None
        start, period_end = boundaries(kind, scheduled.date())
        end = min(now.astimezone(UTC), period_end.astimezone(UTC))
        seconds, matched_end, previous, previous_end = comparison(kind, start, end)
        payload = {
            "id": key,
            "kind": kind,
            "timezone": "Europe/Zurich",
            "scheduled_at": stamp(scheduled),
            "period_start": stamp(start),
            "period_end": stamp(end),
            "calendar_end": stamp(period_end),
            "data_as_of": stamp(now),
            "interim": end < period_end.astimezone(UTC),
            "completeness": "partial_local_records_only; current job/ledger state; external finance unknown",
            "metrics": self.aggregate(db, start, end),
            "comparison": {
                "equal_elapsed_seconds": int(seconds),
                "current_end": stamp(matched_end),
                "baseline_start": stamp(previous),
                "baseline_end": stamp(previous_end),
                "current": self.aggregate(db, start, matched_end),
                "baseline": self.aggregate(db, previous, previous_end),
            },
        }
        db.execute(
            "INSERT INTO reports VALUES(?,?,?,?)",
            (key, kind, stamp(scheduled), json.dumps(payload)),
        )
        return key

    def tick(self, now=None, *, alerts_only=False):
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("Timezone-aware clock required")
        keys = []
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prefs = self.preferences(db)
            if not alerts_only:
                for offset in range(6, -1, -1):
                    day = now.astimezone(ZONE).date() - timedelta(days=offset)
                    due = datetime.combine(day, daytime(20), ZONE)
                    if due > now:
                        continue
                    kinds = ["daily"]
                    if day.weekday() == 6:
                        kinds.append("weekly")
                    if day.day == calendar.monthrange(day.year, day.month)[1]:
                        kinds.append("monthly")
                    for kind in kinds:
                        key = self.generate(db, kind, due, now)
                        if key:
                            keys.append(key)
            alerts = []
            if prefs.immediate_alerts:
                rows = db.execute(
                    "SELECT * FROM audit_events WHERE (action='budget_blocked' OR action='job_failed' OR action LIKE 'platform_critical:%' OR action LIKE 'platform_upload_error:%' OR action IN ('quality_failed','media_failed','render_failed','preview_failed','upload_failed')) AND id NOT IN (SELECT event_id FROM report_alerts) AND created_at>=? ORDER BY id LIMIT 100",
                    (stamp(now - timedelta(days=7)),),
                ).fetchall()
                for row in rows:
                    category = "budget" if row["action"] == "budget_blocked" else "job_error"
                    if row["action"].startswith(("platform_critical:", "platform_upload_error:")):
                        category = ":".join(row["action"].split(":")[:3])
                    db.execute(
                        "INSERT INTO report_alerts VALUES(?,?,?)",
                        (row["id"], category, row["created_at"]),
                    )
                    last = db.execute(
                        "SELECT last_sent FROM report_cooldowns WHERE category=?", (category,)
                    ).fetchone()
                    if last and now.timestamp() - last[0] < 3600:
                        continue
                    alert = {"category": category, "event_id": row["id"], "job_id": row["job_id"]}
                    if row["action"].startswith(("platform_critical:", "platform_upload_error:")):
                        detail = db.execute(
                            "SELECT payload FROM platform_events WHERE audit_id=?", (row["id"],)
                        ).fetchone()
                        alert["platform_event"] = json.loads(detail[0]) if detail else None
                    alerts.append(alert)
                    db.execute(
                        "INSERT OR REPLACE INTO report_cooldowns VALUES(?,?)",
                        (category, now.timestamp()),
                    )
            if keys or alerts:
                self.enqueue(db, keys, alerts, prefs)
        self.dispatch(now)
        return {"reports_created": len(keys), "alerts_queued": len(alerts), "simulation": True}

    def enqueue(self, db, keys, alerts, prefs, nonce=""):
        summaries = []
        for report_id in sorted(keys):
            row = db.execute("SELECT payload FROM reports WHERE id=?", (report_id,)).fetchone()
            report = json.loads(row[0])
            summaries.append(
                {
                    "id": report_id,
                    "data_as_of": report["data_as_of"],
                    "interim": report["interim"],
                    "metrics": report["metrics"],
                }
            )
        payload = {
            "reports": sorted(keys),
            "report_summaries": summaries,
            "alerts": alerts,
            "simulation": True,
        }
        batch = json.dumps(payload, sort_keys=True) + nonce
        for channel in sorted(set(prefs.channels)):
            key = hashlib.sha256((channel + batch).encode()).hexdigest()
            db.execute(
                "INSERT OR IGNORE INTO report_deliveries(id,channel,status,payload) VALUES(?,?,'pending',?)",
                (key, channel, json.dumps(payload)),
            )

    def dispatch(self, now):
        # Only mocks exist: interrupted mock deliveries can safely resume with the same receipt key.
        with self.store.connect() as db:
            db.execute(
                "UPDATE report_deliveries SET status='pending' WHERE status='running' AND updated<?",
                (now.timestamp() - 120,),
            )
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM report_deliveries WHERE status IN ('pending','failed','blocked_configuration') AND attempts<3 AND retry_at<=? ORDER BY rowid LIMIT 20",
                    (now.timestamp(),),
                )
            ]
        for key in ids:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM report_deliveries WHERE id=?", (key,)).fetchone()
                if (
                    row["status"] not in ("pending", "failed", "blocked_configuration")
                    or row["retry_at"] > now.timestamp()
                    or row["attempts"] >= 3
                ):
                    continue
                if db.execute("SELECT paused FROM system_state WHERE id=1").fetchone()[0]:
                    continue
                prefs = self.preferences(db)
                recipient = getattr(prefs, row["channel"])
                if row["channel"] not in prefs.channels:
                    continue
                if not recipient:
                    db.execute(
                        "UPDATE report_deliveries SET status='blocked_configuration',error='Recipient not configured' WHERE id=?",
                        (key,),
                    )
                    continue
                db.execute(
                    "UPDATE report_deliveries SET status='running',attempts=attempts+1,updated=? WHERE id=?",
                    (now.timestamp(), key),
                )
            try:
                result = self.delivery.send(
                    row["channel"], recipient, json.loads(row["payload"]), key
                )
                if (
                    not result.get("simulation")
                    or result.get("confirmed_real_delivery") is not False
                ):
                    raise ValueError("Real delivery prohibited")
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE report_deliveries SET status='simulated',result=?,error=NULL WHERE id=?",
                        (json.dumps(result), key),
                    )
            except Exception:
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE report_deliveries SET status='failed',error='Mock delivery failed',retry_at=? WHERE id=?",
                        (now.timestamp() + 2 ** (row["attempts"] + 1), key),
                    )
                # Intentionally no job-failure audit event: no recursive alert chain.


def register_reporting(app, settings, store, authorize):
    service = Reporting(store)

    def protected():
        if not settings.api_token or len(settings.api_token.get_secret_value()) < 32:
            raise HTTPException(503, "Strong owner API token required for reporting")

    dependencies = [Depends(authorize), Depends(protected)]

    @app.get("/reports", dependencies=dependencies)
    def reports():
        with store.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM reports ORDER BY scheduled_at DESC LIMIT 100"
                )
            ]

    @app.get("/reports/settings", dependencies=dependencies)
    def preferences():
        with store.connect() as db:
            prefs = service.preferences(db).model_dump()
        prefs["email"] = "***@***" if prefs["email"] else None
        prefs["whatsapp"] = "***" + prefs["whatsapp"][-2:] if prefs["whatsapp"] else None
        return {
            **prefs,
            "timezone": "Europe/Zurich",
            "time": "20:00",
            "weekly_day": "Sunday",
            "monthly_day": "last",
            "catchup_days": 7,
        }

    @app.post("/reports/settings", dependencies=dependencies)
    def configure(body: Preferences):
        with store.connect() as db:
            db.execute("UPDATE report_settings SET value=? WHERE id=1", (body.model_dump_json(),))
        return preferences()

    @app.post("/reports/run", dependencies=dependencies)
    def run():
        return service.tick()

    @app.post("/reports/test", dependencies=dependencies)
    def test(idempotency_key: str | None = Header(default=None, max_length=200)):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prefs = service.preferences(db)
            if not prefs.email and not prefs.whatsapp:
                raise HTTPException(409, "Configure at least one mock recipient")
            # Explicit test submissions are separate; periodic jobs remain idempotent.
            service.enqueue(db, [], [], prefs, nonce=idempotency_key or str(time.time_ns()))
        service.dispatch(datetime.now(UTC))
        return {"simulation": True, "confirmed_real_delivery": False}

    @app.get("/reports/deliveries", dependencies=dependencies)
    def deliveries():
        with store.connect() as db:
            return [
                dict(r)
                for r in db.execute("SELECT * FROM report_deliveries ORDER BY rowid DESC LIMIT 100")
            ]

    return service
