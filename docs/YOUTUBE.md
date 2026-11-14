# Private YouTube adapter — disabled, offline-tested

`app.youtube.YouTube` implements a resumable-upload library behind the existing Publisher contract. The application still selects `SimulatedYouTube`; there is no reachable OAuth callback, connect button or real-upload HTTP route. Setting YOUTUBE_ENABLED alone does not switch publishing. Do not wire or activate real use without a separate owner-authorized integration review and live-test approval.

## Configuration and token protection

Server-only names: `YOUTUBE_ENABLED` (false), `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_URI`, `YOUTUBE_TOKEN_KEY`. The last value is a Fernet key supplied by protected server secret storage. It must be backed up separately from the database, never logged, committed, exposed via NEXT_PUBLIC, or stored alongside encrypted records. Loss of the key makes stored credentials/sessions unavailable; do not silently reinitialize them. Production secret management, key rotation and deployment are not provisioned.

`YouTube.from_settings(store, settings)` fails closed when disabled or configuration is incomplete. Constructor injection and `httpx.MockTransport` support offline tests. No example contains actual credentials. Tests generate ephemeral keys.

The intended application is a local owner-operated OAuth Desktop client using a registered loopback redirect on 127.0.0.1, PKCE S256, a random ten-minute single-use state, exact callback URI matching and the sole scope `youtube.upload`. `begin_oauth` and `callback` are library methods only: the secure loopback receiver, owner session binding and login UX still need implementation before use. No OAuth URL was opened in this task. Concurrent login beginnings intentionally replace the previous pending state.

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
