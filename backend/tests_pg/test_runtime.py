import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event, Lock
from urllib.parse import parse_qs, urlparse

import httpx
import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr

from app.commands import CATEGORIES, Commands, OrderBudget
from app.main import create_app
from app.migrate import apply
from app.postgres import DatabaseUnavailable
from app.reporting import ZONE, Preferences, Reporting
from app.workflow import Workflow
from app.youtube import Blocked, Vault, YouTube

TEXT = "Erstelle 5 Videos über aktuelle KI-Trends. Maximal CHF 3 Budget."


def headers(pg, key="test"):
    return {
        "Authorization": "Bearer " + pg.settings.api_token.get_secret_value(),
        "Idempotency-Key": key,
    }


def job(pg):
    client = TestClient(create_app(pg.settings))
    result = client.post("/jobs", headers=headers(pg), json={"topic": "PostgreSQL workflow"})
    assert result.status_code == 201, result.text
    return client, result.json()["id"]


def test_complete_application_restart_commands_and_mock_publication(pg):
    client, key = job(pg)
    assert client.get("/jobs", headers=headers(pg)).status_code == 200
    assert client.post(f"/jobs/{key}/run", headers=headers(pg)).status_code == 200
    assert (
        client.get(f"/jobs/{key}/video", headers=headers(pg)).headers["content-type"] == "video/mp4"
    )
    assert (
        client.post(
            f"/jobs/{key}/approval",
            headers=headers(pg),
            json={"approved": True, "privacy": "public"},
        ).status_code
        == 422
    )
    client.post(f"/jobs/{key}/approval", headers=headers(pg), json={"approved": True})
    result = client.post(f"/jobs/{key}/run", headers=headers(pg)).json()
    assert result["steps"][-1]["result"]["simulation"] is True
    restarted = TestClient(create_app(pg.settings))
    assert restarted.get(f"/jobs/{key}/workflow", headers=headers(pg)).json() == result
    order = restarted.post("/commands", headers=headers(pg, "order"), json={"text": TEXT}).json()[
        "id"
    ]
    restarted.post(f"/commands/{order}/approve", headers=headers(pg))
    result = restarted.post(f"/commands/{order}/run", headers=headers(pg)).json()
    assert result["status"] == "previews_ready" and len(result["videos"]) == 5
    assert len({v["workflow"]["steps"][2]["result"]["sha256"] for v in result["videos"]}) == 5
    assert all(v["workflow"]["steps"][-1]["attempts"] == 0 for v in result["videos"])


def test_parallel_usd_reservations_idempotency_and_rollback(pg):
    class Failed:
        def generate(self, topic):
            raise RuntimeError("synthetic transport ambiguity")

    settings = pg.settings.model_copy(
        update={
            "ai_provider": "openai",
            "allow_paid_ai": True,
            "openai_api_key": SecretStr("synthetic"),
            "job_budget_usd": 0.1,
            "daily_budget_usd": 0.1,
            "monthly_budget_usd": 0.1,
            "lifetime_budget_usd": 0.1,
            "request_reservation_usd": 0.1,
            "input_usd_per_million": 1,
            "output_usd_per_million": 1,
        }
    )
    client = TestClient(create_app(settings, Failed()))
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(
                lambda i: client.post(
                    "/jobs", headers=headers(pg, str(i)), json={"topic": "Atomic reservation"}
                ),
                range(4),
            )
        )
    assert sorted(r.status_code for r in responses) == [402, 402, 402, 502]
    winner = next(
        (i, r.json()["detail"]["job_id"]) for i, r in enumerate(responses) if r.status_code == 502
    )
    assert (
        client.post(
            "/jobs", headers=headers(pg, str(winner[0])), json={"topic": "Atomic reservation"}
        ).json()["id"]
        == winner[1]
    )
    with pg.store.connect() as db:
        assert db.execute("SELECT SUM(cost_usd) FROM ai_usage").fetchone()[0] == Decimal(".1")
    with pytest.raises(RuntimeError), pg.store.connect() as db:
        db.begin("test:rollback")
        db.execute("INSERT INTO audit_events(action) VALUES('must_rollback')")
        raise RuntimeError("rollback")
    with pg.store.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM audit_events WHERE action='must_rollback'").fetchone()[
                0
            ]
            == 0
        )


def test_parallel_chf_retry_budget_and_unrelated_work_not_globally_locked(pg):
    commands = Commands(pg.store, Workflow(pg.store), pg.settings)
    order = commands.create(TEXT, "budget")["id"]
    budget = OrderBudget(pg.store, daily=3, monthly=3)

    def reserve(key):
        try:
            budget.reserve(
                order,
                key,
                {k: ".1" for k in CATEGORIES},
                verified=True,
                source="synthetic test prices",
            )
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(reserve, ["a", "b", "c"])) == [200, 200, 402]
    with pg.store.connect() as guard:
        guard.begin("budget:CHF")
        # Independent mock script admission must not wait for the CHF budget lock.
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(lambda: job(pg)).result(timeout=5)
            assert response[1]


def test_worker_claims_and_stale_worker_result_fence(pg):
    _, key = job(pg)
    workflow = Workflow(pg.store)
    original = workflow.renderer.render
    count = 0
    mutex = Lock()

    def render(*args, **kwargs):
        nonlocal count
        with mutex:
            count += 1
        time.sleep(0.1)
        return original(*args, **kwargs)

    workflow.renderer.render = render

    def run():
        try:
            workflow.run(key)
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(lambda _: run(), range(4))) <= {200, 409}
    assert count == 1
    with pg.store.connect() as db:
        assert (
            db.execute(
                "SELECT attempts FROM workflow_steps WHERE job_id=? AND name='render'", (key,)
            ).fetchone()[0]
            == 1
        )
    client, key2 = job_with_key(pg, "stale")
    second = Workflow(pg.store)
    execute = second.execute

    def stale(job_id, name, record, **kwargs):
        result = execute(job_id, name, record, **kwargs)
        if name == "quality":
            with pg.store.connect() as db:
                db.begin("job:" + job_id)
                db.execute(
                    "UPDATE workflow_steps SET claim_token='replacement',status='pending' WHERE job_id=? AND name='quality'",
                    (job_id,),
                )
        return result

    second.execute = stale
    with pytest.raises(HTTPException, match="Stale worker"):
        second.run(key2)
    assert (
        client.get(f"/jobs/{key2}/workflow", headers=headers(pg)).json()["steps"][0]["status"]
        == "pending"
    )


def job_with_key(pg, key):
    client = TestClient(create_app(pg.settings))
    return client, client.post(
        "/jobs", headers=headers(pg, key), json={"topic": "Resume workflow"}
    ).json()["id"]


def test_orphaned_job_lease_requires_controlled_resume(pg):
    client, key = job(pg)
    client.get(f"/jobs/{key}/workflow", headers=headers(pg))
    with pg.store.connect() as db:
        db.execute(
            "UPDATE workflow_steps SET status='running',attempts=1,updated=?,claim_token='crashed' WHERE job_id=? AND name='quality'",
            (time.time(), key),
        )
    assert client.post(f"/jobs/{key}/run", headers=headers(pg)).status_code == 409
    assert client.post(f"/jobs/{key}/reconcile", headers=headers(pg)).status_code == 409
    with pg.store.connect() as db:
        db.execute("UPDATE workflow_steps SET updated=0 WHERE job_id=?", (key,))
    assert client.post(f"/jobs/{key}/reconcile", headers=headers(pg)).status_code == 200
    restarted = TestClient(create_app(pg.settings))
    assert restarted.post(f"/jobs/{key}/run", headers=headers(pg)).status_code == 200


def test_oauth_single_consumer_encrypted_tokens_and_restart(pg):
    key = SecretStr(Fernet.generate_key().decode())
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(
            200, json={"access_token": "synthetic-access", "refresh_token": "synthetic-refresh"}
        )

    adapter = YouTube(
        pg.store,
        enabled=True,
        vault_key=key,
        client_id="synthetic",
        client_secret=SecretStr("synthetic"),
        redirect_uri="http://127.0.0.1:8000/oauth/youtube/callback",
        transport=httpx.MockTransport(handler),
    )
    state = parse_qs(urlparse(adapter.begin_oauth()).query)["state"][0]

    def callback():
        try:
            adapter.callback(state, "synthetic-code", adapter.redirect)
            return 200
        except Blocked:
            return 400

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(lambda _: callback(), range(3))) == [200, 400, 400]
    assert calls == ["/token"]
    with pg.store.connect() as db:
        blob = db.execute("SELECT ciphertext FROM youtube_vault WHERE name='tokens'").fetchone()[0]
        assert b"synthetic-access" not in blob
    reopened = Vault(pg.store, key)
    with pg.store.connect() as db:
        assert reopened.read(db, "tokens")["refresh_token"] == "synthetic-refresh"


def test_channel_gate_approval_pause_and_reporting(pg):
    client, key = job(pg)
    client.post(f"/jobs/{key}/run", headers=headers(pg))
    client.post(f"/jobs/{key}/approval", headers=headers(pg), json={"approved": True})
    event = {
        "channel_id": "local-youtube",
        "kind": "copyright_strike",
        "source": "mock_platform_signal",
        "verification": "mock",
        "note": "Synthetic integration signal",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    assert (
        client.post("/platforms/events", headers=headers(pg, "signal"), json=event).status_code
        == 200
    )
    assert client.post(f"/jobs/{key}/run", headers=headers(pg)).status_code == 423
    assert (
        client.post("/platforms/events", headers=headers(pg, "signal"), json=event).json()[
            "duplicate"
        ]
        is True
    )
    client.post(
        "/platforms/review",
        headers=headers(pg),
        json={
            "channel_id": "local-youtube",
            "owner_confirmed": True,
            "reason": "Reviewed synthetic signal; no actual provider event",
        },
    )
    assert client.post(f"/jobs/{key}/run", headers=headers(pg)).status_code == 200
    client.post("/system/pause", headers=headers(pg), json={"paused": True})
    assert (
        client.post(
            "/jobs", headers=headers(pg, "paused"), json={"topic": "Must not start"}
        ).status_code
        == 423
    )
    client.post("/system/pause", headers=headers(pg), json={"paused": False})
    assert client.get("/reports").status_code == 401


def test_report_outbox_parallel_restart_and_stale_claim(pg):
    service = Reporting(pg.store)
    with pg.store.connect() as db:
        db.execute(
            "UPDATE report_settings SET value=?",
            (Preferences(email="owner@example.test", whatsapp="+41790000000").model_dump_json(),),
        )
    clock = datetime(2026, 5, 31, 20, tzinfo=ZONE)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: service.tick(clock), range(3)))
    with pg.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM report_deliveries").fetchone()[0] == 2
        assert (
            db.execute(
                "SELECT COUNT(*) FROM report_deliveries WHERE status='simulated'"
            ).fetchone()[0]
            == 2
        )
        db.execute(
            "UPDATE report_deliveries SET status='running',updated=0,attempts=1,claim_token='crashed'"
        )
    Reporting(pg.store).tick(clock + timedelta(minutes=1))
    with pg.store.connect() as db:
        assert {r[0] for r in db.execute("SELECT attempts FROM report_deliveries")} == {2}
        db.execute("UPDATE report_deliveries SET status='pending',attempts=0")
    entered, release = Event(), Event()

    class Slow:
        def send(self, *args):
            entered.set()
            release.wait(5)
            return {"simulation": True, "confirmed_real_delivery": False, "receipt": "old"}

    service.delivery = Slow()
    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(service.dispatch, clock)
        assert entered.wait(3)
        with pg.store.connect() as db:
            row = db.execute("SELECT id FROM report_deliveries WHERE status='running'").fetchone()
            db.execute(
                "UPDATE report_deliveries SET claim_token='replacement',status='pending' WHERE id=?",
                (row[0],),
            )
        release.set()
        work.result(timeout=10)
    with pg.store.connect() as db:
        assert (
            db.execute("SELECT result FROM report_deliveries WHERE id=?", (row[0],)).fetchone()[0]
            != '{"simulation": true, "confirmed_real_delivery": false, "receipt": "old"}'
        )


def test_migrations_idempotent_private_permissions_and_no_fallback(pg, tmp_path):
    assert apply(pg.admin_dsn) == []
    with pg.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 4
    with pytest.raises(DatabaseUnavailable), pg.store.connect() as db:
        db.execute("CREATE TABLE forbidden(x int)")
    api = TestClient(create_app(pg.settings))
    with psycopg.connect(pg.admin_dsn, autocommit=True) as control:
        name = control.info.dbname
    # Block only this disposable test database; no connection-string fallback is possible.
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    config = conninfo_to_dict(pg.admin_dsn)
    with psycopg.connect(
        make_conninfo(**{**config, "dbname": "postgres"}), autocommit=True
    ) as admin:
        admin.execute(
            sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(name))
        )
        try:
            with pytest.raises(DatabaseUnavailable):
                with pg.store.connect():
                    pass
            assert api.get("/health").status_code == 503
        finally:
            admin.execute(
                sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(sql.Identifier(name))
            )
    assert not tmp_path.joinpath("never-fallback.db").exists()


def test_stale_renderer_cannot_promote_a_file(pg):
    client, key = job(pg)
    workflow = Workflow(pg.store)
    render = workflow.renderer.render

    def superseded(*args, **kwargs):
        result = render(*args, **kwargs)
        with pg.store.connect() as db:
            db.begin("job:" + key)
            db.execute(
                "UPDATE workflow_steps SET claim_token='new-worker',status='pending' WHERE job_id=? AND name='render'",
                (key,),
            )
        return result

    workflow.renderer.render = superseded
    with pytest.raises(HTTPException, match="Stale worker"):
        workflow.run(key)
    assert not (pg.store.artifact_dir / f"{key}.mp4").exists()
    assert client.get(f"/jobs/{key}/video", headers=headers(pg)).status_code == 404


def test_process_exit_after_claim_and_fresh_process_resume(pg):
    import os
    import subprocess
    import sys
    from pathlib import Path

    _, key = job(pg)
    Workflow(pg.store).snapshot(key)
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "TEST_PG_URL": pg.app_dsn,
        "TEST_ARTIFACTS": str(pg.store.artifact_dir),
        "TEST_JOB": key,
    }
    admission = """
import os,time
from app.store import Store
s=Store('unused',mode='postgres',database_url=os.environ['TEST_PG_URL'],artifact_dir=os.environ['TEST_ARTIFACTS'])
with s.connect() as db:
 db.begin('job:'+os.environ['TEST_JOB'])
 db.execute("UPDATE workflow_steps SET status='running',updated=?,attempts=1,claim_token='crashed-process' WHERE job_id=? AND name='quality'",(time.time(),os.environ['TEST_JOB']))
os._exit(23)
"""
    assert (
        subprocess.run(
            [sys.executable, "-c", admission], env=environment, capture_output=True, timeout=15
        ).returncode
        == 23
    )
    with pg.store.connect() as db:
        assert (
            db.execute(
                "SELECT status FROM workflow_steps WHERE job_id=? AND name='quality'", (key,)
            ).fetchone()[0]
            == "running"
        )
        db.execute("UPDATE workflow_steps SET updated=0 WHERE job_id=?", (key,))
    client = TestClient(create_app(pg.settings))
    assert client.post(f"/jobs/{key}/reconcile", headers=headers(pg)).status_code == 200
    resume = """
import os
from app.store import Store
from app.workflow import Workflow
s=Store('unused',mode='postgres',database_url=os.environ['TEST_PG_URL'],artifact_dir=os.environ['TEST_ARTIFACTS'])
result=Workflow(s).run(os.environ['TEST_JOB'])
assert result['steps'][2]['status']=='succeeded'
print('resumed')
"""
    result = subprocess.run(
        [sys.executable, "-c", resume], env=environment, capture_output=True, timeout=45
    )
    assert result.returncode == 0 and result.stdout.strip() == b"resumed"
