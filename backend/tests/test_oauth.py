import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.store import Store
from app.youtube import YouTube

ORIGIN = "http://127.0.0.1:8000"
TOKEN = "x" * 40


@pytest.fixture
def setup(tmp_path):
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(
            200, json={"access_token": "SECRET_TOKEN", "refresh_token": "SECRET_REFRESH"}
        )

    settings = Settings(
        database_path=str(tmp_path / "db"),
        api_token=TOKEN,
        youtube_enabled=True,
        youtube_redirect_uri=ORIGIN + "/oauth/youtube/callback",
        _env_file=None,
    )
    store = Store(settings.database_path)
    adapter = YouTube(
        store,
        enabled=True,
        vault_key=SecretStr(Fernet.generate_key().decode()),
        client_id="test",
        client_secret=SecretStr("secret"),
        redirect_uri=settings.youtube_redirect_uri,
        transport=httpx.MockTransport(handler),
    )
    client = TestClient(create_app(settings, youtube=adapter), base_url=ORIGIN)
    return client, adapter, settings, calls


def login(client):
    r = client.post(
        "/owner/session", headers={"Origin": ORIGIN, "Authorization": "Bearer " + TOKEN}
    )
    assert r.status_code == 200
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=lax" in r.headers["set-cookie"]


def begin(client):
    r = client.post("/oauth/youtube/start", headers={"Origin": ORIGIN})
    assert r.status_code == 200
    return parse_qs(urlparse(r.text).query)["state"][0]


def test_owner_callback_and_single_exchange(setup, caplog):
    client, adapter, settings, calls = setup
    assert client.post("/oauth/youtube/start", headers={"Origin": ORIGIN}).status_code == 401
    login(client)
    state = begin(client)
    url = f"/oauth/youtube/callback?state={state}&code=SECRET_CODE"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.get(url), range(2)))
    assert sorted(r.status_code for r in results) == [200, 400]
    assert len(calls) == 1
    assert "SECRET" not in "".join(r.text for r in results) + caplog.text
    assert client.post("/owner/logout", headers={"Origin": ORIGIN}).status_code == 200
    assert client.get(url).status_code == 401


def test_foreign_expired_csrf_and_disabled(setup):
    client, adapter, settings, calls = setup
    assert (
        client.post(
            "/owner/session",
            headers={"Origin": "https://evil.invalid", "Authorization": "Bearer " + TOKEN},
        ).status_code
        == 403
    )
    login(client)
    state = begin(client)
    foreign = TestClient(client.app, base_url=ORIGIN)
    login(foreign)
    assert foreign.get(f"/oauth/youtube/callback?state={state}&code=code").status_code == 400
    assert client.get("/oauth/youtube/callback?state=wrong&code=code").status_code == 400
    with adapter.store.connect() as db:
        for row in db.execute(
            "SELECT name FROM youtube_vault WHERE name LIKE 'oauth:%'"
        ).fetchall():
            item = adapter.vault.read(db, row[0])
            item["expires"] = 0
            adapter.vault.write(db, row[0], item)
    assert client.get(f"/oauth/youtube/callback?state={state}&code=code").status_code == 400
    settings.youtube_enabled = False
    assert client.post("/oauth/youtube/start", headers={"Origin": ORIGIN}).status_code == 503
    assert not calls


def test_cancel_token_error_redirect_and_expired_session(setup):
    client, adapter, settings, calls = setup
    login(client)
    state = begin(client)
    assert (
        client.get(f"/oauth/youtube/callback?state={state}&error=access_denied").status_code == 200
    )
    assert not calls
    assert client.get(f"/oauth/youtube/callback?state={state}&code=x").status_code == 400
    state = begin(client)
    adapter.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"secret": "SECRET_ERROR"})
        )
    )
    r = client.get(f"/oauth/youtube/callback?state={state}&code=SECRET_CODE")
    assert r.status_code == 400 and "SECRET" not in r.text
    with adapter.store.connect() as db:
        db.execute("UPDATE owner_sessions SET expires=?", (time.time() - 1,))
    assert client.post("/oauth/youtube/start", headers={"Origin": ORIGIN}).status_code == 401
    settings.youtube_redirect_uri = "https://example.com/callback"
    assert (
        client.post(
            "/owner/session", headers={"Origin": ORIGIN, "Authorization": "Bearer " + TOKEN}
        ).status_code
        == 503
    )


def test_invalid_redirect_port_is_safely_blocked(setup):
    client, adapter, settings, calls = setup
    settings.youtube_redirect_uri = "http://127.0.0.1:bad/oauth/youtube/callback"
    assert (
        client.post(
            "/owner/session", headers={"Origin": ORIGIN, "Authorization": "Bearer " + TOKEN}
        ).status_code
        == 503
    )
    assert not calls
