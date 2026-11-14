import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from app import migrate
from app.commands import Commands
from app.config import Settings
from app.import_sqlite import transfer
from app.platforms import PlatformEvent, Platforms
from app.reporting import Reporting
from app.store import Store
from app.workflow import Workflow
from app.youtube import Vault


def test_additive_migration_on_existing_foundation_and_checksum_guard(pg, tmp_path, monkeypatch):
    config = conninfo_to_dict(pg.admin_dsn)
    name = "lc_existing_" + uuid4().hex[:12]
    control = psycopg.connect(make_conninfo(**{**config, "dbname": "postgres"}), autocommit=True)
    control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(**{**config, "dbname": name})
    try:
        with psycopg.connect(dsn, autocommit=True) as db:
            foundation = next(migrate.MIGRATIONS.glob("*foundation.sql"))
            db.execute(foundation.read_text())
            db.execute("INSERT INTO public.agents(name) VALUES('Preserved foundation data')")
        assert len(migrate.apply(dsn, runtime_only=True)) == 4
        assert migrate.apply(dsn, runtime_only=True) == []
        with psycopg.connect(dsn) as db:
            assert (
                db.execute("SELECT name FROM public.agents").fetchone()[0]
                == "Preserved foundation data"
            )
            assert (
                db.execute("SELECT count(*) FROM lc_runtime.schema_migrations").fetchone()[0] == 4
            )
        copies = tmp_path / "migrations"
        copies.mkdir()
        for source in migrate.MIGRATIONS.glob("*.sql"):
            shutil.copy2(source, copies / source.name)
        altered = next(copies.glob("*private_runtime.sql"))
        altered.write_text(altered.read_text() + "\n-- tampered temporary test copy\n")
        monkeypatch.setattr(migrate, "MIGRATIONS", copies)
        with pytest.raises(RuntimeError, match="checksum"):
            migrate.apply(dsn, runtime_only=True)
    finally:
        control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        control.close()


def test_private_rls_and_backend_least_privilege(pg):
    with psycopg.connect(pg.admin_dsn) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname='lc_runtime' AND NOT rowsecurity"
            ).fetchone()[0]
            == 0
        )
        for role in ("anon", "authenticated"):
            assert (
                db.execute(
                    "SELECT has_schema_privilege(%s,'lc_runtime','USAGE')", (role,)
                ).fetchone()[0]
                is False
            )
        assert (
            db.execute(
                "SELECT rolbypassrls OR rolsuper OR rolcreatedb FROM pg_roles WHERE rolname='lazy_capitalist_runtime'"
            ).fetchone()[0]
            is False
        )
    with psycopg.connect(pg.app_dsn) as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("DELETE FROM lc_runtime.schema_migrations")


def test_readonly_synthetic_import_preview_repeatability_ciphertext_and_files(pg, tmp_path):
    source = Store(str(tmp_path / "source.db"))
    workflow = Workflow(source)
    commands = Commands(source, workflow, Settings(_env_file=None))
    reports = Reporting(source)
    platforms = Platforms(source, reports)
    order = commands.create(
        "Erstelle 1 Videos über aktuelle KI-Trends. Maximal CHF 3 Budget.", "synthetic"
    )["id"]
    commands.approve(order)
    video = commands.run(order)["videos"][0]["job_id"]
    key = SecretStr(Fernet.generate_key().decode())
    vault = Vault(source, key)
    with source.connect() as db:
        vault.write(
            db, "tokens", {"access_token": "synthetic-token", "refresh_token": "synthetic-refresh"}
        )
        db.execute("UPDATE ai_usage SET cost_usd=? WHERE job_id=?", (0.000123, video))
        db.execute(
            "UPDATE video_jobs SET created_at=? WHERE id=?", ("2026-01-31 23:59:59.123456", video)
        )
    with source.connect() as db:
        db.execute(
            "INSERT INTO audit_events(id,action) VALUES(?,?)",
            (3_000_000_000, "synthetic-large-reference"),
        )
        db.execute(
            "INSERT INTO report_alerts VALUES(?,?,?)",
            (3_000_000_000, "test", "2026-01-31 23:59:59"),
        )
        db.execute("UPDATE ai_usage SET input_tokens=? WHERE job_id=?", (3_000_000_000, video))
    platforms.record(
        PlatformEvent(
            channel_id="synthetic",
            kind="platform_warning",
            source="mock_platform_signal",
            verification="mock",
            note="Synthetic wide-ID import fixture",
            occurred_at=datetime.now(UTC),
        ),
        "synthetic-wide-event",
    )
    before = hashlib.sha256(Path(source.path).read_bytes()).hexdigest()
    preview = transfer(source.path, pg.admin_dsn, synthetic_confirmed=True)
    assert preview["mode"] == "preview" and preview["insert"]["video_jobs"] == 1
    assert not preview["conflicts"]
    with pg.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM video_jobs").fetchone()[0] == 0
    transferred = transfer(source.path, pg.admin_dsn, synthetic_confirmed=True, apply=True)
    assert transferred["insert"]["youtube_vault"] == 1
    repeated = transfer(source.path, pg.admin_dsn, synthetic_confirmed=True, apply=True)
    assert sum(repeated["insert"].values()) == 0
    assert hashlib.sha256(Path(source.path).read_bytes()).hexdigest() == before
    assert pg.store.job(video) == source.job(video)
    with pg.store.connect() as db:
        assert (
            str(db.execute("SELECT cost_usd FROM ai_usage WHERE job_id=?", (video,)).fetchone()[0])
            == "0.000123"
        )
        assert Vault(pg.store, key).read(db, "tokens")["access_token"] == "synthetic-token"
        assert db.execute("SELECT MAX(id) FROM audit_events").fetchone()[0] > 2_147_483_647
        assert (
            db.execute("SELECT input_tokens FROM ai_usage WHERE job_id=?", (video,)).fetchone()[0]
            == 3_000_000_000
        )
    with source.connect() as db:
        original = db.execute(
            "SELECT ciphertext FROM youtube_vault WHERE name='tokens'"
        ).fetchone()[0]
    with pg.store.connect() as db:
        assert (
            db.execute("SELECT ciphertext FROM youtube_vault WHERE name='tokens'").fetchone()[0]
            == original
        )
    # Files are referenced by the same immutable/hash metadata; never copied as DB blobs.
    pg.store.artifact_dir = source.artifact_dir
    assert (
        Workflow(pg.store).snapshot(video)["steps"][2]["result"]["sha256"]
        == hashlib.sha256((source.artifact_dir / f"{video}.mp4").read_bytes()).hexdigest()
    )
    # Target conflict aborts the whole import and never replaces the row.
    with pg.store.connect() as db:
        db.execute("UPDATE video_jobs SET topic='Target preserved' WHERE id=?", (video,))
    with pytest.raises(ValueError, match="conflict"):
        transfer(source.path, pg.admin_dsn, synthetic_confirmed=True, apply=True)
    assert pg.store.job(video)["topic"] == "Target preserved"
    with pytest.raises(ValueError, match="confirmation"):
        transfer(source.path, pg.admin_dsn)


def test_native_duplicate_column_rows_and_decimals(pg):
    with pg.store.connect() as db:
        row = db.execute("SELECT COALESCE(1,0),COALESCE(2,0),COALESCE(3,0)").fetchone()
        assert tuple(row) == (1, 2, 3)
        assert row[1] == 2
        assert list(db.execute("SELECT 'percent%' AS value").fetchone().keys()) == ["value"]
