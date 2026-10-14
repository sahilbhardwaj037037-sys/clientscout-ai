# Architecture — Checkpoint 4

Browser → React/TypeScript on local Vite → same-origin `/api/...` → configured Vite proxy → local FastAPI → SQLAlchemy → SQLite.

## Connection configuration

`config/local.json` provides the sole default API/frontend port values. Root `.env` overrides them, process environment wins. Python `app/core/settings.py` and Vite config read the same root file and defaults. `app/run.py` starts Uvicorn on the configured API port; Vite uses it for proxying `/api` in dev and preview. Only the nonsecret effective loopback proxy URL is injected into the client for Settings. No API key or complete environment dictionary is serialized into frontend code.

The reported port 10180 was not present in inspected source, root/frontend/backend environment files or observed Vite source. The existing Vite process belonged to this checkout and pointed to 8000; the API was not listening there during diagnosis, yielding a proxied 502. This does not establish where the earlier 10180 message came from. Port-specific UI instructions have been replaced with configuration guidance. Both default and alternate-port configurations were subsequently checked in Chrome.

## Backend

- `api/leads.py`: list/detail/create/update/delete, CSV import and dashboard aggregation.
- `schemas/lead.py`: strict field/status/length validation and explicit UTC timestamps.
- `services/urls.py`: canonical stored URLs and deduplication keys; no DNS/network calls.
- `services/imports.py`: bounded UTF-8 CSV parsing, header validation and per-line errors, before writes.
- `models/lead.py`: business details, status, notes, unique normalized website key, original URL, source/filename and timestamps. Details remain user-supplied, not verified evidence.
- `database/session.py`: request-scoped sessions, foreign keys, busy timeout and explicit SQLite transactions/savepoints.
- `migrations`: an explicit Alembic revision creates the schema. App and CLI share the database path. No `create_all` schema bypass or implicit startup migration.

Accepted CSV rows commit in one transaction. Nested savepoints isolate unique-key conflicts; invalid rows are skipped explicitly. A file-level error saves nothing. Direct duplicate creates return 409 and existing ID; conflicting updates roll back all fields. Database errors return a bounded 503 message without disclosing SQL or local secrets. Lists paginate (limit ≤100) and filter; escaped search terms cannot act as SQL LIKE wildcards. All queries use SQLAlchemy bindings.

Health verifies migration revision and queries the lead table; database failure never yields an OK response. Dashboard total, per-status counts and recent leads are read in a database transaction. Priority totals count current qualified latest assessments scoring at least 70; draft totals count saved drafts.

## Frontend

Approved shell, brand and theme tokens remain intact. Find Leads adds native forms and CSV upload; Saved Leads adds collection filters/pagination and a detail/edit/delete route. Dashboard fetches persisted data. `services/api.ts` validates response shape, propagates backend validation/conflict errors, bounds request time and never invents success. `hooks/useResource.ts` cancels obsolete reads and exposes loading/errors/retry. Writes are disabled in flight. Settings shows the actual configured backend target.

No lead data is stored in localStorage; only theme preference is. Browser refresh/backend restart retain leads via SQLite. Empty database and unavailable database are separate UI states.

## Security and scope

- Loopback binding, explicit local Hosts and Origins; foreign browser write Origins rejected. Preview uses frontend port plus one. No wildcard CORS, authentication or public hosting support.
- API responses are no-store. React escapes notes, filenames and other user input. Website links use noopener/noreferrer; lead links do not trigger backend access; Website Audit is a separate explicit action.
- Imported files are ≤1 MiB/500 non-empty rows, validated UTF-8; only known data columns allowed. No formulas are executed or files retained. CSV export is not implemented.
- Keys/environment/database/caches/build artifacts are ignored; no API-key field exists in the frontend.
- Stored URL checks block dangerous schemes/credentials/local literals. Explicit audits use the public pinned transport and bounded redirect/body/time protections described below; imports remain network-free.
- No prohibited Google Maps scraping, automatic outreach sending, background schedules or deployment. Explicit source research and optional constrained AI assistance are described below.

SQLite persistence is intended for a single local user. Imports report per-row results immediately and preserve per-lead source metadata; an import run history table is not implemented. Database backups require stopping the backend first.


## Explicit public URL auditor

Checkpoint 3A adds `models/audit.py`, migration **0002_audits**, Pydantic audit schemas, `/api/audits` routes and the `auditing/` services. Audit reports are independent JSON snapshots of measured evidence. Optional lead foreign keys use SET NULL on deletion so historic observations survive lead removal. The existing lead schema and deduplication behavior are unchanged. Health verifies both tables and the new revision.

`network.py` uses HTTPcore's public custom AsyncNetworkBackend API and a TLS connection pool with the Certifi trust bundle. On each new connection, all DNS answers are checked, the selected literal IP is passed to the socket backend, and HTTPcore preserves original hostname SNI/Host. Keepalive reuse and connection retries are disabled. No environment proxy, cookies or arbitrary outgoing headers. Streaming limits check compressed and decoded data; unsupported encodings fail explicitly. Tests prove a public-first/private-second DNS set is blocked and that the socket literal differs from preserved TLS SNI.

`robots.py` implements bounded manual redirects, same-host spacing, fail-closed robots status handling and RFC-aware Protego permission matching. No page access precedes permission checking at its destination origin. Downgrades/unsafe URLs/loops are blocked. Robots and page response evidence is retained with status/time/validated addresses; full response bodies are not persisted.

`html.py` extracts static declarations and deterministic recommendations. Missing title/description/language/alt/viewport findings cite observed absence. Canonical/noindex/H1 observations recommend contextual review rather than asserting a ranking penalty. No arbitrary scripts, AI or local shell output is executed.

`pagespeed.py` calls a fixed Google HTTPS endpoint only after permitted HTML succeeds and the user requests it. A backend key is optional; the complete keyed request URL and provider error bodies are never stored/logged by application code. Returned requested URL, mobile form factor, runtime success and numeric metric units are validated. Actual Lighthouse values/estimated savings are retained with provider source/version/time/warnings. Missing or failed PSI is unavailable, leaving a partial HTML report without invented metrics.

`manager.py` owns at most two async tasks, persisted per-host/global cooldowns, rolling provider attempt budget, provider Retry-After cooldown and a 100-second total deadline. It creates a queued record before external work, closes database sessions before awaits, writes progress/final evidence, cancels local tasks and marks interrupted jobs on restart instead of restarting calls. Run one local Uvicorn worker. No scheduler or automatic provider retry exists.

The FastAPI lifespan owns task shutdown/recovery. Tests override both session dependency and lifespan engine so fixtures do not mutate the user's database. The frontend polls only the selected active run every 1.5 seconds, cancels obsolete reads, exposes explicit cancellation/manual retry/history pagination and rejects malformed data. Theme/brand/shell tokens are unchanged. Reports are plain escaped text; target HTML and provider descriptions are not injected into the DOM.

Endpoints: GET `/api/audits/config`; POST `/api/audits`; GET `/api/audits?lead_id=&limit=&offset=`; GET `/api/audits/{id}`; POST `/api/audits/{id}/cancel`. A POST needs a validated URL and `permission_confirmed=true`; `use_pagespeed` defaults false. Lead IDs must refer to matching-host leads. Rejected starts create no run; accepted failures/cancellations remain auditable. No capability silently treats unavailable data as success.

[HTTPcore backend reference](https://www.encode.io/httpcore/network-backends/) documents the custom socket interface; [Protego](https://github.com/scrapy/protego) documents robots matching. Remaining limitations and current check results are in `checkpoint-3a-results.md`.

## Attributed business discovery

`providers/base.py` defines the modular async provider protocol; `providers/overpass.py` implements escaped bounded OSM queries, exact-place/coordinate resolution, strict source parsing, evidence/attribution and cache use. `SafeFetcher.post` reuses the existing audit transport's DNS pinning, TLS, streaming limits and deadline. Provider redirects are refused. No Nominatim or frontend provider fetch exists.

`discovery/manager.py` owns one task, persisted 30-second/global Retry-After cooldowns, a rolling 20-start budget, 100-second deadline, 24-hour cache and explicit cancellation/recovery. It uses short database sessions outside network awaits. Lifespan shuts down both independent audit/discovery managers. Migration **0003_discovery** adds three source-layer tables without changing leads/audits. Health checks the current revision and all tables. The original lead totals/statuses remain unchanged; dashboard adds a separate saved-discovery count.

`api/discovery.py` exposes config/start/read/history/cancel/review-save/saved-list routes. Save uses only staged server-side records selected by validated source IDs from a completed run with an allowed licence; atomic unique-key savepoints preserve previously saved records. OSM records never enter the website-required private lead table automatically. Nullable source fields are retained.

`components/Discovery.tsx` extends the approved SearchCard, persists the selected run in the route query, polls active state only, aborts obsolete reads, and requires selection/licence acknowledgement. SavedLeads adds an independently paginated source collection. `services/discovery.ts` validates API payloads and safe source links before rendering. Attribution stays beside preview and saved records. Existing approved theme tokens, shell geometry and manual lead workflows remain. See [provider policy and licensing](discovery-provider.md) for the precise bounds and obligations.

## Discovery diagnostics and bounded administration

`providers/locations.py` validates country qualifiers/coordinates/relation IDs and builds exact-name country-scoped metadata queries. Multiple/capped candidates or spatial disagreement stop before POI calls. Small administrative areas use an area/bbox intersection; large boxes are refused in boundary-only mode and sampled as clearly labelled nearby searches in auto mode. `providers/diagnostics.py` records bounded hashes/status/time/query/error excerpts with distinct failure classes, and logs minimal metadata without source bodies or user queries. Successful response bodies are not duplicated as diagnostics.

Migration **0004_discovery_diagnostics** adds a nullable JSON column to existing search jobs; old jobs read as an empty diagnostic list, preserving unknown original errors. The progress callback optionally captures each completed/failed request's evidence before provider parsing, so failed JSON remarks survive. Cancellation/recovery/SQL sessions and previous provider budgets remain unchanged. Cache keys use a new namespace so the obsolete literal-qualified-place resolver is not reused; historic reports and licensed saved source data remain readable.

The existing search card adds scope and nearby-radius controls plus escaped expandable evidence, with a preparation-only 500 m fallback action. Native validation, backend guards and existing manual/CSV/audit flows remain. No large city query, automatic partial-results recovery, third-party geocoder or new discovery provider was added.


## Business intelligence and reviewed drafts

Migrations 0005/0006 add business identities tied to exactly one private lead or saved discovery record, enrichment jobs/contact observations, immutable evidence assessments, editable drafts and asynchronous AI usage. Foreign keys cascade business-linked intelligence; usage retains bounded request IDs/statuses rather than prompts. Lifespan owns all four managers and marks interrupted work without automatic provider resumption. Health expects 0006_ai_jobs.

`intelligence/contacts.py`, `identity.py` and `enrichment.py` extract only published business methods after bounded source permission and identity checks. Enrichment reuses SafeFetcher and same-domain PoliteFetcher, including robots checks, public pinned sockets/TLS, body/deadline limits and an eight-request budget. Same-domain contact/about pages inherit homepage identity only when no contradictory organization evidence exists. OSM tags remain attributed unverified observations; optional allowlisted Wikidata organization lookups retain CC0 provenance.

`scoring.py` stores deterministic evidence-v1 weighted components, confidence/coverage, source observations, identity, limitations and source-described segment. `freshness.py` checks the actual current business snapshot and latest source job before draft/AI dispatch and again before AI output persistence. Expired sources or business changes cannot extend qualification merely by refreshing the assessment timestamp. Dashboard priority excludes stale assessments. Historical assessments/drafts remain readable with their original evidence/time.

`providers/gemini.py` uses the official SDK at the fixed Google endpoint with explicit model, verified TLS, no environment proxies, no tools, one SDK attempt and a structured selection schema. Only public name/category plus approved observation/service IDs are sent. Allowlist validation prevents model-generated facts from entering drafts or changing scores. Application AIManager reserves every attempt, permits at most one 500/503 retry, enforces active/global/daily limits and a 429 cooldown, records actual token counts when available and sanitizes errors. It does not switch models or silently fall back to templates. Live operation remains unverified without credentials.

The `/api/intelligence` router exposes config, target lists/detail, enrichment start/read/cancel, assessments/filtering, AI jobs, usage and draft generation/read/edit. React intelligence and Proposal Studio screens preserve the existing shell/themes, render source provenance as escaped text, require permission/consent/review, validate API responses and poll only selected active jobs. Local templates and Gemini-assisted selections have distinct labels. No email/DM/form sender exists.
