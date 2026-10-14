# Checkpoint 3B discovery provider and limitations

Provider policies and documentation reviewed on 14 October 2026. This is a deliberately small, user-triggered, single-user local MVP; no bulk country/city harvesting, scheduled discovery, Google Maps scraping, outreach or AI scoring.

## Choice and operating policy

OpenStreetMap through Overpass supplies genuine mapped businesses with stable node/way/relation IDs and source links without an API key or a paid account. Public Overpass is a shared free service, not an uptime guarantee. Its [operator's usage policy](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html) describes load shedding, resource budgets, appropriate manual queries and the need for an owned instance for heavier applications. Our application deliberately stays far below the documented resource guidance: one active search, 30 seconds between starts, at most 20 starts per rolling 24 hours, bounded responses and a 24-hour query/place cache. Restarting does not clear the start budget or cooldown. Counts include failed and cached accepted runs. Cancellation cannot recall a query already received by the provider.

The [Overpass QL documentation](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL) defines the tag/around queries and timeout/maxsize limits. Business output uses `out center`, whose way/relation coordinates are bounding-box centers rather than verified entrances: see [OSM object types and full data](https://dev.overpass-api.de/overpass-doc/en/full_data/osm_types.html). Responses with provider `remark` errors are rejected, even if they contain partial elements. No silent provider failover or fixture fallback exists.

Nominatim is **not used**. Its [public service policy](https://operations.osmfoundation.org/policies/nominatim/) restricts systematic POI queries/autocomplete and places additional responsibilities on generic geocoding integrations. Exact OSM place labels are instead resolved through one bounded Overpass place-node query. No commercial Maps API, CAPTCHA bypass or website scraping is part of discovery. Website audits remain separate permitted actions.

## Supported search and truthful limits

Location accepts an exact local/English OSM city, town, village, hamlet, suburb, neighbourhood or country-node label, or `latitude, longitude`. Ambiguous names require coordinates; absent labels produce an actionable error. Combined freeform addresses such as “Cambridge, UK” are not a general geocoder and may fail. A country label, if available, resolves only its mapped center. **Every search samples within 2 km of the center; it does not enumerate a whole city or country.** Use coordinates to choose an area deliberately. Returned way/relation centers outside the permitted radius/tolerance are skipped even if the object overlaps the radius.

Categories: cafe (also cafés/coffee), restaurant, bakery, hotel, dentist, pharmacy, salon, gym, shop, office and car repair; other text is a literal case-insensitive business-name keyword restricted to commercial tags. No regex/code interpolation is allowed. Limit defaults to 10 and must be an integer 1–50. Candidate output is bounded at 20–200 (four times the requested limit, minimum 20); presence filters/dedup can return fewer results even when more records exist. The candidate-cap warning communicates possible truncation. Duplicate/invalid counts describe processed candidates, not the whole geographic population.

All names, addresses, categories and website tags are **unverified community source data**. Missing names and addresses are null and visibly marked. No usable website tag does not prove that a business lacks a website. Unsafe/syntactically invalid website tags are discarded with a warning. Links do not cause backend fetches or automatically launch audits; any later audit still performs the complete DNS/SSRF/redirect/robots checks. No phone/email or invented domain is added. Distinct branches sharing a domain remain separate; duplicate source IDs and identical name/position/website records within a run are removed. Saving enforces a unique provider/source-ID key and preserves an existing saved snapshot.

## ODbL storage and attribution

[OpenStreetMap copyright/licensing](https://www.openstreetmap.org/copyright) permits reuse under ODbL with attribution and licence obligations. Review the [ODbL 1.0 legal terms](https://opendatacommons.org/licenses/odbl/1-0/), including sections 4.2–4.6 and private/internal-use provisions. Public use of derived databases and public distribution can require share-alike/database access; attribution on a screen alone does not satisfy every database obligation. This application is local, has no export/public publishing endpoint, and does not claim a legal exemption based on a small query size.

The adapter retains licence, attribution, retrieval time, source URL/ID and available source-data timestamp. Search snapshots/cache and selected records carry these notices. Results and saved-business views show “© OpenStreetMap contributors” linking to copyright and ODbL. Saving requires the user to acknowledge source licensing. Unknown licences cannot be saved. The backend accepts selected IDs from its persisted completed result, never client-supplied fabricated business fields.

Migration `0003_discovery` adds **discovery_searches**, **discovery_cache**, and **discovered_businesses**. The original website-required **leads** and **audits** schemas/data are unchanged. OSM data remains a separate source collection; private manual/CSV notes/statuses are not copied into it. This separation helps keep independent datasets identifiable; it is not a blanket exemption for sharing the entire SQLite database. Before any future database export/publication, determine the applicable ODbL notice/share-alike/access requirements, include the licensed source dataset as required, and separately protect private data. Do not publish the local database, search history or backups to GitHub. Saved source records are read-only in this MVP; editing, export and conversion into private lead records are deferred.

## Configuration and safety

No new dependencies or API credentials are required. Root `.env` may set `DISCOVERY_ENABLED=false` to disable new searches; saved snapshots remain readable. Empty/default is true. `OVERPASS_API_URL` defaults to `https://overpass-api.de/api/interpreter`. Override only to a provider you are authorized to use, after checking its policies. Endpoint must be public HTTPS with no user credentials, unusual port, query or fragment. Endpoint/API keys are never injected into frontend code. Changes require backend restart. The existing shared API/frontend port configuration and `/api` proxy remain unchanged.

All provider requests are backend-only form POSTs through the existing HTTPcore public-IP pinned transport: validate every DNS answer, connect to a literal IP, preserve TLS SNI/Host, verify certificates, reject internal/translated addresses, ignore environment proxies and never follow provider redirects. No arbitrary frontend endpoint is accepted. Native JSON/SQLAlchemy validation protects text and saved IDs; React escapes returned text. Existing local Host/CORS/foreign-Origin guards apply to discovery writes.

Timeouts: DNS/connect 5 seconds, provider read 30 seconds, individual request total 35 seconds, total search 100 seconds. Responses are capped at 8 MiB on wire and decoded; no unbounded downloading. Overpass requests specify their own 15/20-second computation limits and output caps. Provider 429/503 honours Retry-After and persists a global cooldown. Exactly one automatic retry is possible **only** when the provider explicitly supplies a short permitted delay (5–15 seconds); otherwise no automatic retry. Malformed Retry-After uses a conservative one-hour cooldown. No indefinitely repeated requests. Manual retry creates a new run and remains subject to all limits.

Progress describes actual stages, not percentages. Polling occurs only for the selected active search. Errors, cancellation and restart interruption persist; interrupted jobs never automatically restart. Cache labels show original retrieval time. Search history retains the latest 10 in the UI; backend history is paginated. Past snapshots persist until the local database is deliberately managed. Run one backend worker; this is not a multi-user/public service. For larger use, operate a permitted owned Overpass instance or evaluate another compliant licensed provider; public availability is not guaranteed.

## API

- GET `/api/discovery/config`: configured provider, truthful availability wording and limits.
- POST `/api/discovery/searches`: validated location/category/provider/limit/website_filter; returns 202 job.
- GET `/api/discovery/searches?limit=10&offset=0`: paginated history.
- GET `/api/discovery/searches/{id}` and POST `/api/discovery/searches/{id}/cancel`: status/results/cancellation.
- POST `/api/discovery/searches/{id}/save`: `source_ids` (1–50) and `licence_confirmed=true`; completed licensed server-side snapshots only; returns actual created/already-saved counts.
- GET `/api/discovery/saved?limit=20&offset=0`: separate attributed saved collection.
- GET `/api/dashboard`: existing lead metrics plus `discovered_businesses` count; private lead status totals continue to count the original leads only.
