"""Explicit version/checksum-checked local migration runner; no startup DDL."""

import argparse
import hashlib
import os
import re
from pathlib import Path

from app.postgres import connect

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def apply(dsn, *, runtime_only=False):
    applied = []
    with connect(dsn) as db:
        # Migration-only session lock; application transactions never take this lock.
        db.autocommit = True
        db.execute("SELECT pg_advisory_lock(721406116)")
        try:
            db.execute("CREATE SCHEMA IF NOT EXISTS lc_migrations")
            db.execute("REVOKE ALL ON SCHEMA lc_migrations FROM PUBLIC")
            db.execute(
                "CREATE TABLE IF NOT EXISTS lc_migrations.history(version TEXT PRIMARY KEY,sha256 TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if runtime_only and path.name.endswith("_foundation.sql"):
                    continue
                content = path.read_text()
                digest = hashlib.sha256(content.encode()).hexdigest()
                old = db.execute(
                    "SELECT sha256 FROM lc_migrations.history WHERE version=%s", (path.name,)
                ).fetchone()
                if old:
                    if old["sha256"] != digest:
                        raise RuntimeError("Applied migration checksum differs: " + path.name)
                    continue
                # Files are standalone psql transactions; this runner includes the ledger atomically.
                script = re.sub(r"(?m)^(BEGIN|COMMIT);\s*$", "", content)
                with db.transaction():
                    db.execute(script)
                    db.execute(
                        "INSERT INTO lc_migrations.history VALUES(%s,%s,now())", (path.name, digest)
                    )
                applied.append(path.name)
        finally:
            db.execute("SELECT pg_advisory_unlock(721406116)")
    return applied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-only",
        action="store_true",
        help="Apply only additive runtime schema to a database with existing foundation migrations",
    )
    args = parser.parse_args()
    dsn = os.environ.get("MIGRATION_DATABASE_URL")
    if not dsn:
        raise SystemExit("MIGRATION_DATABASE_URL required; no DSN on command line")
    try:
        for name in apply(dsn, runtime_only=args.runtime_only):
            print("Applied " + name)
    except Exception:
        raise SystemExit(
            "Migration failed; database unchanged for failed migration. Inspect schema/checksum with owner tools; no credentials logged."
        ) from None


if __name__ == "__main__":
    main()
