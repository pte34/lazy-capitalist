"""Explicit insert-only synthetic SQLite -> PostgreSQL preview/import.

No source mutation, automatic production migration, video blob copy or target overwrite.
"""

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from psycopg import sql

from app.postgres import connect

TABLES = (
    "video_jobs",
    "system_state",
    "job_metadata",
    "cost_estimates",
    "submissions",
    "workflow_steps",
    "storyboards",
    "ai_usage",
    "audit_events",
    "commands",
    "command_videos",
    "order_budget",
    "youtube_vault",
    "owner_sessions",
    "platform_events",
    "platform_blocks",
    "report_settings",
    "reports",
    "report_alerts",
    "report_cooldowns",
    "report_deliveries",
)


def canonical(value, column):
    if isinstance(value, (bytes, memoryview)):
        return bytes(value)
    if column in ("created_at", "scheduled_at"):
        dt = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    if isinstance(value, (float, Decimal, int)):
        return Decimal(str(value))
    return value


def transfer(source, dsn, *, apply=False, synthetic_confirmed=False):
    if not synthetic_confirmed:
        raise ValueError(
            "Explicit synthetic dataset confirmation required, including encrypted records"
        )
    path = Path(source).resolve(strict=True)
    records = {}
    # URI mode=ro and query_only: never invoke Store bootstrap on the source.
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if (
            db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or db.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise ValueError("Source integrity/foreign-key validation failed")
        source_tables = {
            r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        unknown = source_tables - set(TABLES) - {"sqlite_sequence"}
        if unknown:
            raise ValueError("Source contains unsupported tables; explicit review required")
        if (
            "video_jobs" in source_tables
            and db.execute("SELECT 1 FROM video_jobs WHERE provider!='mock' LIMIT 1").fetchone()
        ):
            raise ValueError("Only synthetic mock-provider datasets allowed")
        count = 0
        for table in TABLES:
            if table in source_tables:
                records[table] = [
                    dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY rowid")
                ]
                count += len(records[table])
                if count > 50000:
                    raise ValueError("Synthetic import size limit exceeded")
    summary = {
        "mode": "apply" if apply else "preview",
        "insert": {},
        "already_equal": {},
        "conflicts": [],
        "source_readonly": True,
        "ciphertext": "preserved opaque; external key required",
        "video_files": "not copied",
    }
    with connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(721406117)")
        if apply:
            db.execute(
                sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(
                    sql.SQL(",").join(sql.Identifier("lc_runtime", t) for t in TABLES)
                )
            )
        # Import requires a quiescent isolated target; never shares an application lease.
        for table, rows in records.items():
            columns = db.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='lc_runtime' AND table_name=%s",
                (table,),
            ).fetchall()
            valid = {r["column_name"] for r in columns}
            pks = [
                r["attname"]
                for r in db.execute(
                    "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) WHERE i.indrelid=to_regclass(%s) AND i.indisprimary ORDER BY a.attnum",
                    ("lc_runtime." + table,),
                ).fetchall()
            ]
            if not valid or not pks:
                raise ValueError("Target runtime migration missing")
            summary["insert"][table] = 0
            summary["already_equal"][table] = 0
            for row in rows:
                if set(row) - valid:
                    raise ValueError("Source columns not supported by target")
                where = sql.SQL(" AND ").join(
                    sql.SQL("{}=%s").format(sql.Identifier(k)) for k in pks
                )
                existing = db.execute(
                    sql.SQL("SELECT * FROM {} WHERE ").format(sql.Identifier("lc_runtime", table))
                    + where,
                    tuple(row[k] for k in pks),
                ).fetchone()
                if existing:
                    if any(canonical(existing[k], k) != canonical(v, k) for k, v in row.items()):
                        summary["conflicts"].append(table)
                    else:
                        summary["already_equal"][table] += 1
                    continue
                summary["insert"][table] += 1
                if apply:
                    values = tuple(
                        Decimal(str(v)) if isinstance(v, float) else v for v in row.values()
                    )
                    db.execute(
                        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                            sql.Identifier("lc_runtime", table),
                            sql.SQL(",").join(map(sql.Identifier, row)),
                            sql.SQL(",").join(sql.Placeholder() for _ in row),
                        ),
                        values,
                    )
        if summary["conflicts"]:
            db.rollback()
            if apply:
                raise ValueError("Target conflicts; entire import rolled back, no overwrite")
        elif apply:
            # Preserve explicit audit IDs without reusing the imported sequence range.
            maximum = db.execute("SELECT MAX(id) AS id FROM lc_runtime.audit_events").fetchone()[
                "id"
            ]
            sequence = db.execute(
                "SELECT last_value,is_called FROM lc_runtime.audit_events_id_seq"
            ).fetchone()
            if maximum is not None and (
                maximum > sequence["last_value"]
                or (maximum == sequence["last_value"] and not sequence["is_called"])
            ):
                db.execute(
                    "SELECT setval(pg_get_serial_sequence('lc_runtime.audit_events','id'),%s,true)",
                    (maximum,),
                )
        else:
            db.rollback()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--synthetic-only", action="store_true", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                transfer(
                    args.source,
                    os.environ["MIGRATION_DATABASE_URL"],
                    apply=args.apply,
                    synthetic_confirmed=args.synthetic_only,
                ),
                sort_keys=True,
            )
        )
    except Exception:
        raise SystemExit(
            "Import rejected/rolled back. Review source schema, mock-only data and target conflicts; no secrets logged."
        ) from None


if __name__ == "__main__":
    main()
