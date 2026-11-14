import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import psycopg

from app.postgres import Connection, DatabaseUnavailable
from app.postgres import connect as pg_connect


class SQLiteConnection:
    def __init__(self, raw):
        self.raw = raw

    def begin(self, resource, *, repeatable=False):
        self.raw.execute("BEGIN IMMEDIATE")

    def lock(self, resource):
        pass  # BEGIN IMMEDIATE already serializes SQLite writes.

    def table_exists(self, table):
        return bool(
            self.raw.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone()
        )

    def executescript(self, sql):
        return self.raw.executescript(sql)

    def execute(self, sql, params=()):
        return self.raw.execute(sql, tuple(str(v) if isinstance(v, Decimal) else v for v in params))


class Store:
    def __init__(self, path: str, *, mode="sqlite", database_url=None, artifact_dir=None):
        if mode not in ("sqlite", "postgres"):
            raise ValueError("Explicit database mode required")
        self.mode = mode
        self.database_url = database_url
        self.artifact_dir = Path(artifact_dir) if artifact_dir else Path(path).parent / "videos"
        if mode == "postgres":
            if not database_url or not artifact_dir:
                raise DatabaseUnavailable("DATABASE_URL and ARTIFACT_DIR required for PostgreSQL")
            self.path = path
            with self.connect() as db:
                version = db.execute(
                    "SELECT version FROM schema_migrations WHERE version='runtime_wide_counters_v4'"
                ).fetchone()
                if not version:
                    raise DatabaseUnavailable("PostgreSQL runtime migration required")
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS storyboards (job_id TEXT PRIMARY KEY REFERENCES video_jobs(id), script TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS system_state (id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL);
            INSERT OR IGNORE INTO system_state VALUES(1,0);
            CREATE TABLE IF NOT EXISTS job_metadata (job_id TEXT PRIMARY KEY, model TEXT NOT NULL, prompt_version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cost_estimates (job_id TEXT PRIMARY KEY, estimated_usd REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS submissions (key TEXT PRIMARY KEY, topic TEXT NOT NULL, job_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workflow_steps (
              job_id TEXT NOT NULL REFERENCES video_jobs(id), name TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
              result TEXT, error TEXT, next_retry REAL NOT NULL DEFAULT 0,
              updated REAL NOT NULL DEFAULT 0, PRIMARY KEY(job_id,name));
            CREATE TABLE IF NOT EXISTS video_jobs (
              id TEXT PRIMARY KEY, topic TEXT NOT NULL, provider TEXT NOT NULL,
              status TEXT NOT NULL, result TEXT, error TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS ai_usage (
              job_id TEXT PRIMARY KEY REFERENCES video_jobs(id),
              cost_usd REAL NOT NULL CHECK(cost_usd >= 0), cost_kind TEXT NOT NULL,
              input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS audit_events (
              id INTEGER PRIMARY KEY, job_id TEXT REFERENCES video_jobs(id),
              action TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)
            for table in ("workflow_steps", "report_deliveries"):
                if db.table_exists(table):
                    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                    if "claim_token" not in columns:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN claim_token TEXT")

    @contextmanager
    def connect(self):
        if self.mode == "postgres":
            raw = pg_connect(self.database_url)
            try:
                with raw:
                    yield Connection(raw)
            except psycopg.Error as exc:
                raise DatabaseUnavailable(
                    "PostgreSQL transaction failed (" + str(exc.sqlstate) + "); no fallback",
                    sqlstate=exc.sqlstate,
                ) from None
            finally:
                raw.close()
        else:
            raw = sqlite3.connect(self.path, timeout=10)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys=ON")
            try:
                with raw:
                    yield SQLiteConnection(raw)
            finally:
                raw.close()

    def job(self, job_id: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM video_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result
