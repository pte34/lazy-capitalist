# Architecture

Next.js is the owner dashboard. FastAPI executes the content workflow. SQLite is a persistent, zero-service local store. PostgreSQL migrations prepare the future Supabase data model; SQLite is not a Supabase emulator and there is no live PostgreSQL runtime adapter yet.

Workflow: validated topic → provider → structured concept and script → Pydantic validation → persisted result/status → usage and audit events. The mock provider is deterministic. OpenAI produces concept and script in one structured-output request to minimize spend. The provider interface can later separate strategy and script generation without introducing an agent framework.

Budget reservations are committed inside SQLite BEGIN IMMEDIATE before network calls. Concurrent processes share the same database/budget. Successful calls replace reservations with rate-based USD estimates (not invoice-verified actual charges); failed/ambiguous calls keep reservations. No automatic retries. Never clear reservations without reconciling provider billing. Budget is lifetime-per-database, not monthly. Do not delete/reset the DB to bypass limits. Upstream billing caps and verified model prices are necessary before paid activation. Models with extra tools or billing categories require a new cost model; only plain text completions are supported. Configured rates are owner-supplied and cannot guarantee provider pricing.

The workflow is synchronous for Phase 1. A process crash can leave a running job with its reservation intact. Recovery is manual; do not rerun an ambiguous paid request before reconciliation. A durable queue, idempotent submissions, cancellation and timeouts across workers belong to a later phase.

Backend is local-loopback by default. Production configuration requires a strong bearer token. Health is public and reveals no secrets. No CORS is enabled. Dashboard proxy uses a server-side token, checks same-origin requests, and rejects writes in production builds. This prevents an unauthenticated hosted visitor using owner credentials. Supabase Auth and owner authorization must be implemented before enabling hosted writes. RLS is enabled on every PostgreSQL table, with anon/authenticated grants explicitly revoked and no permissive policies.

Planned agent responsibilities: Capitalist orchestrates; Trend Hunter researches; Creative Genius plans; Content Factory produces; Influencer publishes; Algorithm Whisperer measures; Accountant reconciles; Auditor checks; Evolutionist improves. These are extension boundaries, not nine running agents.

No production hosting is selected for the Python service yet. Serverless ephemeral disks are unsuitable for this SQLite backend. Before cloud operation, implement a transactional PostgreSQL repository and durable workflow execution, then authenticate the dashboard. Vercel configuration prepares only the frontend.
