"""Small SQL dialect boundary for the existing parameterized Store queries.

No business logic, implicit schema creation or SQLite fallback. All write coordination
is explicit via scoped transaction advisory locks, not a global database mutex.
"""

import hashlib
import re
import time
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps

import psycopg
from psycopg.rows import dict_row, tuple_row


class DatabaseUnavailable(RuntimeError):
    def __init__(self, message, sqlstate=None):
        super().__init__(message)
        self.sqlstate = sqlstate


def retry_aborted_snapshot(function):
    """Only known rolled-back database conflicts, never ambiguous connection/HTTP failures."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        for attempt in range(3):
            try:
                return function(*args, **kwargs)
            except DatabaseUnavailable as exc:
                if exc.sqlstate not in ("40001", "40P01", "23505") or attempt == 2:
                    raise
                time.sleep(0.01 * (attempt + 1))

    return wrapped


class Row:
    """SQLite-compatible row protocol: positional iteration plus mapping keys()."""

    def __init__(self, columns, values):
        self.sequence = tuple(
            value.astimezone(UTC).strftime(
                "%Y-%m-%d %H:%M:%S.%f" if value.microsecond else "%Y-%m-%d %H:%M:%S"
            )
            if isinstance(value, datetime)
            else bytes(value)
            if isinstance(value, memoryview)
            else value
            for value in values
        )
        self.values = dict(zip(columns, self.sequence, strict=True))

    def keys(self):
        return self.values.keys()

    def __getitem__(self, key):
        return self.sequence[key] if isinstance(key, int) else self.values[key]

    def __iter__(self):
        return iter(self.sequence)

    def __len__(self):
        return len(self.sequence)


class Cursor:
    def __init__(self, cursor, insert_id=None):
        self.cursor = cursor
        self.lastrowid = insert_id
        self.rowcount = cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return Row([c.name for c in self.cursor.description], row) if row is not None else None

    def fetchall(self):
        return [
            Row([c.name for c in self.cursor.description], row) for row in self.cursor.fetchall()
        ]

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


# Only these legacy upsert forms are accepted; all other SQL stays shared.
UPSERTS = {
    "system_state": ("id", ("id", "paused")),
    "cost_estimates": ("job_id", ("job_id", "estimated_usd")),
    "storyboards": ("job_id", ("job_id", "script")),
    "youtube_vault": ("name", ("name", "ciphertext")),
    "report_settings": ("id", ("id", "value")),
    "report_cooldowns": ("category", ("category", "last_sent")),
}


def dialect(sql):
    sql = sql.strip()
    match = re.match(r"INSERT OR (REPLACE|IGNORE) INTO (\w+)", sql, re.I)
    if match:
        mode, table = match.groups()
        sql = re.sub(r"INSERT OR (REPLACE|IGNORE)", "INSERT", sql, count=1, flags=re.I)
        if mode.upper() == "IGNORE":
            sql += " ON CONFLICT DO NOTHING"
        else:
            if table not in UPSERTS:
                raise ValueError("Unsupported upsert table")
            pk, columns = UPSERTS[table]
            sql += f" ON CONFLICT({pk}) DO UPDATE SET " + ",".join(
                f"{col}=EXCLUDED.{col}" for col in columns if col != pk
            )
    sql = sql.replace(
        "date('now','start of month')",
        "date_trunc('month',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'",
    )
    sql = sql.replace(
        "date('now')", "date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
    )
    sql = sql.replace("MAX(reserved_micro,actual_micro)", "GREATEST(reserved_micro,actual_micro)")
    sql = re.sub(r"\browid\b", "ordinal", sql)
    return sql.replace("%", "%%").replace("?", "%s")


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def begin(self, resource, *, repeatable=False):
        if repeatable:
            self.raw.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        self.lock(resource)

    def lock(self, resource):
        key = int.from_bytes(hashlib.sha256(resource.encode()).digest()[:8], signed=True)
        self.raw.execute("SELECT pg_advisory_xact_lock(%s)", (key,))

    def table_exists(self, table):
        return (
            self.raw.execute("SELECT to_regclass(%s) AS name", ("lc_runtime." + table,)).fetchone()[
                "name"
            ]
            is not None
        )

    def executescript(self, sql):
        # DDL is versioned and applied explicitly by the owner/migration tool.
        # Bootstrap calls only verify their declared tables already exist.
        for table in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql):
            if not self.table_exists(table):
                raise DatabaseUnavailable("Runtime migration missing")

    def execute(self, sql, params=()):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            raise ValueError("PostgreSQL requires an explicit resource-scoped transaction")
        statement = dialect(sql)
        audit_insert = bool(re.match(r"INSERT INTO audit_events\b", statement))
        if audit_insert:
            statement += " RETURNING id"
        values = tuple(
            Decimal(str(value))
            if isinstance(value, float)
            else int(value)
            if isinstance(value, bool)
            else value
            for value in params
        )
        cursor = self.raw.cursor(row_factory=tuple_row)
        cursor.execute(statement, values)
        insert_id = cursor.fetchone()[0] if audit_insert else None
        return Cursor(cursor, insert_id)


def connect(dsn):
    try:
        return psycopg.connect(
            dsn,
            connect_timeout=5,
            options="-c search_path=lc_runtime,pg_catalog -c timezone=UTC -c lock_timeout=10000 -c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000",
            row_factory=dict_row,
            prepare_threshold=None,
        )
    except psycopg.Error:
        raise DatabaseUnavailable("PostgreSQL connection unavailable; no fallback") from None
