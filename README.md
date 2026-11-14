# Lazy Capitalist

**Let AI work. Let money flow.**

Phase 1 foundation for owner-controlled short-form content automation. Working local mock generation; no production video provider, real publishing, revenue integrations, deployment or paid calls. Local script-dependent FFmpeg text videos are available.

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
4. Apply and review the implemented PostgreSQL runtime migrations, then implement hosted owner Auth before connecting production writes. Select managed backend/workflow hosting and approve its budget. Do not deploy the SQLite backend onto ephemeral serverless disks.
5. Only after separate approval: activate paid providers, confirm supported model schema and pricing, set provider billing limits, and reconcile usage.

No free-tier capacity or CHF 0 production operation is guaranteed. The current local mock system needs no paid credentials. Architecture and extension boundaries are in ARCHITECTURE.md; future scope is in ROADMAP.md.

Optional browser smoke test: with backend :8000, `npm run dev` on :3000 and `npm run start -- --hostname 127.0.0.1 --port 3001` (after build), run `uv run --with playwright python -m playwright install chromium`, then `uv run --with playwright python tests/smoke_dashboard.py` from the repository root. Use only the mock provider. This checks form submission, navigation, mobile overflow and production write protection; screenshots go to ignored `work/`.

## Local private-video MVP

Install FFmpeg (including libx264 and drawtext) before running the backend. No new hosting or subscriptions are needed. Existing databases gain additive SQLite tables automatically; existing scripts/jobs are retained. The original Supabase migration is unchanged and is **not** a runtime adapter for these local tables.

In the dashboard, generate a topic, open **Lokales Video-Teststudio**, refresh the queue, select a job, and run it. The workflow saves quality review → local media provenance → script-dependent multi-scene FFmpeg MP4 → preview. Inspect the preview and quality results, approve privately, then run again for a **simulated** private YouTube receipt. There is no actual YouTube upload or audio narration. This is genuine local text-video production, not a complete narrated AI video pipeline.

API (same bearer protection as existing jobs):
- `GET /jobs/{id}/workflow`, `POST /jobs/{id}/run`
- `GET /jobs/{id}/video`, `POST /jobs/{id}/approval` with `{"approved":true,"privacy":"private"}`
- `POST /jobs/{id}/reconcile` for interrupted local steps after 600 seconds
- `GET /system`, `POST /system/pause` with `{"paused":true}`
- `POST /jobs/{id}/cost-reconciliation` with owner-supplied `actual_usd` and `billing_reference`; this is manual invoice reconciliation, not provider verification.

Paid job creation requires `Idempotency-Key` (missing keys are rejected); reuse the same key on transport retries. Conflicting topics are rejected. The form reuses a key for repeated submissions of the same topic. Submission keys, per-step claims, outputs and attempts persist. Each step allows at most three attempts with 2/4/8-second persisted backoffs; call run again after the wait. Completed steps are skipped. A running step blocks retries until reconciliation; only deterministic local/mock steps can currently be recovered. Paid script failures keep their reservation and cannot be automatically retried. Never enable a real external adapter until status reconciliation is implemented for it. Pause blocks new admissions/step claims; actions admitted before pause can finish.

Paid AI requires positive JOB_BUDGET_USD, DAILY_BUDGET_USD, MONTHLY_BUDGET_USD and LIFETIME_BUDGET_USD, in addition to the existing configuration. All remain zero by default. Reservations and calendar-day/month sums use UTC and the same atomic SQLite write transaction. Successful paid calls retain at least their reservation until manual invoice reconciliation; token-based estimates are reported separately. Ambiguous failures retain their full reservation. Actual costs exceeding limits block further reservations; limits are never increased automatically. Local rendering and simulated uploads make no paid API calls. Provider billing and additional billing categories still require owner verification.

Quality checks currently flag repeated sentences and require owner review for unsupported claims and original value. They do not fact-check or guarantee platform-policy compliance. Model, prompt version, hook, script length, test format and cost records persist; `concept-v1` is the baseline identifier, with no automatic prompt/code changes. Performance and revenue remain unknown.

Browser verification for the studio: with backend :8000 and dashboard dev server :3000, run `uv run --with playwright python tests/smoke_private_mvp.py` after installing Chromium as described above.

The offline-tested real YouTube adapter library is now implemented but connected to a protected local Desktop OAuth callback, with live OAuth disabled and **no real-upload HTTP route**. Runtime publishing remains simulated. Setup variables, encrypted storage requirements, approval binding, reconciliation limits and official API references: [docs/YOUTUBE.md](docs/YOUTUBE.md). Current phase/cloud gaps and the handoff reporting convention: [docs/STATUS.md](docs/STATUS.md).

## Current local additions

Owner-bound Desktop OAuth callbacks are implemented but live OAuth stays disabled. See docs/YOUTUBE.md; never perform a Google login without separate approval. The local renderer now produces genuine script-dependent text scenes, without voiceover/external imagery: docs/LOCAL_VIDEO.md and examples/storyboard.json. Reports and mock notifications use the same local process and database: docs/REPORTING.md. Strong owner API_TOKEN and matching server-only BACKEND_API_TOKEN are required for reporting management. No provider messages, uploads or deployments are enabled by these additions.

## Command Center and platform signals

The local dashboard now plans the deterministic five-video/CHF-3 example, exposes an editable content plan, separates production from publishing approval, and renders five genuine local text videos. Trend data is explicitly synthetic; references are never automatically fetched. Unknown compute costs are not priced as zero and no all-in CHF-3 guarantee is asserted. All paid order execution is unavailable. See docs/COMMAND_CENTER.md. Manual owner platform reports and synthetic signals can lock one channel until explicit review; upload errors are not strikes. Only YouTube is prepared for future live integration; TikTok/Instagram have no publishers. See docs/PLATFORM_WARNINGS.md. Reports include commands and channel warnings while keeping CHF/USD and real/simulated outcomes separate.

## PostgreSQL runtime

Both SQLite and explicit PostgreSQL modes use the same services. Native private runtime schema, least-privilege backend role, resource locks, fenced claims and snapshot reports are locally tested. Run explicit migrations before startup; no automatic fallback or data import occurs. Setup/import/restore contract: docs/POSTGRES_RUNTIME.md. Targeted findings: docs/PERSISTENCE_REVIEW.md. Remaining hosted auth, pooling, file storage, workers and operational gates: docs/CLOUD_READINESS.md. Cloud deployment and live providers remain unverified and disabled.
