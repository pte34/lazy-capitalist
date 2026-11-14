import json
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.main import create_app
from app.store import Store
from app.youtube import Blocked, Metadata, YouTube, fingerprint

META = {
    "title": "Test",
    "description": "Test only",
    "made_for_kids": False,
    "synthetic_media": True,
}
SESSION = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=SECRET_SESSION"


@pytest.fixture
def setup(tmp_path):
    store = Store(str(tmp_path / "db"))
    video = tmp_path / "test.mp4"
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=32x32:d=0.1",
            "-c:v",
            "libx264",
            "-y",
            str(video),
        ],
        check=True,
    )
    return store, video


def adapter(setup, handler):
    store, video = setup
    client = YouTube(
        store,
        enabled=True,
        vault_key=SecretStr(Fernet.generate_key().decode()),
        client_id="test-client",
        client_secret=SecretStr("SECRET_CLIENT"),
        redirect_uri="http://127.0.0.1:8765/callback",
        transport=httpx.MockTransport(handler),
    )
    with store.connect() as db:
        client.vault.write(
            db,
            "tokens",
            {
                "access_token": "SECRET_ACCESS",
                "refresh_token": "SECRET_REFRESH",
                "expires": time.time() + 3600,
            },
        )
    return client


def send(client, setup):
    return client.upload(
        "job",
        setup[1],
        "private",
        metadata=META,
        approval=fingerprint(setup[1], Metadata(**META).payload()),
    )


def test_success_private_encrypted_and_idempotent(setup):
    calls = []

    def handler(r):
        calls.append(r)
        if r.method == "POST":
            payload = json.loads(r.content)
            assert payload["status"] == {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": True,
            }
            return httpx.Response(200, headers={"Location": SESSION})
        return httpx.Response(200, json={"id": "video123"})

    client = adapter(setup, handler)
    assert send(client, setup)["youtube_video_id"] == "video123"
    assert send(client, setup)["simulation"] is False
    assert len(calls) == 2
    with setup[0].connect() as db:
        blobs = b"".join(row[0] for row in db.execute("SELECT ciphertext FROM youtube_vault"))
    for secret in [b"SECRET_ACCESS", b"SECRET_REFRESH", b"SECRET_SESSION", b"video123"]:
        assert secret not in blobs


@pytest.mark.parametrize("visibility", ["public", "unlisted"])
def test_visibility_blocked(setup, visibility):
    client = adapter(setup, lambda r: pytest.fail("No HTTP allowed"))
    with pytest.raises(Blocked):
        client.upload("job", setup[1], visibility, metadata=META, approval="none")
    with pytest.raises(Blocked):
        Metadata(**{**META, "privacy": visibility}).payload()
    with pytest.raises(ValidationError):
        Metadata(**META, publishAt="tomorrow")


def test_disabled_missing_vault_and_approval(setup):
    with pytest.raises(Blocked, match="disabled"):
        YouTube(setup[0])
    with pytest.raises(Blocked, match="storage key missing"):
        YouTube(
            setup[0],
            enabled=True,
            client_id="id",
            client_secret=SecretStr("test"),
            redirect_uri="http://127.0.0.1:8765/callback",
        )
    client = adapter(setup, lambda r: pytest.fail("No HTTP allowed"))
    with pytest.raises(Blocked):
        client.upload("job", setup[1], "private")
    with pytest.raises(Blocked):
        client.upload("job", setup[1], "private", metadata=META, approval="stale")


def test_oauth_state_and_single_use(setup):
    from urllib.parse import parse_qs, urlparse

    client = adapter(
        setup,
        lambda r: httpx.Response(
            200, json={"access_token": "new", "refresh_token": "refresh", "expires_in": 3600}
        ),
    )
    query = parse_qs(urlparse(client.begin_oauth()).query)
    assert query["scope"] == ["https://www.googleapis.com/auth/youtube.upload"]
    assert query["code_challenge_method"] == ["S256"]
    with pytest.raises(Blocked, match="state"):
        client.callback("wrong", "code", client.redirect)
    with pytest.raises(Blocked):
        client.callback(query["state"][0], "code", "http://evil.invalid")
    client.callback(query["state"][0], "code", client.redirect)
    with pytest.raises(Blocked):
        client.callback(query["state"][0], "code", client.redirect)


@pytest.mark.parametrize("revoked", [False, True])
def test_refresh_expired_and_revoked(setup, revoked):
    def handler(r):
        assert r.url.path == "/token"
        assert b"grant_type=refresh_token" in r.content
        return (
            httpx.Response(400, json={"error": "invalid_grant", "secret": "SECRET_RESPONSE"})
            if revoked
            else httpx.Response(200, json={"access_token": "renewed", "expires_in": 3600})
        )

    client = adapter(setup, handler)
    with setup[0].connect() as db:
        client.vault.write(
            db, "tokens", {"access_token": "expired", "refresh_token": "refresh", "expires": 0}
        )
    if revoked:
        with pytest.raises(Blocked, match="reauthentication"):
            client.access_token()
        with setup[0].connect() as db:
            assert client.vault.read(db, "tokens") is None
    else:
        assert client.access_token() == "renewed"


@pytest.mark.parametrize("status", [200, 308, 404, 403])
def test_timeout_then_probe_never_new_upload(setup, status, caplog):
    caplog.set_level("INFO")
    calls = []

    def handler(r):
        calls.append(r)
        if r.method == "POST":
            return httpx.Response(200, headers={"Location": SESSION})
        if len(calls) == 2:
            raise httpx.ReadTimeout("SECRET_TIMEOUT " + SESSION)
        if r.headers["content-range"].startswith("bytes */"):
            return httpx.Response(status, json={"id": "completed"}, headers={"Range": "bytes=0-3"})
        assert r.content == setup[1].read_bytes()[4:]
        return httpx.Response(200, json={"id": "completed"})

    client = adapter(setup, handler)
    with pytest.raises(Blocked) as error:
        send(client, setup)
    assert "SECRET" not in str(error.value)
    with setup[0].connect() as db:
        attempt = client.vault.read(db, "upload:job")
        attempt["retry_at"] = 0
        client.vault.write(db, "upload:job", attempt)
    if status in (200, 308):
        assert send(client, setup)["youtube_video_id"] == "completed"
    else:
        with pytest.raises(Blocked):
            send(client, setup)
    assert sum(r.method == "POST" for r in calls) == 1
    assert "SECRET" not in caplog.text


def test_initiation_timeout_crash_pause_and_limits(setup):
    calls = []

    def handler(r):
        calls.append(r)
        raise httpx.ReadTimeout("secret")

    client = adapter(setup, handler)
    with setup[0].connect() as db:
        db.execute("UPDATE system_state SET paused=1")
    with pytest.raises(Blocked, match="paused"):
        send(client, setup)
    assert not calls
    with setup[0].connect() as db:
        db.execute("UPDATE system_state SET paused=0")
    with pytest.raises(Blocked):
        send(client, setup)
    with pytest.raises(Blocked):
        send(client, setup)
    assert len(calls) == 1
    with setup[0].connect() as db:
        item = client.vault.read(db, "upload:job")
        item.update(session=SESSION, busy=True, started=0)
        client.vault.write(db, "upload:job", item)
    with pytest.raises(Blocked):
        send(client, setup)
    client.recover_interrupted("job")
    with setup[0].connect() as db:
        item = client.vault.read(db, "upload:job")
        item.update(calls=3, retry_at=0)
        client.vault.write(db, "upload:job", item)
    with pytest.raises(Blocked, match="limit"):
        send(client, setup)
    assert len(calls) == 1


def test_artifact_or_metadata_change_invalidates_workflow_approval(tmp_path):
    from fastapi.testclient import TestClient

    path = tmp_path / "db"
    client = TestClient(create_app(Settings(database_path=str(path), _env_file=None)))
    job = client.post("/jobs", json={"topic": "Test binding"}).json()["id"]
    client.post(f"/jobs/{job}/run")
    client.post(f"/jobs/{job}/approval", json={"approved": True})
    (tmp_path / "videos" / f"{job}.mp4").write_bytes(b"changed")
    assert client.post(f"/jobs/{job}/run").status_code == 502
    state = client.get(f"/jobs/{job}/workflow").json()
    assert state["steps"][4]["status"] == "pending"
    assert state["steps"][5]["status"] == "failed"


def test_revocation_and_upload_401(setup):
    def handler(r):
        if r.url.path == "/revoke":
            return httpx.Response(200)
        if r.method == "POST":
            return httpx.Response(200, headers={"Location": SESSION})
        return httpx.Response(401, json={"secret": "DO_NOT_LOG"})

    client = adapter(setup, handler)
    with pytest.raises(Blocked):
        send(client, setup)
    with setup[0].connect() as db:
        assert client.vault.read(db, "tokens") is None
    client = adapter(setup, handler)
    client.revoke()
    with pytest.raises(Blocked, match="authentication"):
        client.access_token()


def test_restart_probes_persisted_session(setup):
    key = SecretStr(Fernet.generate_key().decode())
    args = dict(
        enabled=True,
        vault_key=key,
        client_id="test",
        client_secret=SecretStr("test"),
        redirect_uri="http://127.0.0.1:8765/callback",
    )

    def interrupted(r):
        if r.method == "POST":
            return httpx.Response(200, headers={"Location": SESSION})
        raise httpx.ReadTimeout("secret")

    first = YouTube(setup[0], **args, transport=httpx.MockTransport(interrupted))
    with setup[0].connect() as db:
        first.vault.write(db, "tokens", {"access_token": "secret", "expires": time.time() + 3600})
    with pytest.raises(Blocked):
        send(first, setup)
    with setup[0].connect() as db:
        attempt = first.vault.read(db, "upload:job")
        attempt["retry_at"] = 0
        first.vault.write(db, "upload:job", attempt)

    def resumed(r):
        assert r.method == "PUT"
        assert r.headers["content-range"].startswith("bytes */")
        return httpx.Response(200, json={"id": "recovered"})

    second = YouTube(Store(setup[0].path), **args, transport=httpx.MockTransport(resumed))
    assert send(second, setup)["youtube_video_id"] == "recovered"


def test_settings_disabled_and_metadata_change(setup):
    with pytest.raises(Blocked, match="disabled"):
        YouTube.from_settings(setup[0], Settings(_env_file=None))
    client = adapter(setup, lambda r: pytest.fail("No HTTP allowed"))
    approved = fingerprint(setup[1], Metadata(**META).payload())
    with pytest.raises(Blocked, match="stale"):
        client.upload(
            "job", setup[1], "private", metadata={**META, "title": "Changed"}, approval=approved
        )
