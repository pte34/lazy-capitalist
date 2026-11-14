# Architecture

Next.js is the owner dashboard. FastAPI executes the content workflow. SQLite is a persistent, zero-service local store. PostgreSQL migrations prepare the future Supabase data model; SQLite is not a Supabase emulator and there is no live PostgreSQL runtime adapter yet.

Workflow: validated topic → provider → structured concept and script → Pydantic validation → persisted result/status → usage and audit events. The mock provider is deterministic. OpenAI produces concept and script in one structured-output request to minimize spend. The provider interface can later separate strategy and script generation without introducing an agent framework.

Budget reservations use SQLite BEGIN IMMEDIATE and UTC job timestamps for lifetime, job, day and month limits. Estimated paid calls retain at least the reserved charge until owner-supplied invoice reconciliation; estimates are separate. Ambiguous calls retain reservations and are not automatically retried. No provider invoice verification exists yet.

The synchronous workflow now persists quality/media/render/preview/approval/upload steps, attempts and backoff deadlines. Atomic step claims prevent duplicate workers. Interrupted steps require explicit reconciliation after 120 seconds. This is supported only for the current deterministic local rendering and simulated publishing. A real external adapter MUST implement status lookup and ambiguous-outcome handling before activation. Global pause prevents new claims, not already admitted work. There is no background scheduler: run/resume is invoked by the owner, so no permanent worker service is required.

Backend is local-loopback by default. Production configuration requires a strong bearer token. Health is public and reveals no secrets. No CORS is enabled. Dashboard proxy uses a server-side token, checks same-origin requests, and rejects writes in production builds. This prevents an unauthenticated hosted visitor using owner credentials. Supabase Auth and owner authorization must be implemented before enabling hosted writes. RLS is enabled on every PostgreSQL table, with anon/authenticated grants explicitly revoked and no permissive policies.

Planned agent responsibilities: Capitalist orchestrates; Trend Hunter researches; Creative Genius plans; Content Factory produces; Influencer publishes; Algorithm Whisperer measures; Accountant reconciles; Auditor checks; Evolutionist improves. These are extension boundaries, not nine running agents.

No production hosting is selected for the Python service yet. Serverless ephemeral disks are unsuitable for this SQLite backend. Before cloud operation, implement a transactional PostgreSQL repository and durable workflow execution, then authenticate the dashboard. Vercel configuration prepares only the frontend.

## Vendor decisions

Trigger.dev was evaluated against the existing persisted local runner: it would add hosted scheduling, durable waits and operational visibility, but also credentials, deployment and another state boundary. No production background workload exists yet. Keep the current single runner; reconsider replacing its scheduling when autonomous cloud operation is authorized. Do not add a parallel orchestrator. Reference: https://trigger.dev/docs and https://trigger.dev/pricing .

Creatomate fits the Renderer interface in principle: submit template/render request, retain external render ID, poll status, download and verify the MP4. A real adapter additionally needs timeout reconciliation, licensed media, output storage and per-render cost configuration. Current credit rates and credits per chosen template/resolution/duration are unverified; per-test-video cost is therefore **unknown**, not zero. Reject paid activation until owner confirms these values and a cost ceiling. Current alternative is free local FFmpeg with synthetic test media. References: https://creatomate.com/docs/api and https://creatomate.com/pricing . No vendor account or paid call was created. Langfuse remains deferred.

The disabled private YouTube library, encrypted state and artifact-bound approval are documented in docs/YOUTUBE.md. Runtime still selects simulated publishing; real callbacks and owner integration remain open.
