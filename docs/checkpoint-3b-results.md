# Checkpoint 3B + GitHub integration — 14 October 2026

## Scope delivered

Real, user-triggered OpenStreetMap business discovery through a modular server-side Overpass adapter. Find Leads retains the approved search card and adds configured provider selection, exact-place/coordinate location, category/name keyword, integer result limit (default 10, max 50), website-tag presence filter, actual job state/errors/cancel/retry, persisted recent searches, source review/selection, licence acknowledgement and selected-save results.

SQLite migration **0003_discovery** adds separate source staging/cache/saved tables; no change to the website-required private lead schema or existing audit schema. Businesses without usable website tags remain null. Saved Leads has a separate attributed source collection and optional explicit website-audit links. Existing URL/CSV import, lead CRUD/statuses/notes, audit evidence, themes, navigation, logo and responsive shell remain. Dashboard adds the actual source-collection count separately from private lead/status totals and refreshes after discovery saves on Overview.

Source IDs/URLs, nullable details, coordinates with their meaning, retrieval time, available source timestamp, unverified flag, attribution/licence and discarded-URL warnings are retained. Duplicate IDs/exact physical records are removed from processed search candidates; separate same-domain branches remain. Save uses staged source IDs only, verifies licence, commits selected records and preserves existing source snapshots.

No Checkpoint 4, AI scoring, proposals, freelance job discovery, scraping, outreach, export, cloud storage or deployment was implemented.

## Git integration

Initially the checkout had no Git repository/history/remotes. Authenticated remote inspection returned no refs: the supplied repository was empty. No unrelated history or conflicts existed. Configured **origin** as `https://github.com/sahilbhardwaj037037-sys/clientscout-ai.git`, created **main**, used the owner's public GitHub noreply identity, and authenticated with the existing macOS credential helper. No token/password was requested, placed in a URL, printed or committed.

Checkpoint 3A baseline committed and pushed separately: **3cfaf3d6601a7246aa988f9b150927f9174508d1**, `Complete ClientScout AI through Checkpoint 3A with tests`. Remote `refs/heads/main` was verified at that exact hash. Immediately before the final 3B commit, remote main still matched it. Final 3B hash/push verification are recorded in Git and the completion response. No force push, history rewrite, private database or user-data upload.

Before both commits: inspect ignored/tracked paths, scan staged blobs for high-confidence credentials/private keys and SQLite signatures, check placeholder environment files and whitespace. Dependencies, virtual environment, environment values, databases/WAL/SHM, generated builds/caches/logs, private import/export/backup directories and credential/key files are excluded. QA data/live provider records/screenshots remain under ignored or temporary storage, outside the committed source.

## Provider and terms

OpenStreetMap/Overpass was selected for legitimate mapped source data, stable source identifiers and no required API key or paid account. Its [public operator policy](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html) supports appropriate small manual queries but documents resource sharing/load shedding; availability is not guaranteed. [OSM licensing](https://www.openstreetmap.org/copyright) requires attribution and ODbL obligations, with [ODbL legal terms](https://opendatacommons.org/licenses/odbl/1-0/) governing derived database public use/distribution. The local app retains notices, shows attribution/licence links, requires acknowledgement before save and separates licensed source data from private lead notes. No claim that separation removes every obligation when distributing a combined database.

Provider configuration, query semantics, storage/licensing obligations, rate/backoff/cache policy, safe networking and restrictions are detailed in [discovery-provider.md](discovery-provider.md).

## Automated verification

All original **101 backend + 22 frontend** tests were retained. Added **71 backend + 8 frontend** cases, including parameterized validation/security inputs. No tests were removed, skipped or weakened to reduce count. Prior single-alert assumptions were corrected by routing test fixtures to their feature endpoints; dashboard error assertions remain intact.

| Actual run | Result | Reported time |
|---|---|---|
| Initial tested 3A baseline, before commit | 101 backend + 22 frontend; build passed | 2.86 s total wall time |
| Targeted lead development verification | 34 backend + 7 frontend passed | 0.39 s pytest; 831 ms Vitest |
| Targeted discovery development verification | 65 backend + 8 frontend passed at that stage | 0.16 s pytest; 620 ms Vitest |
| Targeted security verification | 152 backend passed at that stage | 0.51 s pytest |
| Final `make check` backend | **172 passed** | **0.75 s** pytest |
| Final `make check` frontend | **30 passed**, all four files | **1.12 s** Vitest |
| Final TypeScript/Vite production build | Passed | 143 ms Vite build (TypeScript included in full command) |
| Final `/usr/bin/time -p make check` | **202 total tests + build passed** | **3.32 s end-to-end wall time** |

Single-run timings vary and are not a performance guarantee. One existing nonfatal Starlette/httpx TestClient deprecation warning remains. No new dependencies were added. Targeted tests were used for development, then full completion checks; the full command was repeated only after a final dashboard freshness/unavailable-count correction invalidated the previous result.

New deterministic coverage: response parsing/partial-provider errors; literal query escaping; text/coordinates/provider/limit/filter validation; unsafe endpoint rejection; missing/unsafe websites and unverified source fields; same-source/exact-record dedup vs separate branches; invalid/out-of-area/tag-mismatched data; HTTP 429/503 bounded backoff/long Retry-After and redirect refusal; network timeout/body/DNS errors; cache retrieval/expiry; persisted cooldown/daily budget; active capacity/cancel/early cancel/shutdown/recovery; API access guards/pagination; forged selection/licence rejection; actual nullable source persistence and dashboard count; migration preservation of pre-existing lead notes/statuses and audit evidence after reopen. POST transport tests prove pinned socket/TLS SNI/Host, form encoding, no automatic redirects, DNS fail-closed, timeout and size protection. Frontend tests cover form submission, licence-gated selected IDs, saved records, source links/null details, cache evidence, disabled provider, malformed/empty/error results, explicit retry and API-confirmed cancellation.

## Actual Chrome/live verification

Used installed Google Chrome via Playwright against owned QA frontend **5175** and backend **10180**, both configured through the existing shared environment mechanism. Isolated database: `/private/tmp/clientscout-qa/checkpoint3b.db`; the user's database was not used for discovery QA. Sandbox denied localhost binding/Chrome launch; native tool approval allowed the QA servers/browser. A duplicate Location label initially required a more specific browser selector; neither failed browser startup attempt issued a provider request.

One small real provider query: coordinates **52.2053, 0.1218**, category **cafe**, limit **2**, default configured **overpass-api.de**. **Live discovery verified:** run 1 completed, returned **2 actual OSM records**, cache_hit false, no error. The provider candidate cap warning was accurately visible. No business records were invented or replaced with fixtures. One selected record was saved after user-facing ODbL acknowledgement, verified by the real saved API, and dashboard showed **1 saved discovery / 0 private website leads** in the isolated database.

Focused Chrome assertions passed: actual proxied migrated health/connection; live source rendering/review/licence gating/save; persisted run after reload; desktop **1440 light** and mobile **320 dark** without horizontal overflow; saved collection and actual database count; **0 page errors**. Reviewed the mobile dark screenshot. Then stopped/restarted the backend process and checked the persisted original two-record search, one saved source record and prefilled query in Chrome at **390 px**, without another provider query. Cancellation/error/empty/missing-website paths use deterministic frontend and backend tests; no second live search was issued to chase those paths. Historical browser matrices were not repeated. Owned QA servers were stopped after verification.

Reproducible helpers: `checkpoint-3b-browser-check.cjs` explicitly requires `CLIENTSCOUT_QA_LIVE_DISCOVERY=true`, Chrome/Playwright and an isolated fresh migrated QA database; `checkpoint-3b-restart-check.cjs` verifies the completed run after a real restart without external calls. Live JSON/screenshots are temporary QA evidence and are not committed business data.

## Configuration and remaining limitations

Apply `alembic upgrade head` before running the updated app; migration also successfully applied to the existing local database without altering existing lead/audit tables. No discovery API key needed. Optional root `.env`: **DISCOVERY_ENABLED** (default true, false disables new searches) and **OVERPASS_API_URL** (default public HTTPS interpreter). Backend-only endpoint is validated; secrets are not injected into the client. Shared API port defaults to 8000/frontend 5173; QA overrides do not change defaults or introduce a component port.

- Every search samples a **2 km radius**, including mapped country labels: no complete city/country directory. Exact place nodes/coordinates only; absent or ambiguous labels require coordinates, not guesses.
- Community coverage/business details/websites remain unverified. Missing website tag is not proof of no website. Way/relation positions are source bounding-box centers.
- Candidate cap/filter/dedup may yield fewer results than requested. No pagination across the external POI population. Public provider reliability/no SLA remains a limitation.
- One active job, 30-second start spacing, 20 accepted starts per rolling day, 24-hour cache, 8 MiB response caps and 100-second total deadline. At most one permitted short automatic backoff retry; no indefinite retries or silent alternate provider.
- Selected source snapshots are a separate read-only ODbL collection, not automatically editable private leads. Existing manual lead editing is unchanged. Public sharing/export of derived databases needs a deliberate ODbL/privacy review before a future feature enables it.
- One local backend worker/user only. Provider-received requests cannot be recalled on cancellation. Old search snapshots persist locally; no background scheduling/retention cleanup beyond expired cache.

Next: review Checkpoint 3B. Checkpoint 4 requires separate approval; no further work started.
