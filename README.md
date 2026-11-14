# Lazy Capitalist

**Let AI work. Let money flow.**

Phase 1 foundation for owner-controlled short-form content automation. Working local mock generation; no video rendering, publishing, revenue integrations, deployment or paid calls.

## Run locally

Prerequisites: Python 3.12, uv, Node.js 22+ and npm. Docker is only needed for PostgreSQL migration tests. Commands start at repository root unless stated otherwise.

```sh
cp .env.example backend/.env
cd backend
uv sync --locked
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. The five dashboard sections show explicitly labeled illustrative metrics. The content form calls the backend and displays a saved concept/script. Generated records persist in SQLite; the form shows submissions from this browser session, and `GET /jobs` returns up to 100 stored records. `BACKEND_URL` defaults to http://127.0.0.1:8000. Optional `BACKEND_API_TOKEN` in `frontend/.env.local` must match backend `API_TOKEN`. Never use `NEXT_PUBLIC_` for secrets.

```sh
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/jobs -H 'Content-Type: application/json' -d '{"topic":"Small experiments for better habits"}'
curl http://127.0.0.1:8000/jobs
curl http://127.0.0.1:8000/finance
```

Add an Authorization bearer header when API_TOKEN is set. OpenAPI docs: /docs. Jobs return validated concepts and scripts, persisted status and an identifier. Failures return a safe error plus job ID. /finance reports USD cost groups; revenue is null until actual data is integrated.

## Verify

```sh
cd backend
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
cd ../frontend
npm ci
npm run lint
npm run build
npm run typecheck
```

For database validation, use a disposable PostgreSQL 17 database. Create NOLOGIN roles anon and authenticated, apply `supabase/migrations/*.sql` with `psql -v ON_ERROR_STOP=1`, then run `tests/database.sql`. CI performs these steps using a PostgreSQL service; no Supabase subscription is required. Do not run destructive test setup against a real project. The SQL test transaction rolls back all sample data.

## Costs and security

Defaults: mock AI, USD 0 lifetime budget, no recurring infrastructure purchased. Paid mode needs explicit owner approval before setting ALLOW_PAID_AI, API key, model-specific verified token rates, a positive per-request reservation and lifetime budget. No live OpenAI request was used for validation. OpenAI compatibility is tested using stubbed HTTP responses; real model acceptance must be verified only after approval. Costs remain estimated, never presented as provider invoices. CHF demo revenue is not combined with USD usage. See ARCHITECTURE.md for budget limits, ambiguous failures and crash recovery.

Backend secrets stay server-side. Production backend requires API_TOKEN (32+ characters). Do not expose local mode publicly. Hosted dashboard writes are disabled until proper owner authentication exists. PostgreSQL denies browser roles by default; this migration does not grant access to all signed-in users.

## Managed deployment preparation — owner action required

1. Review and merge the PR after CI passes.
2. Frontend Vercel project: choose root directory `frontend`, use the committed lockfile, and configure environment values server-side. `frontend/vercel.json` selects Next.js. No deployment has been performed. Hosted previews remain read-only.
3. Supabase: owner selects an available plan, reviews costs, creates/links the project, and applies reviewed migrations. CLI: discover supported flags using `supabase --help`; never apply test role setup to hosted Supabase. RLS is enabled with no user policies. Verify advisors before production.
4. Implement the PostgreSQL runtime adapter and owner Auth before connecting production writes. Select managed backend/workflow hosting and approve its budget. Do not deploy the SQLite backend onto ephemeral serverless disks.
5. Only after separate approval: activate paid providers, confirm supported model schema and pricing, set provider billing limits, and reconcile usage.

No free-tier capacity or CHF 0 production operation is guaranteed. The current local mock system needs no paid credentials. Architecture and extension boundaries are in ARCHITECTURE.md; future scope is in ROADMAP.md.

Optional browser smoke test: with backend :8000, `npm run dev` on :3000 and `npm run start -- --hostname 127.0.0.1 --port 3001` (after build), run `uv run --with playwright python -m playwright install chromium`, then `uv run --with playwright python tests/smoke_dashboard.py` from the repository root. Use only the mock provider. This checks form submission, navigation, mobile overflow and production write protection; screenshots go to ignored `work/`.
