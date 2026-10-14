# Checkpoint 1 actual verification — 14 October 2026

## Automated checks

| Command | Actual result |
|---|---|
| `cd backend` then `.venv/bin/python -m pytest -q` | 3 passed; one Starlette warning about future httpx TestClient deprecation |
| `cd backend` then `.venv/bin/python -m pip check` | No broken requirements |
| `cd frontend` then `npm test` | 8 passed |
| `cd frontend` then `npm run build` | TypeScript and Vite passed; JS 283.68 kB / 90.34 kB gzip, CSS 14.34 kB / 3.93 kB gzip |
| npm dependency installation audit | 0 vulnerabilities reported at installation |

Frontend tests cover honest empty states, disabled search, health-fetch contract, all six navigation links, theme persistence/system reset, saved theme restoration, network error/retry, malformed-response rejection, loading and unknown-route recovery. Backend tests cover health JSON, allowed versus denied CORS origins and rejection of an untrusted Host.

The initial TypeScript build found unsupported `exact` options on Testing Library role queries. Those were corrected; the final tests and build pass. Browser QA exposed unwanted initial scroll caused by StrictMode focus effects; focus now changes only when the route changes and navigation scroll is explicit. The final browser checks passed after that fix.

## Real running application

Started Uvicorn at 127.0.0.1:8000 and Vite at 127.0.0.1:5173. Direct GET `/api/health` returned HTTP 200:

```json
{"status":"ok","service":"clientscout-api","version":"0.1.0","checkpoint":1}
```

Headless installed Google Chrome, driven by temporary Playwright tooling outside the repository, loaded all six routes at **1440×900**, **820×1180**, **390×844** and **320×740**, in both themes: **48 route/theme/viewport combinations passed**. Every route displayed backend connected from the real proxied fetch, restored the selected theme across reloads and had no horizontal document overflow.

Additional live checks passed: mobile drawer initial focus, forward/backward focus wrapping, Escape and focus return; navigation closes the drawer; desktop collapse/expand widths are 72px/248px; an intercepted network failure displays an error and Retry recovers with a real backend fetch. No browser page errors were recorded. Desktop light and mobile dark screenshots were inspected and saved in `docs/screenshots/`.

The one-off verification script is preserved as `docs/checkpoint-1-browser-check.cjs`. It assumes the macOS Chrome executable, two running local servers and the temporary tooling directory used for this run. To reproduce in this environment:

```sh
npm install --prefix /private/tmp/clientscout-qa --no-package-lock playwright
NODE_PATH=/private/tmp/clientscout-qa/node_modules node docs/checkpoint-1-browser-check.cjs
```

It writes screenshots to that temporary directory. This is checkpoint QA, not a full Checkpoint 5 E2E suite. Playwright was not added to the application's dependencies and no browser was downloaded.

## Limits and operational notes

- No full accessibility certification, screen-reader review or other-browser/device matrix was performed. Focus behavior and responsive dimensions were checked in Chrome.
- The Starlette TestClient/httpx deprecation warning does not fail the tests; the exact tested versions are pinned. Revisit the test transport on future upgrades.
- Sandbox DNS blocked dependency downloads and localhost port binding. Installation and live runtime/browser verification succeeded after native permission grants. On ordinary local terminals, use the README commands.
- Static `npm run preview` has no API proxy; use Vite dev plus FastAPI for connected review.
- Servers used for verification were stopped after checks; use the documented commands to launch for review.
- No database, provider, audits, scoring, AI, drafts, sending or CSV capability is enabled. API health does not imply any such feature is available.

Checkpoint 1 is ready for user review. **Checkpoint 2 has not been started and requires explicit approval.**
