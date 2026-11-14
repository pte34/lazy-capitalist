"""Local Desktop OAuth receiver; no hosted web callback or live mode by default."""

import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, Request, Response
from starlette.responses import PlainTextResponse

from app.youtube import Blocked, YouTube

COOKIE = "lc_owner"


class HideOAuthQuery:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/oauth/youtube/callback":
            scope.setdefault("state", {})["oauth_query"] = parse_qs(
                scope.get("query_string", b"").decode(), keep_blank_values=True
            )
            # uvicorn access logging also uses this scope: do not log codes or state.
            scope["query_string"] = b""
        await self.app(scope, receive, send)


def register_oauth(app, settings, store, injected=None):
    app.add_middleware(HideOAuthQuery)
    with store.connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS owner_sessions (digest TEXT PRIMARY KEY, expires REAL NOT NULL)"
        )

    def local(request):
        parsed = urlparse(settings.youtube_redirect_uri)
        if (
            settings.environment != "local"
            or parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or not parsed.port
            or parsed.path != "/oauth/youtube/callback"
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise HTTPException(503, "Local desktop callback not configured")
        origin = f"http://127.0.0.1:{parsed.port}"
        if request.headers.get("host") != parsed.netloc:
            raise HTTPException(403, "Loopback host required")
        return origin

    def csrf(request):
        if request.headers.get("origin") != local(request):
            raise HTTPException(403, "Same-origin owner request required")

    def owner(request):
        local(request)
        cookie = request.cookies.get(COOKIE, "")
        digest = hashlib.sha256(cookie.encode()).hexdigest()
        with store.connect() as db:
            row = db.execute(
                "SELECT expires FROM owner_sessions WHERE digest=?", (digest,)
            ).fetchone()
        if not cookie or not row or row[0] < time.time():
            raise HTTPException(401, "Owner session required")
        return digest

    def adapter():
        if not settings.youtube_enabled:
            raise HTTPException(503, "Live OAuth disabled")
        try:
            return injected if injected is not None else YouTube.from_settings(store, settings)
        except Exception:
            raise HTTPException(503, "Secure OAuth configuration unavailable") from None

    @app.post("/owner/session")
    def session(request: Request, response: Response):
        csrf(request)
        token = settings.api_token.get_secret_value() if settings.api_token else ""
        if len(token) < 32:
            raise HTTPException(503, "Strong owner API token required")
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(401, "Owner authorization required")
        cookie = secrets.token_urlsafe(32)
        with store.connect() as db:
            db.execute(
                "INSERT INTO owner_sessions VALUES(?,?)",
                (hashlib.sha256(cookie.encode()).hexdigest(), time.time() + 3600),
            )
        response.set_cookie(COOKIE, cookie, httponly=True, samesite="lax", max_age=3600, path="/")
        response.headers["Cache-Control"] = "no-store"
        return {"owner_session": True, "expires_in": 3600}

    @app.post("/owner/logout")
    def logout(request: Request, response: Response):
        csrf(request)
        digest = owner(request)
        with store.connect() as db:
            db.execute("DELETE FROM owner_sessions WHERE digest=?", (digest,))
        response.delete_cookie(COOKIE, path="/")
        return {"owner_session": False}

    @app.post("/oauth/youtube/start")
    def start(request: Request):
        csrf(request)
        digest = owner(request)
        try:
            url = adapter().begin_oauth(digest)
        except Blocked:
            raise HTTPException(400, "OAuth start blocked") from None
        return PlainTextResponse(
            url, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
        )

    @app.get("/oauth/youtube/callback")
    def callback(request: Request):
        digest = owner(request)
        query = request.state.oauth_query
        if any(len(v) != 1 for v in query.values()) or not query.get("state"):
            raise HTTPException(400, "Invalid OAuth response")
        client = adapter()
        try:
            if "error" in query:
                client.consume_oauth(query["state"][0], settings.youtube_redirect_uri, digest)
                message = "Google connection cancelled; no tokens exchanged."
            elif query.get("code"):
                client.callback(
                    query["state"][0], query["code"][0], settings.youtube_redirect_uri, digest
                )
                message = "Google connection stored server-side. Upload remains disabled."
            else:
                raise Blocked("Invalid callback")
        except Exception:
            raise HTTPException(400, "OAuth callback rejected; restart owner connection") from None
        return PlainTextResponse(
            message,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            },
        )
