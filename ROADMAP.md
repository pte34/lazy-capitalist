# Roadmap

## Phase 1
- [x] Repository, FastAPI, validated configuration, structured event logs, CI
- [x] Persistent deterministic mock content workflow, usage reservations, audit events
- [x] Supabase-compatible migration and disposable PostgreSQL verification
- [x] Responsive Next.js dashboard, explicit demo labels, local workflow form
- [x] Reproducible lockfiles, backend tests, lint/type/build validation
- [ ] Owner PR review and merge (never automatic)

## Later, separately authorized
- Supabase transactional runtime adapter, Auth and owner authorization
- Cloud scheduling and external status reconciliation (local steps/idempotency/manual billing reconciliation now implemented)
- Owner-approved model, verified pricing and provider billing caps
- Video provider/rendering adapters and quality checks
- Publishing with approval gates, analytics ingestion, actual revenue reconciliation
- Additional agents only when a simple workflow no longer suffices

The owner-authorized local video test MVP is implemented. Actual YouTube OAuth/upload, final script-based video production and production deployment remain open.

Private YouTube preparation: offline-tested resumable adapter library and encrypted OAuth/session storage now exist; real-upload runtime selection and project/quota verification and any authorized live private test remain open. See docs/STATUS.md and docs/YOUTUBE.md.

Local additions completed: owner-bound Desktop callback (mock HTTP only), script-dependent scene/text MP4 rendering and deterministic Zurich reports with mock notification history. Production hosting, real media/narration and authorized external verification remain open.

Command Center local scope completed: structured owner-reviewed plans, five distinct script videos, content constraints/reference provenance, CHF-only admission guard, manual/mock platform warnings, per-channel locks and extended reporting. Draft PR #1 and GitHub write access are now verified. Cloud operation, PostgreSQL runtime for these additive SQLite tables, hosted owner auth and any approved live publishing remain open.
