# Checkpoint 5.1 — Durable Agent Foundation

Implemented on `feature/checkpoint-5` from stable base `ba50d79bcd5713d83368648fa01a47d4b4d20a73`. This phase connects only deterministic local plan checks. It does not connect business discovery, website access, Gemini, scheduling, notifications or outreach.

## Storage and immutable plans

Additive migration `0007_research_foundation` adds seven tables: `research_plans`, `research_jobs`, `research_steps`, `research_attempts`, `research_events`, `research_approvals`, and `research_worker_lease`. Its SQL is frozen in the migration. Existing tables, source records, drafts, freelancer profiles and configuration are not rewritten. Rollback drops only these new tables and their triggers; use rollback only on isolated test databases unless separately authorized to discard foundation records.

Plan revisions store category, a labelled coordinate/radius area (500/1000/2000 metres), requested lead count (1–50), explicit disabled external scopes, local attempt/runtime budgets, zero request/Gemini budgets and a timezone-aware expiry no more than seven days ahead. Place labels are not geocoded. A requested count is planning input, not a discovery result. Database triggers reject changes to plan revisions and job-to-plan bindings. Creating a revision creates a new paused job, links the prior revision, and rejects stale revision parents. It never edits the original job or its results.

Scopes in this phase are immutable denied capabilities, not standing access grants. The approval table stores reconciliation references for uncertain or unsupported actions; no endpoint can approve them or authorize a provider. Permission grants and provider-specific approval flows remain later work.

## Execution and recovery

Tasks are saved paused. Explicit **Run offline check** queues two ordered steps: `validate_plan` and `summarize_plan`. Their only output is a typed local result reference with the plan hash and zero external requests/businesses researched. No arbitrary command, provider name, URL, code or runner can be submitted through the API.

All required job states are persisted: queued, running, waiting_for_approval, waiting_for_budget, waiting_for_retry, paused, cancelling, cancelled, interrupted, failed, completed. Steps separately record pending, running, succeeded, cancelled, interrupted, failed or uncertain. Successful local checks do not imply successful business research.

A singleton SQLite lease allows one local worker. Short transactions obtain a write lock before reading mutable job/lease state, serializing claims, control requests and lease takeover across connections/processes. A unique owner and increasing epoch fence late results from previous owners; one running step is permitted globally. Heartbeats renew a 15-second lease. A live lease is never recovered by another worker. No database transaction is held while awaiting a runner, sleeping or polling.

Creating a task uses a client request UUID: retrying identical input returns the same job; conflicting input with that UUID returns 409. Steps have unique idempotency keys and attempts have unique step/attempt numbers. Completed steps are not replayed. Controls require the current job version; stale writes return 409 and the UI refreshes without claiming success.

Pause stops subsequent dispatches and lets the bounded current local step settle. Cancellation records intent durably, stops an active local check, and discards late output while retaining previously committed results and accounting. Graceful backend shutdown interrupts active checks and releases ownership. After an ungraceful stop, a new owner waits for lease expiry, reconciles unfinished attempts and requires explicit resume of interrupted local work. Already queued, never-dispatched local checks may proceed; there are no external dispatches to resume.

An interrupted step marked non-replay-safe, or reserved for a future external action, becomes uncertain and blocks on a persisted reconciliation reference. It cannot be resumed or approved in 5.1. Cancelling preserves its history and committed results. An unsupported action is blocked before invoking the runner. Exactly-once execution against future external providers is not claimed.

Each local attempt reserves up to one second of cumulative runtime before dispatch, with an asyncio deadline no greater than that reservation or remaining expiry. Reservations are conservative and are never refunded after a crash, failure, pause or resume. Attempt limits are also cumulative. Exhaustion enters waiting_for_budget; a new explicitly reviewed revision is required for fresh allowances. Failures permit at most one retry per step and respect a persisted two-second backoff even across pause/resume. Terminal failures, invalid output and timeouts use fixed sanitized codes; raw exception messages and rejected runner output are not persisted.

Persistence errors halt the research worker and cancel active local work. New creates/controls are rejected until database access/migrations are repaired and the backend is restarted. UI/API failures remain prominent. There is no fallback in-memory success queue or silent continuation. An uncertain or failed persistence operation is reconciled using the durable record after restart.

## APIs

All routes retain loopback Host/Origin controls and no-store responses. Research validation errors are sanitized rather than echoing rejected input.

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/api/research/status` | Offline-only capability and worker/persistence status |
| POST | `/api/research/jobs` | Idempotently save a paused plan; optional `based_on_job_id` creates a new revision |
| GET | `/api/research/jobs?limit=20&offset=0` | Paginated task history |
| GET | `/api/research/jobs/{id}` | Plan, status, version, progress, usage, steps, attempts and reconciliation references |
| POST | `/api/research/jobs/{id}/control` | `{action: pause|resume|cancel, version: current_version}` |
| GET | `/api/research/jobs/{id}/events?limit=50&after=0` | Cursor-paginated activity with fixed explanations and step/attempt references |

Events contain codes, timestamps and record IDs, not plan text, contacts, HTML, prompts, credentials or arbitrary exception text. Optional technical details show attempt state, timing, reserved runtime and sanitized error codes.

Health now reports version `0.5.1`, checkpoint 5, and requires migration head `0007_research_foundation`. The frontend health contract is updated accordingly. No startup migration is performed.

## UI

`/research` adds one sidebar destination using the existing compass brand, cream/coffee tokens and accessible shell. Operators edit a structured task, review the exact proposed plan, then save it paused. Editing form fields invalidates review. Create retries keep the same request ID while the reviewed payload is unchanged.

Task history and selected-job routes survive refresh. Current status, local progress, budgets, expiry, critical failures and action-required messages remain visible. Pause/resume/cancel use current versions. New revisions preserve historical records. Steps, hashes and attempts use expandable details; activity is paginated. Responses are validated before rendering and active states poll at 1.5-second intervals. No application data is put in localStorage.

## Safety and migration validation

The private Checkpoint 4 backup was verified before edits: manifest, coverage, hashes and restricted permissions. Before implementation, configuration/profile/database hashes matched the verified backup. Following explicit user authorization, the live database was subsequently migrated forward from 0006 to `0007_research_foundation`. Integrity, foreign keys, metadata, all historical record contents and private profile/configuration were verified. The final audit rechecked the live schema and historical data read-only. Startup never migrates automatically; the original database-file hash is expected to differ after adding schema and user-created foundation jobs.

Upgrade, Alembic metadata check, rollback to 0006 and re-upgrade were exercised on temporary databases, including a private copy of the verified data backup. All 12 historical table content hashes were preserved, including the existing five outreach drafts. No rollback/reset/restore ran against live data.

## Manual acceptance checklist — no external APIs

Use a new private temporary directory and set `CLIENTSCOUT_DB_PATH` to a new database there in every backend command. Use unused loopback ports and set `GEMINI_API_KEY=''`, `PAGESPEED_API_KEY=''`, `PAGESPEED_ENABLED=false`, and `DISCOVERY_ENABLED=false` in that QA process environment. Run `alembic upgrade head` only against that isolated database, then start the backend without reload and point a separate frontend at its API port. Do not change root `.env`, the original database path or profile.

1. Open Research and confirm the foundation-only explanation. There must be no Start Research, provider, scheduling, notification or outreach action.
2. Review a bounded task. Confirm the coordinates, requested count, expiry, limits and denied external scopes; save it and verify it is paused.
3. Reload. The task and activity remain. Run offline checks and verify two successful local steps, zero businesses researched and zero external requests.
4. Save another paused task, cancel it and reload. Verify cancellation/history and no attempt dispatch. Save a revision and confirm the original plan/result remains unchanged.
5. Set zero allowed attempts, save and run. Verify waiting_for_budget is prominent; resume cannot manufacture a new budget. Review and create a new revision if desired.
6. Use two tabs and stale control versions. Verify a rejected stale action never displays success, and refresh recovers the actual state.
7. Check activity, expanded technical details and long hashes at desktop and 320-pixel widths in light/dark mode. Verify keyboard access, drawer Escape/focus return and no horizontal overflow.
8. Stop/restart the isolated backend and reload. Completed data stays intact. Deterministic tests inject blocked runners and crashes to verify active interruption, lease recovery, cancellation and stale-owner rejection; production checks are deliberately too fast to rely on manually clicking during a running step.
9. Simulate unavailable persistence only in an isolated fixture. Verify errors are visible, no checks start, and recovery requires repairing access and restarting. Do not alter real file permissions or remove live database files for this test.
10. Stop the owned QA servers after review. Preserve the real data and private backup.

## Verification results and limitations

Final audit checks: **604 backend tests passed** (5.61 seconds; two existing dependency deprecation warnings), **77 frontend tests passed** across eight files (3.23 seconds), TypeScript/Vite production build passed (133 ms Vite), and `git diff --check` passed. Secret scans covered tracked and non-ignored untracked source; no configured secret values or recognizable credential patterns were found. Untracked-file whitespace checks also passed. No files were staged, committed or pushed. Earlier implementation browser QA used a new temporary database with discovery and paid providers disabled. It verified review/save paused, reload, both local steps, zero external research, stale-version rejection, immutable revision creation, budget warnings, activity/details, 1440-pixel light and 320-pixel dark layouts, keyboard drawer behavior and zero page errors. Screenshots and QA data remain outside Git.

This phase is deliberately not a business research agent yet. It has no permission-granting workflow, provider dispatch/reconciliation, geocoding, notification delivery, scheduling or result ranking. Use one backend worker; the lease prevents duplicate research execution but does not retrofit multi-worker support into the existing Checkpoints 1–4 managers. Existing manual discovery/audit/writer features retain their original explicit controls and have not been invoked live during this work. The private backup is local, permission-restricted and unencrypted; it remains outside Git.

## Manual acceptance and final audit

The user confirmed task #1 survived refresh and completed both offline checks, task #2 was cancelled with zero attempts/requests, and task #3 displayed waiting_for_budget at 0/0 attempts. All three states survived a backend restart; reported external request counters were zero. The audit independently read these states from SQLite.

This proves restart persistence of those saved states. It does **not** prove recovery from a real process crash during an active attempt or manual pause timing. Lease takeover, active interruption, pause/resume and ambiguous dispatch are covered by deterministic tests with temporary databases and injected runners/clocks. No live SIGKILL, power-loss test or in-flight provider request was performed. The final audit corrected cancellation/shutdown precedence with two regressions; restart the backend to load that fix before any later testing.

See the [final pre-commit audit](checkpoint-5-1-final-audit.md) for severity, verification evidence, limitations and the exact changed-file inventory.

## Changed files

23 files: 11 modified and 12 new.

- `README.md`
- `backend/app/api/research.py`
- `backend/app/main.py`
- `backend/app/models/research.py`
- `backend/app/research/manager.py`
- `backend/app/schemas/research.py`
- `backend/migrations/env.py`
- `backend/migrations/versions/0007_research_foundation.py`
- `backend/tests/test_health.py`
- `backend/tests/test_migrations.py`
- `backend/tests/test_research.py`
- `backend/tests/test_research_migrations.py`
- `docs/architecture.md`
- `docs/checkpoint-5-1-final-audit.md`
- `docs/checkpoint-5-1-foundation.md`
- `frontend/src/App.test.tsx`
- `frontend/src/App.tsx`
- `frontend/src/Research.test.tsx`
- `frontend/src/pages/Research.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/services/health.ts`
- `frontend/src/services/research.ts`
- `frontend/src/styles.css`
