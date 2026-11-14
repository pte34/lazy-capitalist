# Status — 2026-11-14

## Verified starting point and scope

Started from clean local/remote dda3bc1 on feat/local-oauth-video-reporting, matching open Draft PR https://github.com/pte34/lazy-capitalist/pull/1. Historical remote CI was green. This task preserves that branch, history and the original public migration. No merge, deployment, cloud provisioning, production-data transfer, paid call, real OAuth/upload or real notification occurred.

## PostgreSQL runtime and targeted review

SQLite remains the explicit offline default; PostgreSQL mode now runs all existing services through the same Store/query logic. DATABASE_MODE, protected DATABASE_URL, strong owner API_TOKEN and explicit ARTIFACT_DIR are required. No connection/schema failure falls back to SQLite or memory. Application roles have no DDL or schema-version-write privileges.

Private lc_runtime has all 21 actual business tables plus migration metadata: jobs/steps/attempt counters, commands/plans, USD and CHF ledgers, artifact/approval JSON, encrypted OAuth/upload data, owner sessions, platform events/locks, reports/preferences/outbox and audit history. Four additive CLI-generated migrations add native numeric/timestamp/BYTEA types, constraints, indexes and 64-bit-compatible references. Public planning tables are unchanged; no managed Supabase deployment is implied.

Review fixes: resource-scoped transaction locks replace SQLite-only write assumptions; provider HTTP remains outside DB transactions. Workflow/outbox/encrypted-upload fencing rejects late workers. Render files are staged by claim and promoted only by the accepted worker; local lease is 600 seconds. OAuth consumption rechecks owner-session validity; approval prerequisites/metadata and channel gates are checked inside their relevant resource transaction. Reports use a consistent PostgreSQL snapshot and bounded retries only for known aborted database conflicts. Connection failure messages redact credentials. Targeted review is NOT a completed production security audit; remaining points are in docs/PERSISTENCE_REVIEW.md.

## Migrations and synthetic transfer

Explicit migration runner tracks checksums and applies each file plus history atomically. Empty and previously foundation-initialized databases, repeat application and checksum mismatch were tested. Applied migrations were not edited. Runtime startup only validates versions/tables. Separate synthetic-only SQLite import has preview, read-only integrity validation, insert/equal/conflict accounting, atomic rollback/no overwrite and replay support. Ciphertext, decimals, fractional timestamps and references above 32-bit range are preserved. No existing local user dataset was automatically transferred or deleted, and no video bytes are inserted into database blobs.

## Actual verification

95 local tests passed: 80 SQLite/configuration tests and 15 actual PostgreSQL integration tests. These cover complete workflows/commands and real local rendering, independent-connection USD/CHF reservations, idempotent requests, exclusive claims, stale-renderer/outbox fences, actual child-process exit plus fresh-process resume, single-consumer OAuth state, channel locks, reports/outbox, rollback, private RLS/role privileges, migrations/import and API 503/no fallback on database outage. Google HTTP and delivery are mocked; no provider credentials required.

PostgreSQL browser smokes passed for the five-video Command Center, reports/mock notifications and owner-cookie/disabled OAuth receiver. The five browser-created video links were confirmed directly in PostgreSQL. Frontend lint/build/types and Python lint/format passed. The existing upstream Starlette test-client deprecation warning remains. Supabase Advisors was attempted but could not complete because its CLI connection refused the isolated non-TLS test instance; no production TLS setting was weakened. Native PostgreSQL RLS/grant/index/constraint checks are tested, not a substitute for hosted security review.

CI now includes postgres-runtime running actual application tests against its own isolated PostgreSQL 17 service; default offline tests skip those fixtures when PG_TEST_ADMIN_URL is absent. Final remote SHA, newest CI result and links are in the completion handoff/PR Checks. Latest local work is backed up as a verified Git bundle under ignored work/.

## Remaining prerequisites and owner action

See docs/CLOUD_READINESS.md: hosted owner auth, distinct hosted OAuth, external secret/key operations, reviewed managed TLS/pooling/connection limits, durable shared artifact storage, reliable workers/scheduler and monitoring/backup/restore drills. Local artifact promotion is not a distributed DB/file transaction. Actual billing remains owner/estimated data and ambiguous actions require reconciliation. These gaps are not provisioned or priced here; Phase 1 cloud acceptance stays open.

Owner action for this development handoff: review the updated draft PR; no credentials, cloud activation or spending approval are needed for the completed local tests. Any real data transfer, provider activation, merge or deployment requires separate scope/approval. No additional product features were begun.

## Required future completion convention

Exactly one copyable block headed LAZY CAPITALIST – CODEX HANDOFF, eight sections:
1. Stand — phase, branch, local/verified remote SHA, dirty state, PR/CI link/result, deployment.
2. Umgesetzt — review fixes, database integration/paths, migrations and modes (or requested package status).
3. Verifikation — executed tests, actual PostgreSQL/concurrency/restart/browser checks, omitted checks/reasons.
4. Funktionsstatus — verified, local/mock, externally unverified and missing.
5. Blocker und Owner-Aktionen — concrete uncertainty and smallest action or none.
6. Kosten und externe Aktionen — actual GitHub writes/services/paid calls and cost knowledge; never count simulation as real.
7. Offene Arbeiten — priorities with acceptance criteria.
8. Nächster empfohlener Auftrag — exactly one bounded goal, prerequisites and approvals.
Preserve AGENTS.md and owner authorization boundaries.
