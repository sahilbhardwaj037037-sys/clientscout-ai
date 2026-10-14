# Checkpoint 2 actual verification — 14 October 2026

## Connection investigation and fix

- Inspected tracked source, root/frontend/backend environment-file locations and current process environment API settings. No 10180 reference or API override existed in that checkout. The existing Vite listener on 5173 belonged to this repository and served a source message referring to 8000.
- No API listener was present on 8000 at diagnosis. Direct health failed; Vite's proxied health returned **502**. The earlier 10180 message cannot be attributed conclusively from the available evidence.
- Removed the separately hardcoded port from the UI error. The browser API base is consistently **`/api`**. `config/local.json` supplies defaults to both Vite and Python; root `.env`, then process env, may override them. Settings shows the effective configured target. No frontend `VITE_API_BASE_URL` override is used.
- Actual Chrome direct and proxied health matched and returned **200**, version **0.2.0**, checkpoint **2**, database **ready**, on default **8000**.
- Repeated actual Chrome verification with backend **10180** and a separate frontend **5175**, setting the same `CLIENTSCOUT_API_PORT` for both processes. Settings displayed **http://127.0.0.1:10180**, and proxied/direct responses matched. These were temporary process overrides; shared default configuration remains **8000 / 5173**.

## Final automated results

| Command | Actual final result |
|---|---|
| `cd backend` then `.venv/bin/python -m alembic upgrade head` | Migration applied successfully to the workspace database; same migration used for separate QA databases |
| `cd backend` then `.venv/bin/python -m pytest -q` | **39 passed**, one existing Starlette TestClient/httpx deprecation warning |
| `cd backend` then `.venv/bin/python -m pip check` | **No broken requirements found** |
| `cd backend` then `.venv/bin/python -m alembic check` | **No new upgrade operations detected** |
| `cd frontend` then `npm test` | **15 passed**, two test files |
| `cd frontend` then `npm run build` | **TypeScript and Vite passed** |
| npm dependency audit during installation | **0 vulnerabilities reported** |

Final build: JS **299.49 kB / 94.39 kB gzip**; CSS **17.08 kB / 4.47 kB gzip**.

Backend coverage includes migrated health and unavailable schema, controlled CORS/Host and foreign-Origin write rejection, complete CRUD, statuses/notes, on-disk commits, normalized duplicate handling, update rollback, invalid/dangerous stored URL rejection, search/filters/pagination, CSV encoding/headers/limits/partial outcomes/duplicate preservation/source metadata, metrics and migration upgrade/downgrade/reopen. Every backend test uses temporary databases.

Frontend coverage retains rendering/routing/themes/loading/error/retry tests and adds real request construction for create/patch/CSV, duplicate recovery links, collection filters and rejection of malformed metric payloads. Network failure never displays a fake zero count as loaded data.

## Actual Chrome checks

Installed Google Chrome was run headlessly using temporary Playwright tooling outside the application dependency graph. Both port configurations were tested. Main workflow checks used an isolated SQLite file under `/private/tmp/clientscout-qa`; **no QA leads were inserted in backend/data/clientscout.db**.

- All six routes in both light/dark themes at **1440×900**, **820×1180**, **390×844**, **320×740**: **48 route/theme/viewport combinations passed**, with real connected health, persistent theme and no horizontal document overflow.
- Saved Leads and populated detail pages additionally passed overflow checks at desktop, 390px and 320px.
- Sidebar 248px/72px geometry and mobile drawer focus wrapping, Escape/focus return passed.
- Manual URL form saved a clearly labeled QA fixture via the live API. Duplicate recovery and invalid local URL errors displayed correctly.
- Notes/status edits survived browser reload. CSV with valid, duplicate and invalid rows returned and displayed **1 saved / 1 duplicate / 1 invalid**. Dashboard showed **2** real saved QA rows and actual shortlisted/contacted counts. Status filtering/reset passed.
- Interrupted health requests displayed a port-independent error. Retry recovered through the real backend.
- Stopped the backend, started a fresh process against the same temporary database, then compared **every lead field and timestamp** with the pre-restart snapshot: identical. This verifies process-restart persistence, not just cached UI data.
- Delete cancellation preserved the lead; explicit confirmation deleted it and returned to the updated collection. API GET afterward returned 404.
- With 21 isolated QA records, Next/Previous displayed **1–20 of 21** and **21–21 of 21**, with correct disabled states. Missing detail recovery passed.
- **Zero browser page errors** in the successful final workflow and restart checks. All isolated QA records were deleted after verification. Desktop/mobile overview and populated mobile screenshots were inspected and saved in `docs/screenshots/`. Populated screenshots contain explicitly labeled QA fixtures, not researched businesses.

Chrome exposed implicit label text including native option/textarea content; status, filter and notes controls now have stable accessible labels. All final checks were rerun after the fixes. Initial component test mocks also needed separate health/data response routing; the final suite has no uncaught errors. The approved visual tokens, SVG brand mark and shell geometry were preserved.

## Reproduce browser verification safely

The scripts are checkpoint QA, not a full Checkpoint 5 suite. They require macOS Chrome at the path in the scripts and temporary Playwright tooling; no browser download was needed.

From repository root, install the temporary tool:

```sh
npm install --prefix /private/tmp/clientscout-qa --no-package-lock playwright
```

Use a **new empty temporary database path**, never your workspace database, to apply migrations:

```sh
CLIENTSCOUT_DB_PATH=/private/tmp/clientscout-qa/new-run.db backend/.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
```

Start two QA terminals from repository root:

```sh
cd backend
CLIENTSCOUT_API_PORT=10180 CLIENTSCOUT_FRONTEND_PORT=5175 CLIENTSCOUT_DB_PATH=/private/tmp/clientscout-qa/new-run.db .venv/bin/python -m app.run
```

```sh
cd frontend
CLIENTSCOUT_API_PORT=10180 CLIENTSCOUT_FRONTEND_PORT=5175 npm run dev
```

From repository root:

```sh
CLIENTSCOUT_QA_FRONTEND=http://127.0.0.1:5175 CLIENTSCOUT_QA_API=http://127.0.0.1:10180 NODE_PATH=/private/tmp/clientscout-qa/node_modules node docs/checkpoint-2-browser-check.cjs
```

Stop/restart the same QA backend with the same temporary database, then:

```sh
CLIENTSCOUT_QA_FRONTEND=http://127.0.0.1:5175 NODE_PATH=/private/tmp/clientscout-qa/node_modules node docs/checkpoint-2-restart-check.cjs
```

The restart script verifies persistence then **deletes QA fixtures**. Never aim it at your real database. The scripts save snapshots/screenshots under `/private/tmp/clientscout-qa`. An earlier interrupted QA run may leave fixtures in its temporary file; use a new path for a fresh run.

## Limits and final server state

- No full screen-reader audit, other-browser matrix, public hosting validation or Checkpoint 5 certification was performed.
- One non-failing Starlette TestClient/httpx deprecation warning remains from the pinned existing test stack.
- Import outcomes are returned per run; a persisted import-history screen is not implemented. Each accepted lead retains source, original URL, filename and timestamps.
- URL import validates stored user input; it does not resolve/fetch websites. DNS/redirect SSRF defenses must precede Checkpoint 3 audits.
- High Priority and Drafts Ready remain unavailable; no opportunity scoring or draft tables are invented.
- Sandbox restrictions required native permission for downloads, localhost listeners/requests and headless Chrome. Those operations succeeded after approval.
- Owned default/QA backend processes and the separate QA frontend were stopped after testing. The pre-existing user Vite process was left intact. Start the backend with the README command for review; defaults remain port 8000. Default workspace database is migrated and contains no test leads.

**Checkpoint 2 is ready for review. Checkpoint 3 has not been started and requires explicit user approval.**
