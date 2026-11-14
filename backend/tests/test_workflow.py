import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(Settings(database_path=str(tmp_path / "db.sqlite"), _env_file=None))
    )


def make_job(client, key="one"):
    return client.post(
        "/jobs", json={"topic": "Better learning habits"}, headers={"Idempotency-Key": key}
    ).json()["id"]


def test_idempotent_creation_and_conflict(client):
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: make_job(client), range(4)))
    assert len(set(ids)) == 1
    assert (
        client.post(
            "/jobs", json={"topic": "Different topic"}, headers={"Idempotency-Key": "one"}
        ).status_code
        == 409
    )
    assert len(client.get("/jobs").json()) == 1


def test_complete_private_simulation(client):
    job = make_job(client)
    state = client.post(f"/jobs/{job}/run").json()
    assert [s["status"] for s in state["steps"]] == ["succeeded"] * 4 + ["pending"] * 2
    preview = client.get(f"/jobs/{job}/video")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "video/mp4"
    assert len(preview.content) > 1000
    assert (
        client.post(
            f"/jobs/{job}/approval", json={"approved": True, "privacy": "public"}
        ).status_code
        == 422
    )
    assert client.post(f"/jobs/{job}/approval", json={"approved": True}).status_code == 200
    result = client.post(f"/jobs/{job}/run").json()
    assert result["steps"][-1]["result"]["simulation"] is True
    assert result["steps"][-1]["result"]["privacy"] == "private"
    assert result["steps"][-1]["result"]["youtube_video_id"] is None
    again = client.post(f"/jobs/{job}/run").json()
    assert again["steps"][-1]["attempts"] == 1
    assert again["revenue"] is None


def test_pause_blocks_new_steps(client):
    job = make_job(client)
    assert client.post("/system/pause", json={"paused": True}).status_code == 200
    assert client.post(f"/jobs/{job}/run").status_code == 423
    assert client.post("/jobs", json={"topic": "Another idea"}).status_code == 423
    client.post("/system/pause", json={"paused": False})
    assert client.post(f"/jobs/{job}/run").status_code == 200


def test_approval_cannot_skip_preview(client):
    job = make_job(client)
    assert client.post(f"/jobs/{job}/approval", json={"approved": True}).status_code == 409


def test_render_retry_resumes_without_reprocessing(tmp_path, monkeypatch):
    from app.workflow import LocalRenderer

    path = str(tmp_path / "db.sqlite")
    client = TestClient(create_app(Settings(database_path=path, _env_file=None)))
    job = make_job(client)
    original = LocalRenderer.render

    def broken(*args):
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(LocalRenderer, "render", broken)
    assert client.post(f"/jobs/{job}/run").status_code == 502
    assert client.post(f"/jobs/{job}/run").status_code == 409
    with sqlite3.connect(path) as db:
        db.execute("UPDATE workflow_steps SET next_retry=0 WHERE job_id=?", (job,))
    monkeypatch.setattr(LocalRenderer, "render", original)
    assert client.post(f"/jobs/{job}/run").status_code == 200
    state = client.get(f"/jobs/{job}/workflow").json()
    assert [s["attempts"] for s in state["steps"][:3]] == [1, 1, 2]


def test_uncertain_step_requires_reconciliation(tmp_path):
    path = str(tmp_path / "db.sqlite")
    client = TestClient(create_app(Settings(database_path=path, _env_file=None)))
    job = make_job(client)
    client.get(f"/jobs/{job}/workflow")
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE workflow_steps SET status='running',attempts=1,updated=? WHERE job_id=? AND name='quality'",
            (time.time(), job),
        )
    assert client.post(f"/jobs/{job}/run").status_code == 409
    assert client.post(f"/jobs/{job}/reconcile").status_code == 409
    with sqlite3.connect(path) as db:
        db.execute("UPDATE workflow_steps SET updated=0 WHERE job_id=?", (job,))
    assert client.post(f"/jobs/{job}/reconcile").status_code == 200
    assert client.post(f"/jobs/{job}/run").status_code == 200


@pytest.mark.parametrize("limited", ["job_budget_usd", "daily_budget_usd", "monthly_budget_usd"])
def test_each_budget_blocks_concurrent_spend(tmp_path, limited):
    from app.providers import MockProvider

    class Charged:
        def generate(self, topic):
            result = MockProvider().generate(topic)
            result.cost_usd = 0.01
            result.cost_kind = "estimated"
            return result

    config = dict(
        database_path=str(tmp_path / "budget.db"),
        ai_provider="openai",
        allow_paid_ai=True,
        openai_api_key="test",
        lifetime_budget_usd=1,
        job_budget_usd=1,
        daily_budget_usd=1,
        monthly_budget_usd=1,
        request_reservation_usd=0.1,
        input_usd_per_million=1,
        output_usd_per_million=1,
    )
    config[limited] = 0.05 if limited == "job_budget_usd" else 0.1
    client = TestClient(create_app(Settings(**config, _env_file=None), Charged()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda i: client.post(
                    "/jobs", json={"topic": "Budget test"}, headers={"Idempotency-Key": str(i)}
                ),
                range(2),
            )
        )
    assert sorted(r.status_code for r in responses) == (
        [402, 402] if limited == "job_budget_usd" else [201, 402]
    )
    if limited != "job_budget_usd":
        job = next(r.json()["id"] for r in responses if r.status_code == 201)
        assert client.get("/finance").json()["costs"][0]["usd"] == 0.1
        assert (
            client.post(
                f"/jobs/{job}/cost-reconciliation",
                json={"actual_usd": 0.01, "billing_reference": "invoice-test"},
            ).status_code
            == 200
        )
        assert client.get("/finance").json()["costs"][0]["cost_kind"] == "actual"


def test_retry_limit(tmp_path, monkeypatch):
    from app.workflow import LocalRenderer

    path = str(tmp_path / "retry.db")
    client = TestClient(create_app(Settings(database_path=path, _env_file=None)))
    job = make_job(client)

    def fail(*args):
        raise RuntimeError("failure")

    monkeypatch.setattr(LocalRenderer, "render", fail)
    for _ in range(3):
        assert client.post(f"/jobs/{job}/run").status_code == 502
        with sqlite3.connect(path) as db:
            db.execute("UPDATE workflow_steps SET next_retry=0 WHERE job_id=?", (job,))
    assert client.post(f"/jobs/{job}/run").status_code == 409


def test_parallel_upload_is_only_processed_once(client):
    job = make_job(client)
    client.post(f"/jobs/{job}/run")
    client.post(f"/jobs/{job}/approval", json={"approved": True})
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: client.post(f"/jobs/{job}/run"), range(4)))
    assert client.get(f"/jobs/{job}/workflow").json()["steps"][-1]["attempts"] == 1
