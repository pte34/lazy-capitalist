"""Only disposable databases on an explicitly supplied loopback PostgreSQL server."""

import os
from dataclasses import dataclass, field
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.config import Settings
from app.migrate import apply
from app.store import Store


@dataclass
class Runtime:
    settings: Settings
    store: Store
    admin_dsn: str = field(repr=False)
    app_dsn: str = field(repr=False)


@pytest.fixture
def pg(tmp_path):
    configured = os.environ.get("PG_TEST_ADMIN_URL")
    if not configured:
        pytest.skip("PG_TEST_ADMIN_URL not configured; no implicit external database")
    config = conninfo_to_dict(configured)
    if config.get("host") not in ("127.0.0.1", "localhost", "::1"):
        pytest.fail("Integration tests require explicit loopback PostgreSQL")
    name = "lc_it_" + uuid4().hex[:20]
    role = "lc_app_" + uuid4().hex[:20]
    admin = psycopg.connect(configured, autocommit=True)
    for builtin in ("anon", "authenticated"):
        if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (builtin,)).fetchone():
            admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(builtin)))
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    owner_dsn = make_conninfo(**{**config, "dbname": name})
    try:
        apply(owner_dsn)
        admin.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD 'ci-runtime-test' IN ROLE lazy_capitalist_runtime"
            ).format(sql.Identifier(role))
        )
        app_dsn = make_conninfo(
            **{**config, "dbname": name, "user": role, "password": "ci-runtime-test"}
        )
        settings = Settings(
            database_mode="postgres",
            database_url=app_dsn,
            artifact_dir=str(tmp_path / "videos"),
            database_path=str(tmp_path / "never-fallback.db"),
            api_token="test-only-" + "x" * 32,
            reporting_scheduler_enabled=False,
            _env_file=None,
        )
        store = Store(
            settings.database_path,
            mode="postgres",
            database_url=app_dsn,
            artifact_dir=settings.artifact_dir,
        )
        yield Runtime(settings, store, owner_dsn, app_dsn)
    finally:
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        admin.close()
