# Owner-reviewed local commands

The supported deterministic example is `Erstelle 5 Videos über aktuelle KI-Trends. Maximal CHF 3 Budget.` Parsing is a bounded full-string pattern, not code evaluation or paid AI. Unsupported wording returns an editable plan with review_required=true and no production approval. Editing that flag is a deliberate owner review. The JSON plan exposes topic, count (1–10), language (de/en), portrait format, CHF cap (at most 3), source period, destination/channel, audience, tone, duration (10–60 seconds), included/excluded topics, inspiration links, notes, own text and rights note.

`/commands*` requires the existing 32+ character owner API_TOKEN. Creation requires Idempotency-Key. `/commands/{id}/plan`, `/approve` and `/run` are separate operations. Production approval binds the current plan. Editing resets production approval and per-video output/approval steps; attempted uploads or running steps block editing. Publishing approval remains separate; order execution stops before publishing even if a video was previously approved. Budget increases are rejected; reducing below committed reservations is rejected.

Commands bind to existing video_jobs, workflow_steps, ai_usage and LocalRenderer — no second video queue, renderer or agent framework. Repeated runs reuse video IDs, step claims, retries, pause and persisted results. Partial failures retain prior previews. Scripts/scene hypotheses are deterministic and explicitly synthetic; neither current trend research nor verified facts are asserted. Local CPU rendering is real. Five outputs are requested, not guaranteed when blocked or failed.

## Cost scope

The local/mock command runner has no paid-provider path and never consults configured OpenAI credentials. No incremental external API fee is incurred by these local steps; local compute/energy/environment costs are **unknown**, not zero. Therefore an all-in CHF 3 economic-cost guarantee cannot be certified. The cap forbids paid procurement; it does not fabricate hardware prices.

CHF reservations extend the same Store/BEGIN IMMEDIATE architecture used for USD AI reservations, with an order-linked integer-micro-CHF ledger. USD and CHF are never combined. Internal reservation preflight requires all five categories (research, script, media, voiceover, rendering), a verified source assertion and the complete bounded retry allowance before reservation. Unit tests use synthetic prices, never market quotes. The runner records only a zero incremental API-fee reservation. There is no paid execution route, provider pricing configuration or FX feed. Positive CHF daily/monthly limits default to zero; no limit is raised by the application. Existing USD settings remain independent. Estimated, reserved and recorded actual columns are distinct; ambiguity retains reservations.

## References and content

Links are stored only; no general URL fetcher, download or platform-video reuse exists. Reference URLs are inspiration, not licensing evidence. Retrieval time remains null because nothing was retrieved. Own text is bounded and handled literally as untrusted data in FFmpeg text files, never as shell/system instructions. Included/excluded topics affect deterministic scripts; conflicting exclusions block production. Audience and requested tone are retained; arbitrary stylistic AI rewriting is not implemented. Local backgrounds and DejaVu font provenance remain in docs/LOCAL_VIDEO.md. Arbitrary asset uploads/paths are intentionally unsupported; own text is the supported owner-content path. Rights notes are owner assertions, not independent legal verification.

## Platform scope

YouTube is the only prepared live adapter and remains disabled. TikTok/Instagram are future plan destinations, not connected publishing providers. Local previews may be created for a future destination; publishing attempts are rejected. No viral reach, platform payout or income is assumed.

Verification: `tests/smoke_command_center.py` creates the supported five-video command through the dashboard, edits a stored inspiration link, separately approves local production, verifies all five MP4s with ffprobe (540×960, 20 seconds and distinct hashes), checks upload steps remain pending, and exercises a synthetic warning/explicit review plus mobile layout. Outputs and representative frame are ignored under work/command-smoke/. All-in environment costs remain unknown. Budget day/month windows use UTC like the existing AI layer; reporting calendar windows remain Europe/Zurich.
