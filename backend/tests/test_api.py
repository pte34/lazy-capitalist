import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.providers import MockProvider, OpenAIProvider


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=str(tmp_path / "test.db"), _env_file=None)


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def test_health_workflow_persistence(client, settings):
    assert client.get("/health").json() == {"status": "ok", "provider": "mock"}
    response = client.post("/jobs", json={"topic": "Small experiments"})
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "succeeded"
    assert 10 <= job["result"]["duration_seconds"] <= 60
    restarted = TestClient(create_app(settings))
    assert restarted.get("/jobs/" + job["id"]).json() == job
    assert len(restarted.get("/jobs").json()) == 1
    assert restarted.get("/finance").json()["costs"] == [{"cost_kind": "mock", "usd": 0.0}]
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT action FROM audit_events ORDER BY id").fetchall() == [
            ("job_started",),
            ("job_succeeded",),
        ]


@pytest.mark.parametrize("topic", ["", "  ", "a", " a ", "\n\n\n", "x" * 301, 123])
def test_invalid_topics(client, topic):
    assert client.post("/jobs", json={"topic": topic}).status_code == 422


def test_missing_job(client):
    assert client.get("/jobs/missing").status_code == 404


def test_authentication(settings):
    settings.api_token = __import__("pydantic").SecretStr("owner-token")
    client = TestClient(create_app(settings))
    assert client.get("/health").status_code == 200
    for endpoint in ["/jobs", "/finance", "/jobs/missing"]:
        assert client.get(endpoint).status_code == 401
    assert client.post("/jobs", json={"topic": "Testing"}).status_code == 401
    assert (
        client.post(
            "/jobs", json={"topic": "Testing"}, headers={"Authorization": "Bearer owner-token"}
        ).status_code
        == 201
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"environment": "production"},
        {"ai_provider": "openai"},
        {"lifetime_budget_usd": -1},
        {"lifetime_budget_usd": float("nan")},
        {"request_reservation_usd": float("inf")},
        {"ai_provider": "unknown"},
    ],
)
def test_environment_validation(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_mock_is_deterministic():
    assert MockProvider().generate("Habits") == MockProvider().generate("Habits")


class BrokenProvider:
    def generate(self, topic):
        raise RuntimeError("secret must not leak")


def test_failure_retains_status_and_hides_secrets(settings):
    client = TestClient(create_app(settings, BrokenProvider()))
    result = client.post("/jobs", json={"topic": "Testing"})
    assert result.status_code == 502
    assert "secret" not in result.text
    job = client.get("/jobs/" + result.json()["detail"]["job_id"]).json()
    assert job["status"] == "failed"
    assert "secret" not in str(job)


def paid_settings(settings):
    return Settings(
        database_path=settings.database_path,
        ai_provider="openai",
        allow_paid_ai=True,
        openai_api_key="test-key",
        lifetime_budget_usd=0.1,
        job_budget_usd=0.1,
        daily_budget_usd=0.1,
        monthly_budget_usd=0.1,
        request_reservation_usd=0.1,
        input_usd_per_million=1,
        output_usd_per_million=1,
        _env_file=None,
    )


def test_concurrent_reservations_cannot_overspend(settings):
    client = TestClient(create_app(paid_settings(settings), BrokenProvider()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(
            pool.map(
                lambda _: (
                    client.post(
                        "/jobs",
                        json={"topic": "Test topic"},
                        headers={"Idempotency-Key": str(__import__("uuid").uuid4())},
                    ).status_code
                ),
                range(2),
            )
        )
    assert sorted(statuses) == [402, 502]
    assert client.get("/finance").json()["costs"] == [{"cost_kind": "reserved", "usd": 0.1}]


def test_openai_adapter_without_network(settings, monkeypatch):
    def post(url, **kwargs):
        assert url == "https://api.openai.com/v1/chat/completions"
        assert kwargs["json"]["response_format"]["json_schema"]["strict"] is True
        concept = MockProvider().generate("Habits").concept.model_dump_json()
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [{"message": {"content": concept}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200},
            },
        )

    monkeypatch.setattr(httpx, "post", post)
    result = OpenAIProvider(paid_settings(settings)).generate("Habits")
    assert result.cost_usd == 0.0003
    assert result.cost_kind == "estimated"


def test_malformed_provider_output_is_failed(settings, monkeypatch):
    def post(url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [{"message": {"content": '{"script":"only a script"}'}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200},
            },
        )

    monkeypatch.setattr(httpx, "post", post)
    client = TestClient(create_app(paid_settings(settings)))
    assert (
        client.post(
            "/jobs",
            json={"topic": "Test topic"},
            headers={"Idempotency-Key": str(__import__("uuid").uuid4())},
        ).status_code
        == 502
    )
    assert client.get("/finance").json()["costs"][0]["cost_kind"] == "reserved"
