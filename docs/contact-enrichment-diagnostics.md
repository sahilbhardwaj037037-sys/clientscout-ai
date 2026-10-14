# Happy Restaurants contact-enrichment investigation — 14 October 2026

## Root cause and limits of the evidence

The persisted original job fetched `https://happyrestaurants.com/robots.txt` with HTTP 200, then stopped with the old generic “Website request timed out” message. Its report had no homepage request or page evidence. A bounded reproduction with the unchanged client confirmed **TCP connection establishment timed out after five seconds, before TLS or HTTP request headers on the homepage connection**. The control `https://example.com/robots.txt` returned HTTP 404 normally. DNS resolved both public hosts outside the execution sandbox; the sandbox itself denied DNS for both, a separate environmental restriction.

The client previously selected only the first validated DNS address and opened a new connection for every request. In the single post-fix live verification, the homepage's first address **172.67.133.150** timed out after **2501 ms**; its second address **104.21.14.4** connected in **143 ms**, TLS verified in **173 ms**, response headers arrived in **309 ms**, and reading finished in **23 ms**. The request returned **HTTP 200**, **36,009 bytes**, in **3153 ms**. Both addresses were validated before either socket was attempted. The robots connection had succeeded on 172.67.133.150 in the same verification, so this is intermittent reachability, not proof that one address is permanently unusable.

The established cause is intermittent TCP reachability from this machine to a target CDN address, combined with first-address-only handling. The evidence does not locate the underlying fault at the ISP, network path or CDN. No HTTP challenge or explicit access denial was observed. Chrome can use different connection/address/protocol selection and existing connections; its success alone does not establish which of those mechanisms avoided the failed route.

## Network/configuration findings

| Area | Actual finding |
|---|---|
| DNS | Public A records for happyrestaurants.com: 172.67.133.150 and 104.21.14.4; answer order can vary. Both were checked, and every answer must remain public, including unused alternatives. No IPv6 answer appeared in these observations. |
| TLS | Successful robots and post-fix homepage TLS with verified certificates, original hostname SNI and Host. The reproduced old homepage failure occurred before TLS. |
| HTTP client | HTTPcore/AnyIO, HTTP/1.1, verified Certifi trust, no environment proxy/cookies/auth or automatic HTTP redirects/retries. No proxy variables or system proxy were present. |
| Headers | Existing honest `ClientScoutAudit/0.3` User-Agent; Accept for HTML/text/JSON; Accept-Encoding identity. The same headers succeeded after TCP fallback. No browser impersonation or header rotation. |
| Redirects | None observed. Existing six-hop, public-target, robots-at-destination, HTTPS-downgrade and enrichment-domain guards remain. |
| Timeouts | DNS ≤5 seconds; TCP socket attempts share ≤5 seconds after DNS, at most two addresses; TLS ≤5 seconds; read inactivity 8 seconds; write 5 seconds; pool 2 seconds; complete GET deadline 12 seconds. The enrichment's total 75-second/eight-request/three-page budget remains. No timeout was increased. |
| Robots | HTTP 200, 1248 bytes; policy allowed the homepage and spacing was observed. Robots errors/denials/challenges still stop access; permission is not inferred from a timeout. |
| Body limits | Homepage 36,009 bytes, below unchanged 2 MiB wire/decoded limits. Robots below 512 KiB. No compression, size limit or partial-body decoding failure caused this incident. |

## Email/contact findings

The downloaded homepage contains **67 parsed links**. Its footer email references are Cloudflare `/cdn-cgi/l/email-protection` links with `[email protected]` text and `data-cfemail` attributes, rather than literal `mailto:` addresses. The page references Cloudflare's browser decoding script. This explains the additional difference between static extraction and Chrome display. [Cloudflare's documentation](https://developers.cloudflare.com/waf/tools/scrape-shield/email-address-obfuscation/) describes this feature as anti-harvesting obfuscation that keeps emails visible to human visitors.

The implementation **does not decode those protection payloads, execute scripts or fetch reveal endpoints**. It records a source-linked empty email observation with `needs_review` and an explicit browser/manual-review explanation, instead of incorrectly presenting “not found.” The website's login/challenge/robots and other access protections remain respected.

Actual public homepage links extracted from the captured response:

- Facebook: `https://www.facebook.com/happyrestaurantlondon/`
- Instagram: `https://www.instagram.com/happyrestaurants/`
- LinkedIn: `https://www.linkedin.com/company/happy-restaurant-london`

These are source associations with `needs_review`, not independently verified profile ownership; none of the profiles was fetched. **No plaintext email, phone or WhatsApp value was extracted from this homepage.** The existing saved OSM business has a phone tag, but it is separate unverified source data and is not a homepage extraction result.

An offline replay used the already captured homepage through the actual parser/enrichment services. The saved source's name `HAPPY` matched the title under the existing identity rules with explicit official confirmation supplied for that replay. The placeholder diagnosis name “Happy Restaurants” did not match its singular, longer page title strongly enough; no identity rule was loosened to make it match. The replay retained the three social links and the manual-review email state. Fixture robots allowed offline replay only; real robots permission had already been verified live. Linked pages were intentionally stopped in the replay, giving a truthful partial result. No new network requests or user-database writes occurred during replay.

## Changes

- TCP fallback uses at most two distinct addresses from one fully validated DNS answer set, within the original socket deadline. The first attempt receives half of the remaining budget when an alternative exists. Prefer a different address family as the alternative when available. There is no second DNS resolution, alternate domain/provider, HTTP retry or retry after TLS/policy/HTTP failures. A cancelled request does not start another attempt.
- All existing public-IP/translation checks, DNS rebinding checks on new connections, pinned literal sockets, Host/SNI preservation, TLS verification, body/decompression limits, redirect checks, robots restrictions, request budgets and cooldowns remain. Keepalive stays disabled.
- Failures distinguish DNS, TCP connect, TLS handshake, response-header/body read, write, pool, total deadline, decoding/body size and policy categories. Diagnostic records contain bounded phase timings, public-address attempts, byte counts and limits. They omit raw exception strings, headers, credentials and query values. DNS timing is recorded separately; HTTPcore's `connect` timing includes the lookup and socket work.
- Failed requests remain separate from successful HTTP request evidence and have no invented HTTP status. Enrichment transport failures now use `error`, while genuine policy restrictions use `blocked`; partially successful runs preserve their observed contacts. Historical saved failures are not rewritten.
- The intelligence UI displays expandable failure-stage details and identifies empty review-required contacts accurately.
- Direct role/business `mailto:` and labelled telephone links can be captured after the first 100 navigation links, using a separate bounded 32-link reserve. Case-insensitive mailto schemes and percent-encoded addresses are handled. Personal staff addresses remain excluded; contacts are never guessed. This cap did not cause the Happy Restaurants incident, but its regression was reproduced and fixed.

## Actual verification

No broad crawler or historical browser matrix was run. Baseline diagnosis fetched one target robots.txt, attempted a homepage socket that failed before HTTP, and fetched one independent control robots.txt. **One post-fix live verification** fetched only target robots.txt and the permitted homepage. Total completed HTTP responses: three from the target (two robots, one homepage) and one control. TCP address fallback did not repeat an HTTP request. No linked contact/about page, site asset, social profile, challenge endpoint, PageSpeed or Gemini request was fetched.

Raw homepage HTML, network JSON and replay results remain under ignored temporary QA storage outside the repository. The user's database was read only to inspect the original failure and source identity, and was not changed.

| Check | Actual result |
|---|---|
| New regressions before implementation | 10 failed, 55 passed; confirmed missing fallback/phase evidence/footer retention |
| Focused network/audit/intelligence tests after fixes | 98 passed |
| Focused intelligence/audit frontend tests | 16 passed |
| Expanded affected backend tests including discovery transport | 201 passed |
| Final `make check` backend | **242 passed**, 1.38 s pytest |
| Final `make check` frontend | **41 passed**, 5 files, 1.27 s Vitest |
| Final TypeScript/Vite build | **Passed**, 135 ms Vite |
| Full `make check` wall time | **4.31 s**, exit 0 |

All prior tests remain. Added coverage proves bounded fallback/no extra resolution, private answers blocking every attempt, no fallback on cancellation, sanitized connect/TLS/header/body/write and DNS failures, retained policy/request diagnostics, late footer role emails/personal-email exclusion, protected email manual-review state, and UI diagnostic rendering. The full gate was repeated after correcting the total-deadline message to name DNS when the deadline expires inside DNS resolution. Whitespace review and an 11-file credential/database/binary scan passed. Two existing nonfatal dependency deprecation warnings remain (Starlette TestClient/httpx and Google SDK typing).

## Review status

The user approved this reliability fix for commit and an ordinary push to origin/main on 14 October 2026. The reviewed scope is the bounded transport fallback, sanitized error diagnostics, already-approved contact handling, associated tests and this investigation report. Pre-commit targeted checks again passed: 201 backend tests and 16 frontend tests. The previous full gate above remains valid; no application code changed during the approval review. The completion response records the actual commit and remote hash verification. No history rewrite, deployment or Checkpoint 5 work. Restart the backend if it is not using development reload; a new explicitly permitted source check is needed to replace the old persisted timeout record. Intermittent network reachability can still fail when both bounded candidates fail, and provider-obfuscated email values remain for manual review. No live Gemini verification was attempted or claimed.
