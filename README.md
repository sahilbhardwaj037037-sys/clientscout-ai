# ClientScout AI

Your Personal Freelance Intelligence Workspace.

**Checkpoint 3B ready for review.** The approved React shell, compass mark, navigation and cream/coffee themes are preserved. Leads now persist locally in SQLite: add website URLs, import CSV, edit details/statuses/notes, search/filter/page the collection and delete with confirmation. Dashboard totals, status counts and recent leads come from the database. High Priority and Drafts Ready remain unavailable until Checkpoint 4; no scores or drafts are fabricated.

## Install

Tested on macOS with Node **24.19.0**, npm **11.17.0**, Python **3.14.7**. Frontend versions and the dependency graph are pinned in `frontend/package.json` and `package-lock.json`; backend versions are pinned in `backend/requirements.txt`.

From the repository root:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
```

No API key is needed. Existing Checkpoint 1 installations should rerun the pip install and `npm ci` to install new dependencies.

## Configure once, run locally

Both launchers read **config/local.json**, optionally overridden by the repository-root **.env**, then process environment variables. Defaults are API port 8000 and frontend port 5173. API host is always loopback, `127.0.0.1`. The browser always requests same-origin `/api/...`; Vite proxies those requests to the configured backend. Settings displays the effective proxy target. No component contains a separate API port or API base URL.

To change a port, copy `.env.example` to root `.env` and set `CLIENTSCOUT_API_PORT` (and optionally `CLIENTSCOUT_FRONTEND_PORT`) to plain integers. **Restart both servers after changing configuration.** Leave values empty to use shared defaults. Do not configure separate terminal overrides with different values. `VITE_API_BASE_URL` and frontend-directory `.env` overrides are not used for the API connection. Use root `.env` for shared port settings; mode-specific files do not override these settings.

First apply migrations, from the repository root:

```sh
cd backend
.venv/bin/python -m alembic upgrade head
```

Terminal 1, from the repository root:

```sh
cd backend
.venv/bin/python -m app.run
```

Terminal 2, from the repository root:

```sh
cd frontend
npm run dev
```

Open **http://127.0.0.1:5173/** with default settings. Health: **http://127.0.0.1:8000/api/health**; API docs: **http://127.0.0.1:8000/docs**. Use your configured ports if changed. Ctrl+C stops either server. The backend launcher reloads during development. Avoid a separate `uvicorn --port` override: it bypasses the shared port setting and can recreate the reported mismatch.

`/api/health` checks API reachability and the migrated database. Missing migrations or a database failure produce an explicit 503. The header checks on opening, every 30 seconds and on request, with a five-second timeout. Connection errors avoid prescribing an independently hardcoded port.

`npm run build` type-checks and emits `frontend/dist`. `npm run preview` serves the built app on the frontend port plus one with the same API proxy; keep the backend running. Restart/rebuild if you change the configured target after building, so Settings matches the build. This is a local application, not a publicly hosted service.

## Use leads and imports

**Find Leads:** enter a public website URL; a missing scheme becomes HTTPS. Business name is optional and defaults to the hostname. Supply category/location/status/notes as needed. These are user-provided details; URL imports do not fetch websites; the separate Website Audit workflow collects timestamped observations.

**Saved Leads:** search name/website/category/location, filter status, browse 20 items per page, open a lead, edit and save. Statuses are **new, shortlisted, contacted, won, archived**. Editing a status records your choice; marking contacted does not send anything. Delete requires a separate confirmation. Source, original URL, CSV filename where applicable and timestamps appear in details.

Deduplication uses a database-enforced unique hostname key: lowercase IDNA hostname, removing a leading `www.` and ignoring scheme, standard port, paths, fragments and query strings. This deliberately treats pages on one hostname as one business; different subdomains remain distinct. Duplicates return the existing lead ID and never overwrite notes or source metadata. A conflicting URL edit rolls back the entire edit.

CSV format: comma-separated **UTF-8** (optional BOM), maximum **1 MiB / 500 non-empty rows**. Required column: `website_url`. Optional columns: `business_name,category,location,status,notes`. Unknown/duplicate headers and malformed files are rejected before any writes. Blank status means new. Quote fields containing commas/newlines. Business names default to hostname when omitted. Notes are limited to 10,000 characters.

Valid rows commit together; invalid rows and duplicate websites are skipped with explicit per-line results. CSV rows do not overwrite existing leads. Import success counts come from committed backend results. Uploads are not retained as files; per-lead source filename and original URL are stored. A request timeout may occur after a write; refresh before retrying to check the result. Deduplication protects against duplicate saves.

## Database and migrations

Default database: **backend/data/clientscout.db**, outside frontend assets and ignored by Git along with SQLite sidecar files. `CLIENTSCOUT_DB_PATH` may override this; relative paths resolve from the repository root, regardless of launch directory. Both Alembic and the app use that same setting. The app does not silently create a schema with `create_all`; run `alembic upgrade head` explicitly.

Stop the backend before copying the database for a consistent backup. Preserve your database during upgrades. `alembic downgrade base` drops the leads table and data; it is a destructive rollback, not a routine launch step.

## Tests

From the repository root:

```sh
cd backend
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python -m alembic check
```

From the repository root, in another terminal:

```sh
cd frontend
npm test
npm run build
```

Backend tests migrate separate temporary databases and never write test leads into your workspace database. Live Chrome checks likewise used temporary databases. See [latest actual results and reproducible browser checks](docs/checkpoint-3a-results.md).

## Versions, security and remaining scope

Frontend remains React 19.3.0, React Router 7.18.4, Vite 8.3.4, TypeScript 7.0.2, Tailwind 4.3.3 and Vitest 5.0.4. Added SQLAlchemy **2.1.4**, Alembic **1.20.0** and python-dotenv **1.2.4**; FastAPI **0.143.0** and Uvicorn **0.54.0** remain pinned. Migrations follow [Alembic's official workflow](https://alembic.sqlalchemy.org/en/latest/tutorial.html); SQLite sessions explicitly manage transactions and savepoints following [SQLAlchemy's SQLite guidance](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html).

[Architecture](docs/architecture.md), [design system](docs/design-system.md), [checkpoint checklist](docs/phase-1-checklist.md).

Both servers bind to localhost, with controlled local CORS/Hosts and rejection of writes with foreign browser Origins. Keys never belong in frontend code or logs; `.env` is ignored. URL checks reject non-HTTP schemes, credentials, private/local/reserved literal addresses and unusual ports. Website Audit makes limited public requests with pinned DNS, redirect revalidation, robots.txt checks and TLS verification; URL import alone makes no requests. No prohibited scraping, scoring, AI, outreach, CSV export, cloud sync, publishing or deployment is implemented.

**Stop for review here. Checkpoint 3B is implemented.** AI opportunity scoring, proposal generation and later checkpoints require separate approval.


## Website auditor — Checkpoint 3A

Open **Website Audit**, enter a public URL and confirm that you have permission and that the site's terms allow analysis. Saved lead details offer **Audit this website** and **View saved audits**. Each run persists separately; it never overwrites lead notes, status or business details. No lead score or proposal is generated.

The auditor checks public DNS and socket addresses, robots.txt, redirects, HTTP availability, HTTPS/TLS, static HTML title, meta description, canonical tags, H1 count, document language, viewport, images lacking alt attributes and robots/noindex directives. Findings include observed values, source URLs and timestamps, with recommendations for human review. Canonical URLs, images and scripts are not fetched. A viewport declaration is a mobile signal, not proof of mobile usability.

Run status/progress, history, retry, cancellation and errors are visible. Retry creates a new report and respects cooldowns. Cancellation stops local work and persists cancelled state; a request already delivered to Google cannot be recalled. Completed reports survive restarts. Interrupted runs are marked interrupted and are never automatically resumed. No simulated progress percentages, results, rankings or metrics exist.

### Optional Google PageSpeed configuration

The HTML audit works with no key. In root `.env`, set **PAGESPEED_ENABLED=true** to allow explicitly selected keyless measurements, or set a backend-only **PAGESPEED_API_KEY**. A key enables the option unless PAGESPEED_ENABLED=false. **PAGESPEED_DAILY_LIMIT** defaults to 10 attempted calls per rolling 24 hours; allowed values are 1 through 100. Restart the backend after changes. Use the checkbox for each new audit; ordinary HTML runs never call Google. No key is entered in the browser or returned by the config endpoint.

PageSpeed receives the permitted final URL, with mobile strategy. Only actual supported numeric Lighthouse lab metrics, Google performance score and Google's estimated savings are shown; missing metrics remain absent. Results are separate from static HTML evidence and this machine's document-transfer timing. No real-user CrUX metrics are claimed. Quota, runtime, invalid response, timeout and API errors leave the HTML report intact with a **partial** status and explicit missing mobile measurements. There are no automatic provider retries. Attempt counts and provider Retry-After cooldowns persist locally.

Google documents [keyless use and API-key configuration](https://developers.google.com/speed/docs/insights/v5/get-started) and the [mobile strategy/response fields](https://developers.google.com/speed/docs/insights/v5/reference/pagespeedapi/runpagespeed). Keyless shared quota can be exhausted; a key does not guarantee available quota. This app does not create a cloud project, enable paid services, configure billing or promise unlimited free calls. Review your provider account's current quotas/terms before enabling it. Selecting PageSpeed sends the public URL to Google; avoid URLs containing private query information.

### Network safety and access limits

- Public HTTP/HTTPS only, standard ports, no embedded credentials. Every DNS answer must be public; private, loopback, link-local, reserved/multicast, mapped/transition IPv6 and metadata addresses are blocked. The validated literal IP is used for the socket while original Host/TLS SNI remain intact, preventing a second hostname lookup. Environment proxies are not used.
- TLS verification uses the pinned Certifi CA bundle; certificate and hostname checking remain enabled. Certificate failures stop the request.
- At most five page redirects and five robots redirects; each target is revalidated. HTTPS downgrades, private redirects and loops stop. Each destination origin's robots policy is checked before its page is fetched.
- Robots wildcard/agent rules use Protego 0.7.0. Missing robots (404/410) allows this limited request; auth denial, 429/5xx, HTML challenges or lookup failure stop. Crawling delays/request-rate extensions are respected. Unsupported visit windows or delays over 10 seconds stop instead of bypassing the restriction. Terms cannot be established from robots alone; the user's permission confirmation is required.
- Two active runs maximum; at least 10 seconds between starts globally, 60 seconds per normalized hostname, and at least two seconds between website requests to a hostname. Server Retry-After can extend the cooldown. Start/budget restrictions survive restart. Use one backend process; multiple workers are not supported.
- DNS/connect timeouts: 5 seconds. Ordinary read timeout: 8 seconds; request total: 12 seconds. Document stage: 35 seconds. PageSpeed stage/read: up to 60 seconds. Entire run: 100 seconds. Limits include redirect chains and robots checks.
- Body limits: HTML 2 MiB, robots 512 KiB, PageSpeed 4 MiB, with both wire and decoded single-member gzip sizes checked. Concatenated gzip and other content encodings are explicitly unsupported. No login, cookies, challenge bypass, browser rendering, recursive crawl or unattended scheduling.

Reports retain bounded extracted signals and request evidence, not full HTML or screenshots of target websites. Static source may differ from JavaScript-rendered content. A single response is not an uptime history, full SEO/accessibility audit or sales prediction. Google performs its own external analysis and redirects; this backend does not control Google's browser. See [auditor architecture](docs/architecture.md) and [actual verification](docs/checkpoint-3a-results.md).

## Efficient development verification

From repository root, use `make test-discovery`, `make test-audits`, `make test-leads`, `make test-shell` or `make test-security` for the affected area. Use `make check` once at checkpoint completion for the full offline test suite and TypeScript/build checks. `npm run test:watch -- src/Audits.test.tsx` from frontend supports focused iteration. Failures and warnings remain visible with concise output.

The [test efficiency review](docs/testing-strategy.md) explains why all security/database/API/persistence tests were retained, the strengthened cancellation assertion, test selection and which historical browser runs overlap. Browser checks remain explicit; no live provider calls are made by the ordinary automated suite.

## Business discovery — Checkpoint 3B

Find Leads offers OpenStreetMap through Overpass, location/coordinates, business category/name keyword, 1–50 results (default 10), and optional website-tag filter. Each user-triggered search samples **within 2 km** of a mapped place center or coordinates; it is not a country/city directory. Ambiguous place names require coordinates. Coverage and business details are unverified. Missing website tags never become invented URLs.

Review returned records, select businesses and acknowledge ODbL before saving. Saved Leads displays a separate attributed source collection, including businesses without websites. Existing manual/CSV lead CRUD, statuses, notes and website-required schema remain intact. Dashboard shows the actual saved discovery count separately. Progress, cancellation, errors, manual retry and persisted history use real backend job state.

No API key is needed. Apply `alembic upgrade head` for **0003_discovery**. Optional backend-only `.env`: `DISCOVERY_ENABLED=false` disables new searches; `OVERPASS_API_URL` overrides the default public HTTPS endpoint. Shared public Overpass has no SLA. One active job, 30-second start spacing, 20 starts/24h, 24-hour cache, body/time caps, bounded backoff and pinned public-IP/TLS transport constrain requests. Restart the backend after configuration changes.

Read [provider selection, terms, ODbL obligations, configuration and limitations](docs/discovery-provider.md) before sharing source-derived data or changing providers. Source views retain attribution/license links. No database/export/private notes are committed to GitHub. See [Checkpoint 3B verification and Git integration](docs/checkpoint-3b-results.md).
