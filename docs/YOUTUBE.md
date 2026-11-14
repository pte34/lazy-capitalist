# Private YouTube adapter — disabled, offline-tested

`app.youtube.YouTube` implements a resumable-upload library behind the existing Publisher contract. The application still selects `SimulatedYouTube`; a protected loopback OAuth receiver is implemented, but live OAuth is disabled and no real-upload HTTP route exists. Setting YOUTUBE_ENABLED alone does not switch publishing. Do not activate real use without separate owner authorization and live-test approval.

## Configuration and token protection

Server-only names: `YOUTUBE_ENABLED` (false), `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_URI`, `YOUTUBE_TOKEN_KEY`. The last value is a Fernet key supplied by protected server secret storage. It must be backed up separately from the database, never logged, committed, exposed via NEXT_PUBLIC, or stored alongside encrypted records. Loss of the key makes stored credentials/sessions unavailable; do not silently reinitialize them. Production secret management, key rotation and deployment are not provisioned.

`YouTube.from_settings(store, settings)` fails closed when disabled or configuration is incomplete. Constructor injection and `httpx.MockTransport` support offline tests. No example contains actual credentials. Tests generate ephemeral keys.

The intended application is a local owner-operated OAuth Desktop client using a registered loopback redirect on 127.0.0.1, PKCE S256, a random ten-minute single-use state, exact callback URI matching and the sole scope `youtube.upload`. `begin_oauth` and `callback` now back protected local receiver routes with owner-session binding; see the local callback section below. No OAuth URL was opened in this task. Concurrent login beginnings from the same owner session intentionally replace its previous pending state; foreign sessions cannot consume it.

Access/refresh tokens, OAuth verifier/state, resumable session URLs and video IDs are encrypted in SQLite `youtube_vault`; keys stay external. Refresh rotates returned tokens; invalid-grant responses clear local tokens and require owner login. Revocation clears stored tokens only after confirmation; ambiguous revocation requires owner follow-up. HTTP debug logging is unsuitable for secret-bearing endpoints; httpx/httpcore INFO/DEBUG logs are suppressed by the adapter, and errors expose no upstream bodies or URLs.

## Artifact and upload semantics

Owner approval binds the video bytes and canonical metadata hash: title, script description, private visibility, audience declaration and synthetic-content declaration. Changed artifacts or metadata block uploading and invalidate workflow approval. Existing legacy approvals without a hash fail closed. Real adapter use requires explicit audience/synthetic fields, valid MP4 video verified with ffprobe, and an immutable byte snapshot (32 MiB local MVP maximum). Public/unlisted and extra fields such as publishAt are rejected. This does not establish legal/media/platform-policy compliance; owner review remains required.

The encrypted attempt is durably written before initiation. The session URL is persisted before uploading bytes. A retry first probes that exact session with `Content-Range: bytes */total`; 308 resumes from the confirmed Range, 200/201 records completion. A timeout during initiation without a known session blocks all new initiation for that job. Expired/unknown/denied session outcomes require reconciliation; unlike the generic Google example, this implementation deliberately does NOT start a replacement session automatically on 404. No exactly-once delivery guarantee is claimed.

Concurrent/abandoned busy attempts block. After at least 120 seconds, `recover_interrupted` may release only a known session for a status probe, never create another upload. There are at most three upload invocations per attempt with persisted exponential backoff; API quota errors stop the invocation and preserve the attempt. Exhaustion requires owner investigation. Google project quota/verification and live error behavior are unverified; no hardcoded daily Google quota availability is promised. Pause is checked at admission and before each HTTP request; already admitted/in-flight traffic cannot be recalled.

## Safe verification

`cd backend && uv sync --locked && uv run pytest && uv run ruff check . && uv run ruff format --check .`

FFmpeg/ffprobe are needed. All Google traffic in tests uses MockTransport and generated local MP4s. No login, real quota, live token refresh, revoke or upload is tested. SQLite remains local-only; neither Supabase runtime integration nor cloud auth is implied.

Official references read for this implementation:
- https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
- https://developers.google.com/youtube/v3/docs/videos/insert
- https://developers.google.com/youtube/v3/docs/videos
- https://developers.google.com/identity/protocols/oauth2/native-app
- https://developers.google.com/identity/protocols/oauth2/web-server

## Local callback receiver (implemented)

The backend now exposes `/owner/session`, `/owner/logout`, `/oauth/youtube/start` and `/oauth/youtube/callback`. This is strictly the local Desktop loopback flow, not a hosted web callback. Use a Google Desktop client and fixed `http://127.0.0.1:<backend-port>/oauth/youtube/callback`. A 32+ character API_TOKEN is required even in local mode to bootstrap the owner session. POST operations require that exact backend Origin and Host. The one-hour host-only HttpOnly SameSite=Lax cookie allows Google's top-level callback while preventing cross-site POSTs; Secure is deliberately false only for HTTP loopback. OAuth state is encrypted and bound to the hashed server-side session, with atomic single consumption before token exchange. Logout/expiry block callbacks. Callback query strings are removed from ASGI access logging; responses never contain codes/tokens. No arbitrary redirects are accepted. Start returns the authorization URL without navigating automatically.

YOUTUBE_ENABLED remains false; disabled endpoints fail before any Google request. Owner must separately authorize any actual login. MockTransport integration tests exercise the receiver without visiting Google. The publisher remains simulated regardless of OAuth connectivity.

Browser smoke: `SMOKE_API_TOKEN=<local-test-owner-token> python tests/smoke_callback.py` with the local backend configured with that same test-only token, redirect on port 8000 and YOUTUBE_ENABLED=false. This checks the HttpOnly owner cookie and blocked Google start/callback without opening Google or storing tokens in browser storage. Do not use production tokens for the smoke.
