# Test efficiency review — 14 October 2026

## Decision

**Keep all 123 automated tests: 101 pytest cases + 22 Vitest cases. No tests removed.** The count includes pytest parameterizations, not just test functions. Every existing security, URL validation, redirect, local access-control, API, database, migration and persistence test remains. There is no login/authentication system; CORS, Host and foreign-Origin protections are the applicable access-control coverage.

The full offline automated suite is inexpensive. The repeated cost came mainly from launching complete suites after small edits and rerunning historical browser matrices, rather than from a problematic slow test. Preserve short, isolated migrated databases per case; a shared mutable database would trade correctness for marginal savings.

## Apparent overlap that should stay

| Tests or groups | Distinct failure protected |
|---|---|
| Lead URL rejection vs `test_nonpublic_and_translation_addresses_are_blocked` | Pydantic/import input validation versus the socket address guard, including DNS-resolved addresses and IPv6 translation forms. Removing either loses a boundary. |
| `test_mixed_dns_answer_is_blocked_before_connection` vs `test_dns_lookup_has_all_answer_validation` | The network backend rejects a mixed answer even with an injected resolver; the DNS adapter separately rejects actual getaddrinfo-shaped mixed results. |
| Redirect target parameterizations vs private redirect/robots destination/loop tests | Target syntax/downgrade restrictions versus complete redirect execution, denied destination policy and bounded loops. |
| CRUD commit/new-session persistence vs migration upgrade/downgrade/reopen vs upgrade-preserves-leads | Committed application writes, schema lifecycle on disk, and preservation of existing business data during schema evolution. |
| Backend and frontend malformed response/error tests | Real API contracts/server guards versus browser-side validation and honest UI errors. |
| Backend manager cancellation vs frontend cancellation vs restart browser check | Worker termination, visible server-returned state, and persisted state after a real process restart. |
| Provider daily budget vs provider Retry-After vs website Retry-After | Separate account-usage and website-access constraints. None is interchangeable. |
| Similar 401/403/429/500/503 robots cases | Distinct auth/access/rate/server failure classes that all must remain fail-closed. Cheap parameterizations retain useful regression protection. |

No automated assertion group was demonstrably redundant enough to justify deletion. Superficially repeated checks that loaded/empty data is honest protect different failure paths (network failure, malformed payload, blocked/unmeasured provider data).

## Duplicated setup and a weak assertion

Three identical `anyio_backend` fixtures were consolidated into `backend/tests/conftest.py`; their asyncio value and per-test scope are unchanged. Only helper definitions were deduplicated; all tests and parameter cases remain.

The former frontend test named “sends cancellation and confirms persisted cancelled state” asserted only that a POST occurred and its GET mock remained running forever. It did **not** prove cancellation state, let alone SQLite persistence. Its replacement retains the request assertion, transitions the mock to the server-returned cancelled state, waits for the Cancelled progress text, verifies the cancel control disappears and confirms retry becomes available. The test name now accurately describes component-level coverage. Database and actual-browser persistence coverage remain separate and unchanged.

Do not merge the large CRUD test with other integrations: it covers a meaningful complete write/status/notes/metrics/delete lifecycle. Future failures may justify splitting for diagnostics, but count reduction is not a goal.

## Development commands

Run from repository root. Make targets are convenience selectors, not permission to skip checkpoint coverage.

| Change | Target | Additional considerations |
|---|---|---|
| Audit transport, robots, HTML or PageSpeed | `make test-audits` | Use `make test-security` when touching request validation, redirect policy, DNS/TLS or access controls. |
| Lead CRUD, CSV, status/notes, schema | `make test-leads` | Include audit manager tests for shared database/FK/schema changes; migration tests remain mandatory. |
| Routing, health display, themes or shell | `make test-shell` | For responsive/focus changes, add targeted Chrome checks at affected sizes/themes. |
| Shared API schemas, database plumbing or cross-feature code | `make test` | The suite is short; do not guess narrowly when dependency impact is uncertain. |
| Completed checkpoint | `make check` | Full pytest + full Vitest + TypeScript/production build. Add migration/dependency checks only when their inputs changed. |

For a single test, from `backend`:

```sh
.venv/bin/python -m pytest tests/test_audit_network.py::test_dns_rebinding_is_rechecked_for_new_connections
```

From `frontend`:

```sh
npm test -- src/Audits.test.tsx -t 'server-returned cancelled state'
npm run test:watch -- src/Audits.test.tsx
```

Use relevant tests after edits; run the full suite once when the checkpoint's final inputs are ready. Repeat only after further edits, a failure, or a newly identified concern invalidates the earlier result. Avoid habitual full-suite/build/browser loops between unchanged states. Do not use `--last-failed` alone as a completion check; it can omit affected passing tests.

## Browser selection and genuine repetition

The historical scripts are retained as review artifacts, not a sequence to run every time:

- `checkpoint-1-browser-check.cjs` substantially repeats the same 48 route/theme/viewport matrix, collapse, drawer and health checks in `checkpoint-2-browser-check.cjs`. Some specific focus assertions differ, so deleting it wholesale would lose assertions. Choose the later lead regression as the routine broad regression; keep the earlier script for those focused assertions when needed. Do **not** run both entire matrices by default.
- `checkpoint-2-browser-check.cjs` is the full lead/shell regression, not required after every unrelated audit parser edit. Its restart partner is required for changed lead persistence/deletion/pagination behavior.
- `checkpoint-3a-browser-check.cjs` covers **populated audit reports**; that is distinct from merely opening the empty audit route in the lead matrix. Run it for changed audit UI/network integration, once against an isolated database. PageSpeed is opt-in and consumes quota; do not repeat requests to chase a successful score after 429.
- `checkpoint-3a-cancel-check.cjs` uniquely guarantees actual cancellation regardless of whether the main script's retry branch hits cooldown. Keep it for cancellation/lifecycle changes.
- `checkpoint-3a-restart-check.cjs` checks actual persisted audit evidence/provider cooldown; keep it for lifecycle/schema/checkpoint integration changes. Reload assertions do not replace it.

For a CSS-only change, use a focused desktop/mobile check on the affected screen and both themes rather than repeated full navigation + live provider runs. Expand to the complete responsive matrix for shared shell/layout changes and relevant checkpoint review. Do not substitute mocked provider metrics for successful live measurements.

Browser scripts are **not** invoked by `make test` or `make check`, avoiding accidental network calls, quota usage and lengthy repetition. This review did not rerun browsers because no product UI/network code changed.

## Output and timings

Pytest defaults to quiet output and short failure traces in `backend/pytest.ini`; warnings remain visible. `--tb=long` restores full traces when diagnosing failures. Vitest uses the dot reporter and retains its pass/fail count, duration and error details. No warning/failure suppression or test exclusion was added. Detailed duration profiling is opt-in: `.venv/bin/python -m pytest --durations=5`.

Baseline on this machine (single measured run, not an average or performance guarantee): pytest **101 passed in 0.68 s**; Vitest **22 passed, 1.02 s duration**. The slowest reported pytest setup was **0.03 s**, with selected calls **0.02 s** or less. There is no evidence warranting xdist, database cloning, browser parallelization or weaker assertions for speed. Startup, scheduler load and tool overhead can exceed reported test-run time. Parallel subprocess timing is not equivalent to sequential end-to-end wall time.

See the final measured results below. Functional browser assertions and prior checkpoint results remain in their existing report files. No Checkpoint 3B/product work was started.

## Final measured verification

| Run | Result | Observed time |
|---|---|---|
| Focused cancellation test during development | 1 passed, 6 intentionally unselected in that file | 634 ms Vitest duration |
| Final full backend suite | **101 passed**, one existing deprecation warning | **0.52 s** pytest reported duration |
| Final full frontend suite | **22 passed**, all three files | **985 ms** Vitest duration |
| Full checkpoint command, `/usr/bin/time -p make check` | Full suites plus TypeScript/Vite build passed | **2.82 s end-to-end wall time** |

Timing differences from the baseline are normal single-run variation; no statistically established runner speedup is claimed. The optimization is targeted iteration, concise reports and avoiding redundant browser executions while preserving all 123 automated cases. `make -n` verified the feature/security selector commands without unnecessarily executing each group again. No browser, website audit or PageSpeed calls were made for this review.

Changed files: root `Makefile`, backend `pytest.ini` and shared test fixtures, the existing frontend cancellation test, frontend package test/watch scripts, README and this review. No application/server/network/database implementation or existing browser assertion was changed. No tests were deleted, permanently skipped, marked xfail or removed from discovery.
