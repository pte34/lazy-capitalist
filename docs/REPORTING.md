# Local reports and mock notifications

The existing FastAPI process runs a lightweight tick at startup and every 60 seconds (`REPORTING_SCHEDULER_ENABLED=true`). It uses the configured Store and atomic transactions, not another workflow framework/service. When the process stops, scheduling stops. Restart catches up at most seven local calendar dates; older missed reports are not automatically created. Multiple processes/ticks share unique report and delivery keys. Manual `POST /reports/run` uses the same code. No cloud schedule or uptime is claimed.

Defaults: daily 20:00 Europe/Zurich, Sunday 20:00 weekly, last calendar date 20:00 monthly. Internally timestamps are UTC. Local calendar starts/ends use zoneinfo, including DST and year changes. Reports record schedule, actual execution data-as-of, cutoff and completeness. A report generated before calendar-period end is an interim snapshot, not an end-of-day/month result. Delayed catchup is capped at period end. Comparisons use the same number of elapsed seconds for both current and prior windows, capped to the shorter available period (explicit comparison cutoffs are stored).

Reports are immutable once generated for a scheduled kind/date. Aggregation is deterministic for a given database snapshot and clock. Current job status and reconciled ledger values are attributed to job creation time; historical as-of statuses and invoice arrival times cannot be reconstructed from the existing ledger. All reports explicitly carry partial-local-data completeness. Render/upload event counts use recorded audit times; local text rendering, historical simulated rendering, simulated private receipts and real private completions are separate. Unsupported public-publication, reach, availability and revenue metrics remain unknown. No fictitious agent activity is included.

Money is calculated with Decimal from stored values and serialized as USD decimal strings. Actual (owner-reconciled), reserved, estimated and mock categories are separate. Reservations are NOT actual spend. Token estimates retained under reservations do not become invoices. No currency conversion or revenue aggregation is invented. Revenue, profit and ROI remain null because sufficient actual data is absent.

## Endpoints and settings

All `/reports*` endpoints require the existing API bearer token, with a configured minimum length of 32 characters even in local mode. No strong token means 503; missing/wrong authorization means 401. The Next.js local proxy forwards its server-only BACKEND_API_TOKEN; hosted proxy operations remain disabled.

- GET `/reports`: persisted snapshots (latest 100).
- GET/POST `/reports/settings`: email, E.164 WhatsApp recipient, desired channels and immediate-alert flag. Responses mask recipients. POST replaces the settings; omitted recipient fields remove them. Recipients are never inferred from a Git profile.
- POST `/reports/run`: process due reports and eligible retries.
- POST `/reports/test`: explicit mock test for configured channels.
- GET `/reports/deliveries`: persistent mock history (latest 100), attempts, safe error and mock receipt.

`live_delivery` accepts only false; no SMTP, WhatsApp API, bot, subscription or AI summary provider is implemented. Both channels are desired by default but no recipient is configured. Missing recipients leave delivery records blocked_configuration, never sent. Settings and recipients reside in the configured protected database; protect that database as owner data. Logs and delivery history contain no recipient addresses or phone numbers. Real delivery cannot be enabled via configuration.

## Alerts and reliability

Actual HTTP 402 budget-block events and existing job/step failure events trigger immediate alert processing. The budget threshold is exhaustion/blocking, not a fabricated near-limit forecast. Categories are deduplicated by audit-event ID, limited to one queued alert per category/hour, and old backlog is bounded to seven days/100 events per tick. No event means no warning. Report/delivery failures intentionally create no job-failure events and therefore no recursive warning chain.

Reports due in one tick and eligible alerts are bundled into one mock notification per desired channel. Payloads retain report summaries and alert event references. Delivery jobs use atomic claims, three maximum attempts and persisted exponential backoff. Interrupted mock jobs can resume after 120 seconds with the same deterministic mock receipt. This recovery is safe only because the adapters have no external effects; it is not a guarantee for future live providers. Pause blocks new delivery claims. Each result explicitly says simulation=true and confirmed_real_delivery=false. 'simulated' is never 'delivered'.

Verification includes DST, calendar boundaries, equal comparison windows, missing finance, concurrent duplicate ticks, restart, cooldown, failing channels, bounded retries, strong authorization, rejected live configuration and UI mock test history. Run `tests/smoke_reporting.py` with the backend and local Next dev server configured with matching test-only API tokens. This does not send email/WhatsApp or contact Google.

Command Center extensions: snapshots now include orders/statuses/linked results and a separate micro-CHF ledger summary. USD AI values and CHF command values are never summed. Platform metrics separate owner-reported critical events, synthetic critical signals, upload errors and currently blocked channels. Existing local renders, simulated private receipts and real private completions stay separate; public publication/revenue/ROI remain unknown. Historical snapshots remain immutable; new fields appear in newly generated reports. Current channel locks and command statuses are explicitly current-state context, not reconstructed historical provider data.

PostgreSQL reports use a repeatable-read snapshot and resource-scoped generation lock, with bounded retries for known aborted database conflicts. Mock outbox completions are fenced against stale workers. Runtime setup and remaining cloud limits are in POSTGRES_RUNTIME.md and CLOUD_READINESS.md.
