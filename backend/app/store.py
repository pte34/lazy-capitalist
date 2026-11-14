import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
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

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def job(self, job_id: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM video_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result
