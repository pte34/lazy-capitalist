# Targeted persistence review

Scope: PR #1 persistence, transaction boundaries, reservation/claim concurrency, authorization and restart. This is not an exhaustive security review.

Fixed:
- PostgreSQL uses the shared Store query path with explicit mode and fail-closed schema/connection handling; there is no SQLite/memory fallback or runtime DDL grant.
- Currency-budget, request, command, job, OAuth/session, channel, report and delivery operations now coordinate on specific transaction resources. No HTTP is held inside admission/completion transactions.
- Workflow/outbox/encrypted-upload claims now fence stale workers. Render output is claim-specific until acceptance; stale renderers cannot replace the served file. Local workflow lease is 600 seconds; exhausted orphaned mock deliveries fail rather than silently re-entering execution.
- OAuth consumption rechecks owner-session revocation/expiry under its owner lock, in addition to the single-use state transaction.
- Approval creation rechecks current prerequisite steps and metadata under the job lock. Publication admission rechecks current approval and channel lock.
- Reports use a consistent PostgreSQL snapshot with bounded retry only for known aborted database conflicts, not ambiguous connections/providers.
- Native numeric/timestamp/BYTEA types retain financial/ciphertext precision; 64-bit references/counters preserve SQLite ranges. Synthetic import refuses target conflicts and source mutation.

Remaining review points before production:
- The static owner bearer boundary and HTTP Desktop callback are not hosted owner authentication. Multiple tenants are not implemented.
- Filesystem promotion and database commit are not one atomic system. Durable/shared immutable storage and tested artifact recovery are required across hosts.
- Provider invoice amounts remain owner-supplied/estimated, not independently reconciled billing. Restore must not reset ambiguous reservations or replay paid calls.
- Actual Google channel identity, quota, refresh/revocation behavior and external-outcome reconciliation are unverified live; no automatic strike feed or guaranteed exactly-once upload exists.
- Managed TLS/pooling/limits, external key rotation, operational monitoring and production backups/restores are not provisioned or verified. See CLOUD_READINESS.md.
