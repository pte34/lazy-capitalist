from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.reporting import ZONE, Preferences, Reporting, boundaries, comparison, stamp
from app.store import Store

NOW = datetime(2026, 5, 31, 20, 0, tzinfo=ZONE)


@pytest.fixture
def service(tmp_path):
    service = Reporting(Store(str(tmp_path / "db")))
    with service.store.connect() as db:
        db.execute(
            "UPDATE report_settings SET value=?",
            (Preferences(email="owner@example.test", whatsapp="+41790000000").model_dump_json(),),
        )
    return service


def test_dst_and_calendar_boundaries():
    for day, hours in [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)]:
        start, end = boundaries("daily", day)
        assert (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() == hours * 3600
        seconds, current_end, previous, previous_end = comparison("daily", start, end)
        assert (current_end - start.astimezone(UTC)).total_seconds() == seconds
        assert (previous_end - previous.astimezone(UTC)).total_seconds() == seconds
    start, end = boundaries("monthly", date(2027, 1, 31))
    assert stamp(start).startswith("2026-12-31")
    assert end.month == 2


def test_bundle_idempotent_restart_and_catchup(service):
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: service.tick(NOW), range(3)))
    with service.store.connect() as db:
        count = db.execute("SELECT count(*) FROM reports").fetchone()[0]
        assert 3 <= count <= 10
        assert (
            db.execute(
                "SELECT count(*) FROM reports WHERE id IN (?,?,?)",
                ("daily:2026-05-31", "weekly:2026-05-31", "monthly:2026-05-31"),
            ).fetchone()[0]
            == 3
        )
        # One combined simulated notification per channel, no duplicates under concurrency.
        assert db.execute("SELECT count(*) FROM report_deliveries").fetchone()[0] == 2
        assert {r[0] for r in db.execute("SELECT status FROM report_deliveries")} == {"simulated"}
    restarted = Reporting(Store(service.store.path))
    assert restarted.tick(NOW)["reports_created"] == 0
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM report_deliveries").fetchone()[0] == 2


def test_missing_finance_and_reservations_are_not_actual(service):
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO video_jobs(id,topic,provider,status,created_at) VALUES('a','test','openai','failed',?)",
            (stamp(NOW - timedelta(hours=1)),),
        )
        db.execute("INSERT INTO ai_usage(job_id,cost_usd,cost_kind) VALUES('a',0.1,'reserved')")
        db.execute(
            "INSERT INTO video_jobs(id,topic,provider,status,created_at) VALUES('b','test','mock','succeeded',?)",
            (stamp(NOW - timedelta(hours=1)),),
        )
        db.execute("INSERT INTO ai_usage(job_id,cost_usd,cost_kind) VALUES('b',0,'mock')")
        report = service.aggregate(db, *boundaries("daily", NOW.date()))
    assert report["costs"]["actual"] == "0.00000000"
    assert report["costs"]["reserved"] == "0.10000000"
    assert report["revenue"] is report["roi"] is report["profit"] is None
    assert report["mock_script_jobs"] == 1


def test_alerts_cooldown_and_failed_channel_no_recursion(service):
    class Failed:
        def send(self, *args):
            raise RuntimeError("sensitive recipient must not leak")

    service.delivery = Failed()
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO audit_events(action,created_at) VALUES('budget_blocked',?)", (stamp(NOW),)
        )
    assert service.tick(NOW, alerts_only=True)["alerts_queued"] == 1
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO audit_events(action,created_at) VALUES('budget_blocked',?)",
            (stamp(NOW + timedelta(minutes=1)),),
        )
    assert service.tick(NOW + timedelta(minutes=1), alerts_only=True)["alerts_queued"] == 0
    for delta in [2, 4, 6]:
        service.tick(NOW + timedelta(minutes=delta), alerts_only=True)
    with service.store.connect() as db:
        assert db.execute("SELECT max(attempts) FROM report_deliveries").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 2
        assert all(
            "sensitive" not in r[0] for r in db.execute("SELECT error FROM report_deliveries")
        )
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO audit_events(action,created_at) VALUES('budget_blocked',?)",
            (stamp(NOW + timedelta(hours=2)),),
        )
    assert service.tick(NOW + timedelta(hours=2), alerts_only=True)["alerts_queued"] == 1


def test_interrupted_mock_delivery_resumes(service):
    service.tick(NOW)
    with service.store.connect() as db:
        before = db.execute("SELECT result FROM report_deliveries ORDER BY id LIMIT 1").fetchone()[
            0
        ]
        db.execute("UPDATE report_deliveries SET status='running',updated=0,attempts=1")
    service.tick(NOW + timedelta(minutes=1))
    with service.store.connect() as db:
        assert (
            db.execute("SELECT result FROM report_deliveries ORDER BY id LIMIT 1").fetchone()[0]
            == before
        )
        assert {r[0] for r in db.execute("SELECT attempts FROM report_deliveries")} == {2}


def test_authorization_settings_mock_test_and_live_block(tmp_path):
    settings = Settings(database_path=str(tmp_path / "db"), api_token="a" * 40, _env_file=None)
    client = TestClient(create_app(settings))
    assert client.get("/reports").status_code == 401
    header = {"Authorization": "Bearer " + "a" * 40}
    assert (
        client.post("/reports/settings", headers=header, json={"live_delivery": True}).status_code
        == 422
    )
    assert (
        client.post("/reports/settings", headers=header, json={"email": "invalid"}).status_code
        == 422
    )
    r = client.post(
        "/reports/settings",
        headers=header,
        json={"email": "owner@example.test", "whatsapp": "+41790000000"},
    )
    assert r.status_code == 200 and "owner@example.test" not in r.text
    assert client.post("/reports/test", headers=header).json()["confirmed_real_delivery"] is False
    assert {r["status"] for r in client.get("/reports/deliveries", headers=header).json()} == {
        "simulated"
    }
    settings.api_token = None
    assert client.get("/reports").status_code == 503


def test_budget_failure_creates_real_event_and_immediate_mock_alert(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "db"),
        api_token="a" * 40,
        ai_provider="openai",
        allow_paid_ai=True,
        openai_api_key="test",
        job_budget_usd=0.01,
        daily_budget_usd=1,
        monthly_budget_usd=1,
        lifetime_budget_usd=1,
        request_reservation_usd=0.1,
        input_usd_per_million=1,
        output_usd_per_million=1,
        _env_file=None,
    )
    client = TestClient(create_app(settings))
    header = {"Authorization": "Bearer " + "a" * 40, "Idempotency-Key": "budget-blocked"}
    client.post("/reports/settings", headers=header, json={"email": "owner@example.test"})
    assert client.post("/jobs", headers=header, json={"topic": "Test budget"}).status_code == 402
    deliveries = client.get("/reports/deliveries", headers=header).json()
    assert any(r["status"] == "simulated" for r in deliveries)


def test_explicit_mock_test_retry_key_deduplicates(tmp_path):
    client = TestClient(
        create_app(Settings(database_path=str(tmp_path / "db"), api_token="a" * 40, _env_file=None))
    )
    headers = {"Authorization": "Bearer " + "a" * 40, "Idempotency-Key": "same-test"}
    client.post("/reports/settings", headers=headers, json={"email": "owner@example.test"})
    assert client.post("/reports/test", headers=headers).status_code == 200
    assert client.post("/reports/test", headers=headers).status_code == 200
    assert len(client.get("/reports/deliveries", headers=headers).json()) == 2
