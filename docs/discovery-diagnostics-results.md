# London search investigation and bounded-search fix — 14 October 2026

## What was verified, and what cannot be recovered

The existing SQLite job for the user-reported **restaurant / London, UK** search has status error, no result, and the message “Overpass reported an incomplete or failed query. Results were not presented as a successful search.” It started at **08:54:43.911858 UTC** and ended at **08:55:00.517824 UTC**, approximately **16.606 seconds**. The original `London, UK` place-cache entry is absent. This was the first persisted discovery job in the local database.

Inspected the exact implementation committed at `5ae5492e4a63d62b21001782845b47b55e65caf9`, configured default endpoint, saved job and cache, and backend logging destinations. The running backend stdout/stderr were attached to `/dev/ttys004`; no project log file was found. The old application did not log or persist the upstream response body, remark, status, request query or stage-specific diagnostics. Ordinary Uvicorn access logs do not supply that upstream evidence. **The literal server remark is lost; its specific timeout/memory/other cause cannot be verified retrospectively.** No historical diagnostic evidence was invented or backfilled into the database.

The unique old error branch proves an **HTTP 200 response containing JSON with a nonempty `remark`**: `request()` passed only status 200 to `parse_document()`, and this precise error message was emitted only on that remark branch. It was **not an observed HTTP 429**, and elapsed time alone does not prove throttling, timeout or memory exhaustion. Public Overpass distinguishes rate denial (429), resource admission (504) and runtime computation failures; see [operator documentation](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html). These are distinct classes, not interchangeable explanations.

Code-path reconstruction of the uncached location lookup identifies the failed stage before restaurant POIs. The old parser tried to parse the two comma-separated components as floats; when that failed, it treated the **whole string `London, UK` as the OSM place name**. It issued a global regex place lookup with 15-second computation and 8 MiB maxsize limits. The exact generated QL reconstructed from that source is:

```overpass
[out:json][timeout:15][maxsize:8388608];(node["place"~"^(city|town|village|hamlet|suburb|neighbourhood|country)$"]["name"~"^London,\\ UK$",i];node["place"~"^(city|town|village|hamlet|suburb|neighbourhood|country)$"]["name:en"~"^London,\\ UK$",i];);out 10;
```

This is a literal qualified-name lookup across the world, not a London lookup constrained to the UK. Output `out 10` caps returned elements, not the work required to evaluate that lookup. The application-level root causes are therefore **incorrect country-qualified location parsing/query planning** and **loss of actionable provider evidence**. The immediate provider failure was its JSON remark; the underlying server error text is unavailable. The reconstructed query is not claimed to have been captured in old logs. It was not replayed against public Overpass to chase an expensive failure.

Category mapping was already correct: restaurant and restaurants select [**amenity=restaurant**](https://wiki.openstreetmap.org/wiki/Tag:amenity%3Drestaurant). The failed location stage prevented that business query from being reached. Controlled regressions retain both mappings and cover additional plural category aliases.

## Changes

- Pure validation for `City, country`, common aliases such as UK → GB and valid ISO country codes, coordinates, and explicit `osm:relation/ID` boundary identifiers. Unknown qualifiers, extra address components and malformed IDs/options are rejected before network work.
- Exact-name/tag metadata queries with optional country-area scope replace the global literal-qualified-name regex. Original and title-case names and `name:en` are supported; this remains an exact-name resolver, not a general address geocoder.
- Country area must resolve exactly once. Multiple places/boundaries, capped metadata candidates or inconsistent same-name place/boundary positions stop **before any POI request**. No first-match choosing or invented coordinates.
- Search scope controls: auto, nearby and small administrative boundary. Nearby radius controls: **500 m, 1 km, 2 km**. Default remains auto/2 km.
- Administrative POI queries intersect the actual source area **and its bounding box**, permitted only at **≤16 km²**, **≤5 km per side**, with a conservative ≤1° longitude-span guard. Large explicit-boundary requests fail before POIs. Auto clearly labels a nearby sample when no permitted small boundary exists. No city-wide restaurant query, tiling, bulk city scan or increased memory/time budget.
- Missing provider-generated areas are explicit failures rather than apparently successful empty boundary results. Way/relation center coordinates remain unverified source bounding-box centers; source geometry can be stale or unavailable.
- `Prepare 500 m nearby fallback` changes controls only. It does not issue an automatic request, switch provider, guess a location or bypass cooldown. Review coordinates/name and start deliberately.
- Persisted request diagnostics: stage, generated QL/hash, actual HTTP status, response hash/bytes/time/timestamp and bounded redacted error excerpt/remark. Successful business response bodies are not copied wholesale. Unknown old evidence is explicitly unavailable. Terminal logs show only stage/status/classification/query hash/byte count, with no raw body, location or credentials.
- Actionable classes for reported timeout, memory, syntax, unknown JSON errors, HTTP 429, 503 and 504; no assumption that every failed/incomplete query is throttled. Partial results remain rejected.
- **0004_discovery_diagnostics** adds a nullable JSON column without rewriting old job contents. Original job/error remains intact. Lead/audit/source tables, manual URL/CSV CRUD, licence notices, SSRF/TLS/redirect/body protections, original theme tokens and shell are preserved. Old cache namespaces are not reused by the replacement resolver; original saved reports stay readable.

Country resolution uses capped metadata requests; city-name ambiguity is determined from that source metadata before requesting business data. No claim that ambiguity can be universally known without any metadata lookup. Exact casing/English naming, area-generation coverage and public-service availability remain limitations.

[Overpass area documentation](https://dev.overpass-api.de/overpass-doc/en/full_data/area.html) explains area filters, name ambiguity and area/bbox intersections. [QL reference](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL) documents exact tags, geometry/bounding-box output and relation-to-area conversion. This implementation does not assert complete city coverage merely because it uses administrative membership.

## Actual verification

All previous 202 cases remain; added **32 backend + 2 frontend** regression cases. Existing helper `progress` accepts optional diagnostics; original tests/assertions were not removed. Tests cover country-qualified query construction, early validation, category aliases, HTTP/body-based failure classification and redaction, database persistence of diagnostics, historic null diagnostics through upgrade/downgrade, ambiguity/no-POI guards, safe large-area refusal, labelled 500 m fallback, small area/bbox intersection, missing generated areas, malformed bounds and frontend evidence/control behavior.

| Actual verification | Result | Time reported |
|---|---|---|
| Targeted security | 184 backend passed | 0.53 s |
| Targeted leads/migrations | 35 backend + 7 frontend passed | 0.37 s pytest; 784 ms Vitest |
| Targeted discovery | 100 backend + 10 frontend passed | 0.21 s pytest; 670 ms Vitest |
| Final `make check` backend | **204 passed** | **0.76 s** |
| Final `make check` frontend | **32 passed** | **1.12 s** |
| TypeScript/Vite production build | Passed | 137 ms Vite build; TypeScript included in full command |
| `/usr/bin/time -p make check` | **236 cases + build passed** | **3.25 s wall time** |

One existing nonfatal Starlette/httpx TestClient deprecation warning remains. No new dependency was installed. `git diff --check` and browser helper syntax check passed. No historical browser matrices were rerun.

**Exactly one modest live provider request** was submitted: nearby coordinates **51.5074, -0.1278**, category **restaurants**, radius **500 m**, limit **2**, default `overpass-api.de`. It completed successfully with **HTTP 200**, **2 real restaurant records**, **11,112 response bytes**, **1,369.88 ms measured request elapsed time**, and no retry. The stored QL contains `(around:500,51.5074000,-0.1278000)` and `["amenity"="restaurant"]`; there was no administrative/city-wide POI request. No results or measurements were invented. Named country/boundary resolution was verified with deterministic source-shaped fixtures, **not live**; no second provider query was sent to claim broader verification.

Chrome against owned QA backend/frontend **10180/5175**, isolated `/private/tmp/clientscout-qa/discovery-diagnostics.db`, verified actual proxied health, radius/category controls, real source results, persisted query/status/timing evidence and desktop light/mobile **320 px dark** diagnostics without horizontal overflow. **Zero page errors**. The initial browser selector attempt submitted no search; its exact-label selector was corrected before the single live request. The modest-query helper requires explicit live opt-in. JSON and screenshots stay in temporary QA storage, not Git. Owned QA servers were stopped; the user's default servers were left running.

## Configuration, limits and Git

Run `alembic upgrade head` through **0004_discovery_diagnostics** before using the new backend. It was applied successfully to the existing local database and isolated QA database. No new API key/configuration or conflicting port defaults. Existing backend-only provider settings and one-worker localhost scope remain.

Preserved: one active discovery job, 30-second start spacing, 20 starts per rolling 24h, 24-hour cache, response size 8 MiB, network/DNS/compute and 100-second search deadline, bounded explicit Retry-After retry and persisted cooldowns. Errors do not automatically launch fallback jobs or silently change providers. OSM source/licence/attribution remains mandatory; no database, source snapshot, environment value, private note or credentials are committed.

Before commit/push: reviewed diff and staged secret/artifact checks, verified origin/main remained at **5ae5492e4a63d62b21001782845b47b55e65caf9**, and ran full completion checks. Final commit/hash/push verification is in Git and the completion response. Normal push only; no history rewrite.

Public Overpass is shared and can fail even on valid bounded requests. Its 200 remarks cannot all be interpreted from duration or status alone; the new retained evidence is essential. Whole London/country boundary searches remain deliberately unsupported on the shared service. Larger use needs an appropriately operated/licensed provider instance and a separate resource plan. This fix stays within Checkpoint 3B; Checkpoint 4 was not started.
