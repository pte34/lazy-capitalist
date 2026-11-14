# PostgreSQL runtime (local verification, no cloud deployment)

The same FastAPI services now run on SQLite or PostgreSQL 17. Only the Store/SQL-dialect boundary differs; providers, workflow, commands, budget calculations, OAuth, channel gates and reporting remain shared. SQLite remains the credential-free local default. PostgreSQL never creates a SQLite file or falls back to memory on connection/schema failure.

## Explicit configuration

- `DATABASE_MODE=sqlite`: existing DATABASE_PATH and local behavior.
- `DATABASE_MODE=postgres`: requires server-only `DATABASE_URL`, explicit writable `ARTIFACT_DIR`, and API_TOKEN of at least 32 characters, including local mode.
- Supplying DATABASE_URL with SQLite mode is rejected rather than silently ignored.
- DATABASE_URL is a secret; do not use NEXT_PUBLIC variables, command-line DSNs for real accounts or commit .env files.
- API errors on database outage return a generic 503; startup with missing migrations/configuration fails closed. No provider call is automatically replayed after a connection failure.

Runtime data lives in private `lc_runtime`, separate from the original public planning schema. All 21 business tables plus schema metadata have RLS. PUBLIC has no schema access; anon/authenticated receive no runtime grants. The trusted NOLOGIN role `lazy_capitalist_runtime` receives backend DML, sequence usage and RLS access, not DDL or schema-version writes. An owner-provisioned login must inherit this role. This is a single-owner backend role, not hosted end-user authorization or an exposed Supabase client key.

Connections use UTC, 5-second connect/10-second lock/30-second statement and 60-second idle-transaction timeouts and disabled named prepared statements. They open per unit of work and close on commit/rollback. No pool service has been provisioned. Production TLS and pooler compatibility/limits require owner review; local tests deliberately use a non-TLS loopback instance.

## Migrations

Existing `20261114143000_foundation.sql` is unchanged. Four additive CLI-created migrations add private runtime tables, constraints, indexes and 64-bit SQLite-compatible references/counters. Video content remains on disk; BYTEA is used only for encrypted integration state. JSON payloads remain text to preserve existing serialized data and common application semantics. Money uses NUMERIC in PostgreSQL; CHF micro-unit ledgers use BIGINT; timestamps use TIMESTAMPTZ and API rows normalize UTC without losing fractional seconds.

Use an isolated local PostgreSQL instance or owner-reviewed existing database. Admin credentials are separate from application credentials:

```
# Set MIGRATION_DATABASE_URL securely in the environment first.
PYTHONPATH=backend uv run --project backend python -m app.migrate
```

For a plain empty PostgreSQL test cluster, create NOLOGIN roles anon and authenticated first (Supabase already has these). The integration-test fixtures do this only on an explicitly configured loopback test server. The original public foundation expects those roles.

For a database where the original foundation is already applied externally:

```
PYTHONPATH=backend uv run --project backend python -m app.migrate --runtime-only
```

That explicitly skips the old public foundation; it does not adopt or rewrite its history. The runner tracks filenames and SHA-256 in private lc_migrations.history and applies each script plus its history entry atomically. Re-running skips matching files; changed applied files fail. Application startup only verifies the required runtime version/tables, never executes PostgreSQL DDL. Supabase's migration runner may instead apply these reviewed files using its own history; do not mix runners without owner reconciliation.

## Transaction and recovery contract

`db.begin(resource)` means SQLite BEGIN IMMEDIATE or a PostgreSQL transaction-scoped advisory lock. Keys are specific to submission, job, command, currency budget, OAuth/owner session, upload attempt, channel, report generation or delivery. There is no global application mutex. Shared USD/CHF aggregates require their own currency/account reservation lock; unrelated work continues. Admin migration/import locks are separate maintenance operations.

Reservations, state changes and audit rows commit before any HTTP/provider action. Cost corrections take the same USD budget lock. Failed/ambiguous paid calls retain reservations. Known aborted reporting snapshot conflicts alone have three bounded retries; ambiguous network/commit outcomes never trigger a generic retry. Reports use REPEATABLE READ for a coherent aggregation snapshot, with idempotent keys/outbox jobs.

Workflow and mock-outbox claims have persisted fencing tokens. Late workers cannot overwrite newer step/delivery results. Rendering writes a claim-specific staging file; only the accepted claim promotes it to the current artifact. Interrupted local steps require explicit reconciliation after 600 seconds (longer than the renderer subprocess bounds). Mock delivery recovery remains 120 seconds, at most three attempts. Known YouTube sessions retain their separate 120-second status-probe rules and encrypted claim fence; unknown initiation never creates a replacement session automatically. No exactly-once external delivery guarantee is claimed.

Artifact promotion and DB commit are not a distributed transaction: a crash may leave an unserved staged/current file with a running DB step. Old artifacts are retained by hash, and reconciliation is required. All workers must use the same artifact directory until an owner-reviewed durable file adapter exists. Never automatically delete unknown artifacts.

## Synthetic insert-only data transfer

No existing local data is automatically imported, deleted or overwritten. `app.import_sqlite` is restricted to explicitly confirmed synthetic datasets (including any encrypted records), rejects non-mock providers/unknown tables, opens the source read-only, checks integrity/foreign keys, and limits imports to 50,000 rows. The operator assertion cannot prove that opaque ciphertext is synthetic: never point this tool at real credentials.

```
PYTHONPATH=backend uv run --project backend python -m app.import_sqlite /path/to/synthetic.db --synthetic-only
PYTHONPATH=backend uv run --project backend python -m app.import_sqlite /path/to/synthetic.db --synthetic-only --apply
```

MIGRATION_DATABASE_URL supplies the owner target connection. Preview reports insert/equal/conflict counts without modifying target rows. Apply requires a quiescent isolated target and takes table maintenance locks; PostgreSQL constraints validate the entire transaction. Existing equal primary keys are skipped, differing rows abort/rollback, and audit sequences only advance. Preview is not a substitute for final target unique/foreign-key constraint validation. Defaults must also match: e.g. a paused source conflicts with an unpaused target seed; an owner must explicitly align a fresh target or leave the import blocked. No automatic seed overwrite occurs.

References, decimals, fractional timestamps, encrypted bytes and stable IDs are preserved. Tests include audit references above 32-bit range. Encryption keys stay outside both databases. Video files are not copied or turned into blobs: separately preserve/copy the authorized artifact directory and verify hashes before choosing it as ARTIFACT_DIR. Unknown/running attempts stay unknown/running; import never resets spending or upload safety state.

## Tests and restoration

Set PG_TEST_ADMIN_URL to an isolated **loopback** PostgreSQL test administrator (CREATEDB/CREATEROLE), then run:

```
cd backend
uv sync --locked
uv run pytest tests
uv run pytest tests_pg
uv run ruff check .
uv run ruff format --check .
```

Without PG_TEST_ADMIN_URL, integration fixtures explicitly skip; CI has a dedicated PostgreSQL service job that actually executes them. Fixtures create/drop only their randomly named synthetic databases/logins. Browser tests use the normal Next.js dev server with matching server-side API token and PostgreSQL backend; no frontend persistence implementation is duplicated.

Before any real migration, create an owner-controlled pg_dump backup plus artifact inventory/hashes and separately protect the encryption key. Verify restore into a new isolated database, roles, migration checksums, ciphertext decryption and file hashes. This task tested synthetic import/replay/rollback, not a production backup restore. Roll back application code only to a schema-compatible version; do not drop private tables, run destructive down migrations or silently switch to an older SQLite dataset. Stop workers before restoration and reconcile ambiguous provider/billing state before restarting. SQLite source files remain available and unchanged, but database switching is an explicit owner decision, not failover.
