# Checkpoint 3A actual results — 14 October 2026

The complete handoff and existing architecture were read. The user's current authorization superseded the handoff's original Checkpoint 1 execution note: only **3A public URL auditing** was implemented. No business discovery, AI priority scoring or proposal generation was added. Approved theme tokens, brand SVG and shell geometry are unchanged.

## Final automated verification

| Command | Actual result |
|---|---|
| `cd backend` then `.venv/bin/python -m alembic upgrade head` | **0002_audits applied successfully**, preserving leads |
| `cd backend` then `.venv/bin/python -m pytest -q` | **101 passed**, one existing non-failing Starlette TestClient/httpx deprecation warning |
| `cd backend` then `.venv/bin/python -m alembic check` | **No new upgrade operations detected** |
| `cd backend` then `.venv/bin/python -m pip check` | **No broken requirements found** |
| `cd frontend` then `npm test` | **22 passed**, three test files |
| `cd frontend` then `npm run build` | **TypeScript and Vite passed** |

Build output: JS **316.48 kB / 98.39 kB gzip**, CSS **18.29 kB / 4.72 kB gzip**. Protego **0.7.0** was added and pinned; Certifi and HTTPcore were already in the pinned dependency graph. No new browser, cloud service or paid account was installed/configured.

Backend tests cover every prior lead/health/import behavior plus non-public/metadata/IPv6 translation addresses, mixed public/private DNS answers, literal-IP sockets with preserved TLS hostname and certificate checking, DNS rebinding, redirect restrictions/loops/destination robots checks, compression/body limits and explicit rejection of concatenated gzip rather than analyzing partial HTML, request timeouts, robots wildcard/delay/status/UTF-8 failures, static HTML evidence/recommendations, malformed canonical URLs, failed/wrong-form-factor/missing-metric PageSpeed results, key redaction in errors, quota cooldowns, persisted attempt budgets, cancellation, restart interruption, lead association/deletion behavior and migration preservation of existing notes/statuses.

Frontend tests retain navigation/themes and lead workflows and add permission confirmation, disabled provider state, request wiring, API evidence rendering, start errors, retry/cancel requests, exact mobile lab metric rendering and malformed-report rejection.

## Real public-site audit in Chrome

Headless installed Google Chrome was controlled with the previously installed temporary Playwright tooling. Tests ran on a separate frontend (5175), backend (10180) and SQLite file under `/private/tmp/clientscout-qa`. Default ports remain 5173/8000. No QA leads/reports were inserted in the user's workspace database.

Actual target: **https://example.com/**. The final real run returned:

- **HTTP 200**, HTTPS with verified certificate and hostname.
- **HTML title: Example Domain**.
- **577 downloaded document bytes**; document transfer measurement **83.79 ms** for this one run.
- Static HTML had no observed description or canonical tag, declared English and a responsive viewport, zero static H1 elements, zero image elements and one external script. Findings reflect that downloaded source, not assumptions about the JavaScript-rendered page.
- Robots request returned **404**, then the permitted page was fetched after the enforced request spacing. The recorded connection used a validated public literal IP while keeping the original hostname for TLS. Sources, timestamps, request status and DNS/socket evidence are persisted.
- Google PageSpeed's real keyless request returned **HTTP 429**. Result status is **partial**, with **no mobile score or metrics** and an explicit provider error. A one-hour provider cooldown was persisted because no Retry-After header was supplied. No substitute performance values were generated.

**Successful live Lighthouse measurements could not be verified because of Google's shared keyless quota response.** Numeric measurement/score parsing and rendering were verified with explicitly labeled automated fixtures; those fixture numbers are not stored as actual website measurements. A configured key with available quota is optional for later user review.

Initial real runs exposed an empty Python system CA store (zero CA certificates); they were retained as errors. A focused diagnostic showed that the pinned Certifi trust bundle returned the legitimate robots response while certificate/hostname verification stayed enabled. The final auditor uses that bundle. No TLS verification bypass was introduced. The browser-check completion polling was also corrected before the successful rerun.

## Actual browser behavior and regression checks

- Real report reload and rendering passed at **1440×900, 820×1180, 390×844 and 320×740**, in **both themes**: eight populated report/theme/viewport combinations with no horizontal document overflow. Desktop light/mobile dark screenshots were inspected and saved under `docs/screenshots/`.
- Permission confirmation, visible in-progress state and cancellation controls worked. Retry of the same real URL respected the persisted hostname cooldown. Unsafe loopback input was rejected with an explicit error, without a fictional report or outbound loopback request.
- A separate live audit of public **https://example.org/** was promptly cancelled in Chrome, without requesting PageSpeed. Backend status became **cancelled**, survived browser reload and removed the active cancellation control.
- Stopped the QA backend and started a fresh process using the same temporary database. Chrome compared **all audit report fields, status, timestamps and provider cooldown** to the earlier snapshot: identical. The actual Example Domain report and HTTP 429 message rendered after restart.
- Reran the complete existing Checkpoint 2 Chrome regression: **48 route/theme/viewport combinations**, actual lead creation, duplicates/invalid URLs, CSV partial outcomes, notes/status edits, reload persistence, database totals/status counts, collection filters, drawer focus/Escape, desktop collapse, connection error/retry and populated lead views passed.
- After real backend restart, lead fields/timestamps were identical. Delete cancellation/confirmation, real 21-record pagination and missing-detail recovery passed. Isolated QA lead fixtures were cleaned up. Actual audit reports remain in the temporary QA database as evidence.
- **No runtime page errors** occurred in the successful audit and regression scripts. No full screen-reader or other-browser certification is claimed.

## Reproduce safely

The audit scripts use a real public target and respect local/website/provider cooldowns. Never reset cooldowns to repeat network checks faster. Existing scripts require the installed macOS Chrome executable and temporary Playwright tooling.

From repository root, choose a **new temporary SQLite path** and migrate it:

```sh
CLIENTSCOUT_DB_PATH=/private/tmp/clientscout-qa/new-audit-run.db backend/.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
```

Start isolated QA servers in two terminals from repository root:

```sh
cd backend
CLIENTSCOUT_API_PORT=10180 CLIENTSCOUT_FRONTEND_PORT=5175 CLIENTSCOUT_DB_PATH=/private/tmp/clientscout-qa/new-audit-run.db PAGESPEED_ENABLED=true .venv/bin/python -m app.run
```

```sh
cd frontend
CLIENTSCOUT_API_PORT=10180 CLIENTSCOUT_FRONTEND_PORT=5175 npm run dev
```

Then from repository root:

```sh
CLIENTSCOUT_QA_PAGESPEED=1 NODE_PATH=/private/tmp/clientscout-qa/node_modules node docs/checkpoint-3a-browser-check.cjs
NODE_PATH=/private/tmp/clientscout-qa/node_modules node docs/checkpoint-3a-cancel-check.cjs
```

The first script requires a successful real HTTP/HTML observation and reports PageSpeed availability honestly. A restricted/network-unavailable public site causes an explicit verification failure, not a fixture fallback. The cancellation script must start after the global 10-second start interval. Stop/restart that same backend/database and run:

```sh
NODE_PATH=/private/tmp/clientscout-qa/node_modules node docs/checkpoint-3a-restart-check.cjs
```

The scripts save snapshots/screenshots under `/private/tmp/clientscout-qa`. They are checkpoint verification, not a full Checkpoint 5 E2E/security certification. Do not run prior fixture-cleanup scripts against a real lead database.

## Configuration, limits and final state

See [README](../README.md) for backend-only PageSpeed flags/key/budget, startup/migration commands and network/access limits. HTML auditing needs no provider key. URL import stays network-free; Website Audit is explicit. Google receives the final public URL only when requested. Reports do not imply terms permission, uptime history, actual mobile usability, ranking quality or sales conversion. Static JavaScript-dependent content may differ from what a browser renders.

Owned QA servers were stopped after verification. The pre-existing user frontend/backend processes were left in place. The workspace schema is migrated; QA data stayed in temporary files. No production deployment, publication, push, discovery source configuration, scoring or proposal generation occurred.

**Checkpoint 3A is complete and stopped for user review. Any further work requires separate approval.**
