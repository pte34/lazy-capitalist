from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

HEADERS = {"Authorization": "Bearer " + "x" * 40, "Idempotency-Key": "strike-1"}


def test_strikes_dedupe_lock_specific_channel_owner_review_and_upload_errors(tmp_path):
    client = TestClient(
        create_app(Settings(database_path=str(tmp_path / "db"), api_token="x" * 40, _env_file=None))
    )
    assert client.get("/platforms").status_code == 401
    job = client.post("/jobs", headers=HEADERS, json={"topic": "Platform guard"}).json()["id"]
    client.post(f"/jobs/{job}/run", headers=HEADERS)
    client.post(f"/jobs/{job}/approval", headers=HEADERS, json={"approved": True})
    event = {
        "platform": "youtube",
        "channel_id": "other-channel",
        "kind": "copyright_strike",
        "source": "mock_platform_signal",
        "verification": "mock",
        "note": "Synthetic strike test only",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    assert (
        client.post("/platforms/events", headers=HEADERS, json=event).json()["channel_blocked"]
        is True
    )
    assert client.post("/platforms/events", headers=HEADERS, json=event).json()["duplicate"] is True
    assert client.post(f"/jobs/{job}/run", headers=HEADERS).status_code == 200
    other = client.post(
        "/jobs",
        headers={**HEADERS, "Idempotency-Key": "second-job"},
        json={"topic": "Locked upload"},
    ).json()["id"]
    client.post(f"/jobs/{other}/run", headers=HEADERS)
    client.post(f"/jobs/{other}/approval", headers=HEADERS, json={"approved": True})
    event["channel_id"] = "local-youtube"
    assert (
        client.post(
            "/platforms/events", headers={**HEADERS, "Idempotency-Key": "strike-2"}, json=event
        ).status_code
        == 200
    )
    assert client.post(f"/jobs/{other}/run", headers=HEADERS).status_code == 423
    client.post("/reports/run", headers=HEADERS)
    assert client.post(f"/jobs/{other}/run", headers=HEADERS).status_code == 423
    assert (
        client.post(
            "/platforms/review",
            headers=HEADERS,
            json={
                "channel_id": "local-youtube",
                "reason": "Reviewed synthetic test and confirmed clearance",
                "owner_confirmed": True,
            },
        ).status_code
        == 200
    )
    assert client.post(f"/jobs/{other}/run", headers=HEADERS).status_code == 200
    event.update(channel_id="error-only", kind="upload_error")
    assert (
        client.post(
            "/platforms/events", headers={**HEADERS, "Idempotency-Key": "upload-error"}, json=event
        ).json()["channel_blocked"]
        is False
    )
    state = client.get("/platforms", headers=HEADERS).json()
    assert len(state["events"]) == 3
    assert not any(c["channel_id"] == "error-only" for c in state["channels"])


def test_signal_provenance_and_timezone_fail_closed():
    import pytest
    from pydantic import ValidationError

    from app.platforms import PlatformEvent

    base = dict(channel_id="test", kind="platform_warning", note="test signal")
    with pytest.raises(ValidationError):
        PlatformEvent(
            **base,
            source="mock_platform_signal",
            verification="owner_reported",
            occurred_at=datetime.now(UTC),
        )
    with pytest.raises(ValidationError):
        PlatformEvent(**base, occurred_at=datetime(2026, 11, 14))
