"""Opt-in, offline-tested YouTube integration. Not wired to public HTTP routes."""

import base64
import hashlib
import json
import logging
import re
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.platforms import publication_guard
from app.store import Store

# httpx INFO logs include capability-bearing resumable URLs. Never emit them.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class Blocked(RuntimeError):
    """Safe error: never include provider bodies, credentials or session URLs."""


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=5000)
    privacy: str = "private"
    made_for_kids: bool
    synthetic_media: bool

    def payload(self):
        if self.privacy != "private":
            raise Blocked("Only private visibility supported")
        return {
            "snippet": {"title": self.title, "description": self.description},
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": self.made_for_kids,
                "containsSyntheticMedia": self.synthetic_media,
            },
        }


def fingerprint(video: Path, metadata: dict) -> str:
    digest = hashlib.sha256()
    with video.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode())
    return digest.hexdigest()


class Vault:
    def __init__(self, store: Store, key: SecretStr | None):
        if not key:
            raise Blocked("Secure token storage key missing")
        try:
            self.cipher = Fernet(key.get_secret_value().encode())
        except Exception:
            raise Blocked("Invalid secure token storage configuration") from None
        self.store = store
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS youtube_vault (name TEXT PRIMARY KEY, ciphertext BLOB NOT NULL)"
            )

    def read(self, db, name):
        row = db.execute("SELECT ciphertext FROM youtube_vault WHERE name=?", (name,)).fetchone()
        try:
            return json.loads(self.cipher.decrypt(row[0])) if row else None
        except Exception:
            raise Blocked("Secure storage unavailable") from None

    def write(self, db, name, value):
        db.execute(
            "INSERT OR REPLACE INTO youtube_vault VALUES(?,?)",
            (name, self.cipher.encrypt(json.dumps(value).encode())),
        )


class YouTube:
    def __init__(
        self,
        store: Store,
        *,
        enabled=False,
        vault_key: SecretStr | None = None,
        client_id="",
        client_secret: SecretStr | None = None,
        redirect_uri="",
        transport=None,
    ):
        if not enabled:
            raise Blocked("Real YouTube adapter disabled")
        redirect = urlparse(redirect_uri)
        if (
            not client_id
            or not client_secret
            or redirect.scheme != "http"
            or redirect.hostname != "127.0.0.1"
            or not redirect.port
            or redirect.username
            or redirect.password
            or redirect.query
            or redirect.fragment
        ):
            raise Blocked("Owner OAuth loopback configuration missing")
        self.store = store
        self.vault = Vault(store, vault_key)
        self.client_id, self.client_secret, self.redirect = client_id, client_secret, redirect_uri
        self.http = httpx.Client(transport=transport, timeout=30, follow_redirects=False)

    @classmethod
    def from_settings(cls, store, settings, **kwargs):
        return cls(
            store,
            enabled=settings.youtube_enabled,
            vault_key=settings.youtube_token_key,
            client_id=settings.youtube_client_id,
            client_secret=settings.youtube_client_secret,
            redirect_uri=settings.youtube_redirect_uri,
            **kwargs,
        )

    def paused(self, db):
        if db.execute("SELECT paused FROM system_state WHERE id=1").fetchone()[0]:
            raise Blocked("System paused")

    def request(self, method, url, **kwargs):
        with self.store.connect() as db:
            self.paused(db)
        try:
            return self.http.request(method, url, **kwargs)
        except Exception:
            raise Blocked("External outcome uncertain; reconciliation required") from None

    def begin_oauth(self, owner_session=""):
        name = "oauth:" + owner_session if owner_session else "oauth"
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        with self.store.connect() as db:
            self.paused(db)
            self.vault.write(
                db, name, {"state": state, "verifier": verifier, "expires": time.time() + 600}
            )
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect,
                "response_type": "code",
                "scope": "https://www.googleapis.com/auth/youtube.upload",
                "state": state,
                "access_type": "offline",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )

    def consume_oauth(self, state, redirect_uri, owner_session=""):
        name = "oauth:" + owner_session if owner_session else "oauth"
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.paused(db)
            pending = self.vault.read(db, name)
            if (
                not pending
                or pending["expires"] < time.time()
                or redirect_uri != self.redirect
                or not secrets.compare_digest(pending["state"], state)
            ):
                raise Blocked("Invalid OAuth state or callback")
            db.execute("DELETE FROM youtube_vault WHERE name=?", (name,))
        return pending

    def callback(self, state, code, redirect_uri, owner_session=""):
        pending = self.consume_oauth(state, redirect_uri, owner_session)
        self.token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect,
                "code_verifier": pending["verifier"],
            }
        )

    def token_request(self, data):
        with self.store.connect() as db:
            self.paused(db)
        response = self.request(
            "POST",
            "https://oauth2.googleapis.com/token",
            data={
                **data,
                "client_id": self.client_id,
                "client_secret": self.client_secret.get_secret_value(),
            },
        )
        if response.status_code != 200:
            if response.status_code in (400, 401):
                with self.store.connect() as db:
                    db.execute("DELETE FROM youtube_vault WHERE name='tokens'")
            raise Blocked("OAuth failed; owner reauthentication required")
        tokens = response.json()
        with self.store.connect() as db:
            old = self.vault.read(db, "tokens") or {}
            if not tokens.get("access_token"):
                raise Blocked("OAuth response invalid")
            self.vault.write(
                db,
                "tokens",
                {**old, **tokens, "expires": time.time() + tokens.get("expires_in", 3600) - 60},
            )

    def access_token(self):
        with self.store.connect() as db:
            tokens = self.vault.read(db, "tokens")
        if not tokens:
            raise Blocked("Owner authentication required")
        if tokens["expires"] <= time.time():
            if not tokens.get("refresh_token"):
                raise Blocked("Owner reauthentication required")
            self.token_request(
                {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
            )
            with self.store.connect() as db:
                tokens = self.vault.read(db, "tokens")
        return tokens["access_token"]

    def revoke(self):
        with self.store.connect() as db:
            self.paused(db)
            tokens = self.vault.read(db, "tokens")
        if tokens:
            response = self.request(
                "POST",
                "https://oauth2.googleapis.com/revoke",
                data={"token": tokens.get("refresh_token", tokens["access_token"])},
            )
            if response.status_code != 200:
                raise Blocked("Revocation not confirmed")
        with self.store.connect() as db:
            db.execute("DELETE FROM youtube_vault WHERE name IN ('tokens','oauth')")

    def upload(self, job_id, video, privacy, *, metadata=None, approval=None):
        if privacy != "private" or metadata is None or approval is None:
            raise Blocked("Private metadata and artifact approval required")
        with self.store.connect() as db:
            publication_guard(db, job_id)
        payload = Metadata.model_validate(metadata).payload()
        # Read once: uploaded bytes and approved hash must describe the same immutable snapshot.
        if video.stat().st_size > 32 * 1024 * 1024:
            raise Blocked("Local MVP upload limit is 32 MiB")
        content = video.read_bytes()
        digest = hashlib.sha256(content)
        digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        artifact = digest.hexdigest()
        if approval != artifact:
            raise Blocked("Artifact approval stale or missing")
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type:format=format_name",
                    "-of",
                    "json",
                    str(video),
                ],
                capture_output=True,
                timeout=10,
                check=True,
            )
            info = json.loads(probe.stdout)
            if "mp4" not in info["format"]["format_name"] or not any(
                s["codec_type"] == "video" for s in info["streams"]
            ):
                raise ValueError("Invalid media")
            if video.read_bytes() != content:
                raise ValueError("Artifact changed during validation")
        except Exception:
            raise Blocked("Validated, immutable MP4 artifact required") from None
        name = "upload:" + job_id
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.paused(db)
            attempt = self.vault.read(db, name)
            if attempt and attempt["artifact"] != artifact:
                raise Blocked("Existing upload belongs to different artifact")
            if attempt and attempt["state"] == "complete":
                return {
                    "simulation": False,
                    "privacy": "private",
                    "youtube_video_id": attempt["id"],
                }
            if attempt and attempt.get("busy"):
                raise Blocked("Reconciliation required: interrupted or active request")
            if attempt and not attempt.get("session"):
                raise Blocked("Reconciliation required: session initiation uncertain")
            attempt = attempt or {"artifact": artifact, "state": "initiating", "calls": 0}
            if attempt["calls"] >= 3 or attempt.get("retry_at", 0) > time.time():
                raise Blocked("Upload retry/quota limit reached")
            attempt.update(busy=True, started=time.time(), calls=attempt["calls"] + 1)
            self.vault.write(db, name, attempt)
            db.execute("INSERT INTO audit_events(action) VALUES(?)", ("youtube_real_attempt",))
        try:
            with self.store.connect() as db:
                publication_guard(db, job_id)
            token = self.access_token()
            headers = {"Authorization": "Bearer " + token}
            if not attempt.get("session"):
                response = self.request(
                    "POST",
                    "https://www.googleapis.com/upload/youtube/v3/videos",
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    headers={
                        **headers,
                        "X-Upload-Content-Length": str(len(content)),
                        "X-Upload-Content-Type": "video/mp4",
                    },
                    json=payload,
                )
                if response.status_code != 200:
                    raise Blocked("Upload initiation rejected; reconciliation required")
                session = response.headers.get("location", "")
                parsed = urlparse(session)
                if (
                    parsed.scheme != "https"
                    or parsed.netloc != "www.googleapis.com"
                    or not parsed.path.startswith("/upload/youtube/v3/videos")
                ):
                    raise Blocked("Invalid upload session endpoint")
                attempt.update(session=session, state="uploading")
                self.save(name, attempt)
                offset = 0
            else:
                response = self.request(
                    "PUT",
                    attempt["session"],
                    headers={
                        **headers,
                        "Content-Length": "0",
                        "Content-Range": f"bytes */{len(content)}",
                    },
                )
                if response.status_code in (200, 201):
                    return self.complete(name, attempt, response)
                if response.status_code != 308:
                    raise Blocked("Upload status ambiguous; no new upload permitted")
                match = re.fullmatch(r"bytes=0-(\d+)", response.headers.get("range", ""))
                if response.headers.get("range") and not match:
                    raise Blocked("Upload range ambiguous")
                offset = int(match[1]) + 1 if match else 0
                if not 0 <= offset < len(content):
                    raise Blocked("Upload offset ambiguous")
            with self.store.connect() as db:
                self.paused(db)
                publication_guard(db, job_id)
            response = self.request(
                "PUT",
                attempt["session"],
                headers={
                    **headers,
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes {offset}-{len(content) - 1}/{len(content)}",
                },
                content=content[offset:],
            )
            if response.status_code in (200, 201):
                return self.complete(name, attempt, response)
            if response.status_code == 401:
                with self.store.connect() as db:
                    db.execute("DELETE FROM youtube_vault WHERE name='tokens'")
            raise Blocked("Upload incomplete or quota denied; reconcile existing session")
        except Exception:
            attempt.update(
                busy=False,
                state="reconciliation_required",
                retry_at=time.time() + 2 ** attempt["calls"],
            )
            self.save(name, attempt)
            raise Blocked(
                "Upload not confirmed; reconcile existing attempt, never restart"
            ) from None

    def recover_interrupted(self, job_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.paused(db)
            name = "upload:" + job_id
            attempt = self.vault.read(db, name)
            if (
                not attempt
                or not attempt.get("session")
                or time.time() - attempt.get("started", 0) < 120
            ):
                raise Blocked("Manual reconciliation required or request still active")
            attempt.update(busy=False, state="reconciliation_required")
            self.vault.write(db, name, attempt)
        # Next upload invocation MUST probe this existing session before sending data.

    def save(self, name, attempt):
        with self.store.connect() as db:
            self.vault.write(db, name, attempt)

    def complete(self, name, attempt, response):
        video_id = response.json().get("id")
        if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", video_id):
            raise Blocked("Upload completion ambiguous")
        attempt.update(state="complete", id=video_id, busy=False)
        self.save(name, attempt)
        return {"simulation": False, "privacy": "private", "youtube_video_id": video_id}
