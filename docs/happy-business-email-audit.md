# HAPPY business-email discovery audit

Read-only investigation at Checkpoint 4. No crawler/extractor change, new website request, protected-email decoding, social-profile access, CAPTCHA interaction or outbound message was performed. Existing reports are observations from 14 October 2026, not a fresh claim about the current website.

## Confirmed evidence

The HAPPY identity points to `https://happyrestaurants.com/`. Its saved OSM snapshot has no `email` or `contact:email` tag. The public phone tag is separate, `public_unverified` evidence; it is not a verified email.

| Persisted enrichment | Official pages/requests | Email outcome |
| --- | --- | --- |
| #1, created 2026-10-14 12:33:30 UTC | robots.txt HTTP 200; no successful homepage/page record | `source_inaccessible`, empty value. The older report has no phase diagnostics. Prior bounded diagnostics traced an intermittent TCP connection timeout; this is not evidence of email absence. |
| #2, created 2026-10-14 13:10:42 UTC | robots.txt HTTP 200; homepage HTTP 200 at 13:10:45 UTC; `/about` HTTP 200 at 13:10:48 UTC | Identity `matched`, official confirmation true. Email is empty with `needs_review`, source `/about`, and `protected_email_source`. No error or failed-request record. |

Job #2 completed the selected queue. It did not exhaust the eight-request/three-page bound: it recorded three requests including robots and two pages. The production queue adds only recognized contact/about paths found on the homepage; it does not recursively discover links from `/about`.

The retained 36,009-byte homepage capture from the earlier bounded verification independently confirms the following. It is not proven byte-identical to job #2's response:

- 67 navigation links, below the parser's 100-link cap; no reserve overflow. The old footer-link cap issue is not the cause here.
- Two same-site `/cdn-cgi/l/email-protection` links in business header/footer context, two `data-cfemail` attributes and protected-placeholder link labels. No payload was decoded or included in this report.
- Zero ordinary `mailto:` links, zero visible plaintext email matches, zero recognized organization JSON-LD blocks/emails, zero forms.
- `/about` is the only contact/about candidate the current queue recognizes. Contact/email-labelled links point to the protection endpoint, not a distinct contact-page route.

Only the homepage raw HTML is retained in ignored temporary QA storage. Raw `/about` HTML is not available. The persisted production report proves a provider-obfuscated link was observed there; it cannot establish whether other visible text or a form existed on that page. The earlier offline homepage replay intentionally did not fetch linked pages; it is separate from the successful persisted enrichment #2.

## Supported root cause

For successful job #2, an email reference was observed but deliberately left undecoded. `ContactPage` recognizes the protection endpoint; `enrich()` records its source and a review-required marker. `extract_contacts()` extracts ordinary role/business `mailto:` links and verified-organization JSON-LD email fields, not Cloudflare payloads. Thus `needs_review` with no email value is intentional and accurate. It is not a failed robots check, CAPTCHA failure, request-budget exhaustion or proof of no public email.

No HTTP 401/403/429, `cf-mitigated` challenge, robots denial or transport failure is recorded for job #2. `PoliteFetcher.page()` checks robots rules before fetching each page. HTTP 200 for robots alone would not prove access permission, but the successful page records show the policy checks passed in that run. Email obfuscation is distinct from a bot-access challenge.

The underlying protected address and whether it is an appropriate business-role mailbox remain unknown. Do not infer its local part, decode it automatically, guess a mailbox, or label it verified from an obfuscation marker alone. `official_verified` in the current contact model means source/identity association, not mailbox deliverability or ownership validation.

## Coverage gaps, distinguished from actual absence

| Code behavior | Consequence | Evidence for HAPPY |
| --- | --- | --- |
| Email extraction scans `mailto:` and organization JSON-LD, not visible body/footer text | An explicitly printed business-role address without either encoding is missed | Synthetic offline replay reproduces the limitation. No such address is visible in the retained homepage; `/about` raw text is unavailable. |
| Only exact contact/contact-us/about/about-us path segments are queued; only homepage links seed the queue | Observed `contact.html`, localized variants or contact links found on `/about` could be missed | Only `/about` was selected. No evidence proves that an omitted HAPPY page contains email. |
| Forms are recorded as contact methods only on contact/contact-us paths | A relevant same-domain form on home/about would be ignored | Homepage has no form. `/about` cannot be checked from retained raw HTML; stored `not_found` does not prove no form exists. |
| Conservative role/name allowlist excludes named staff and unrecognized aliases | Some legitimate public business aliases may require manual review | Intended privacy protection. No evidence of a rejected plaintext HAPPY address. |
| Provider obfuscation is marked, never decoded | Requires human source review | Confirmed on the homepage and persisted `/about` marker. This is the principal demonstrated cause. |

Offline synthetic probes used reserved example addresses only. They confirmed ordinary role `mailto:` extraction, exclusion of named-staff mailboxes, no plaintext-only extraction, and form/path limitations. No private contact value or obfuscation payload was exposed.

## Minimal recommendations, not implemented

1. Keep the current `needs_review` email source link prominent. The user can review the official site manually and confirm whether an address is publicly displayed and appropriate for business outreach. Do not change protected data into a guessed or decoded `official_verified` email.
2. If approved, add a bounded scan of visibly published business-role email text in appropriate business contact contexts. Reuse the conservative role filter, exclude hidden/script/staff text, and retain exact official source/time and manual-verification status. Do not expand to arbitrary personal-address harvesting or infer addresses from names/domains.
3. Recognize explicit contact forms on permitted official home/about pages when their purpose is clear; record only the contact route/action and provenance. Do not submit forms or infer an email from an action endpoint.
4. Prioritize explicit observed contact links by label/path and permit bounded discovery from `/about` within the existing page/request caps. Never probe guessed URLs, ignore robots, broaden to protected social pages, or increase budgets silently.
5. Add per-page sanitized extraction counts (ordinary email links, visible role candidates, excluded personal candidates, protected markers, forms) and selection reasons. Do not retain raw HTML, decoded payloads or address values in diagnostic logs.

Any crawler changes should have separate offline regressions for observed vs inferred routes, robots/access denials, Cloudflare review-only handling, script/staff exclusion, form purpose/same-domain checks, provenance and budgets. No crawler changes were made in this task.

## File evidence

- `backend/app/intelligence/enrichment.py`: lines 28–43 (bounded fetch/access checks), 52–60 (identity and protected references), 67–77 (homepage-only queue), 86–91 (missing/review states).
- `backend/app/intelligence/contacts.py`: lines 23–29 (protected references/link caps), 59–64 (role filter), 86–103 (extraction channels/forms).
- `backend/app/auditing/robots.py`: `robots()` and `_page()` (policy before page access).
- Earlier transport evidence: [contact-enrichment diagnostics](contact-enrichment-diagnostics.md).

## Follow-up: user-observed footer addresses (15 October 2026)

The user reported seeing `info@happyrestaurant.com` and `booking@happyrestaurant.com` in the browser footer. These are observations supplied by the user, not verified extraction results. Neither was inserted into the application database or prefilled into the manual-entry form during this investigation.

A read-only replay of the retained 36,009-byte homepage found neither address literally or after HTML entity decoding. Neither appears in the parser's static visible text or an ordinary `mailto:` link. Both would pass the existing business-role filter, so that filter does not explain their absence. The capture contains two protection links, two `data-cfemail` markers on nested spans, and one reference to Cloudflare's `email-decode.min.js`. No protected payload or script was decoded, fetched or executed.

This establishes that the reported strings are absent from this retained server HTML. The protection markers and decoder reference support a browser-rendering explanation. It does **not** establish that these exact two strings are the contents of those protected payloads: no corresponding rendered DOM was retained. Nor can this capture prove the current live footer contents or every byte received by enrichment #2. The raw `/about` response remains unavailable.

The official candidate website is **happyrestaurants.com** (plural); the user-reported mailbox domain is **happyrestaurant.com** (singular). The singular domain is not literally associated in the retained unescaped homepage. Common branding and a role local part do not prove domain ownership, association or mailbox deliverability. No DNS, website, browser or provider request was made to resolve that uncertainty. Both addresses remain unverified.

### Offline comparison

`backend/tests/test_manual_contacts.py` uses reserved example addresses and a non-decodable protected-payload placeholder:

| Representation | Existing extractor result |
| --- | --- |
| Ordinary footer text, including entity-encoded `@` | Text is visible to the parser but no email contact is emitted: confirmed coverage gap |
| Ordinary or entity-encoded role `mailto:` | Extracted, subject to the existing role filter |
| Cloudflare protected anchor/span | Protection reference observed; no address emitted or payload decoded |
| JavaScript assignment containing an address | Script excluded; no JavaScript execution or address emitted |
| Synthetic post-render DOM with a role `mailto:` | Extracted if that DOM is supplied directly; production enrichment does not render it |

The synthetic DOM is a comparison fixture, not a claim about HAPPY's rendered DOM. No crawler behavior was changed.

### Explicit manual observations implemented

Lead Intelligence now has an initially empty manual-entry form. Submission requires acknowledgement of a personally observed public business-role address and attribution to a page on a previously matched official website. The server excludes personal staff aliases, link/header inputs, unrelated source hosts, source URLs containing credentials/query/fragments, and protection endpoint URLs. The source-page path is user-attributed, not freshly fetched or independently verified.

The existing `ContactMethod` storage records each explicit observation with `needs_review`, `manual_public_observation`, source URL, recorded time, and whether the email domain text matches the checked website domain. A different domain remains `different_domain_unverified`; even a matching domain does not verify the address. Exact repeated submissions reuse the observation. At most ten manual observations are supported per identity. Entries recover through the server's target-state response after reload and are displayed separately from automatic enrichment results. No migration, automatic source fetch, contact opening or sending was introduced.

Manual observations do not replace the empty protected-email marker, rewrite enrichment reports, affect assessment contact availability/scores, or enter the Gemini context. The UI exposes no promotion to verified status. Domain matching is explicitly a text comparison, not DNS/ownership verification. Fresh evidence or a separate human verification process would be needed before claiming association.

Changed implementation files: `backend/app/intelligence/manual_contacts.py`, `backend/app/api/intelligence.py`, `backend/app/schemas/intelligence.py`, `frontend/src/components/ManualBusinessEmail.tsx`, `frontend/src/components/LeadIntelligence.tsx`, and `frontend/src/services/intelligence.ts`. Offline regressions: `backend/tests/test_manual_contacts.py`, `frontend/src/components/ManualBusinessEmail.test.tsx`.

Verification: all 571 backend tests and all 67 frontend tests passed; frontend production build passed. Backend emitted the two existing dependency deprecation warnings (Starlette/httpx and Google SDK typing).
