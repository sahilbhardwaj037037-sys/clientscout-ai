import asyncio
import time
from urllib.parse import urlsplit
from app.auditing.html import analyze_html
from app.auditing.network import AuditFailure, SafeFetcher
from app.auditing.pagespeed import measure_pagespeed
from app.auditing.robots import PoliteFetcher

LIMITATIONS = ['Static HTML only: no JavaScript execution, screenshots, full-site crawl or login.',
               'Availability and transfer timing are observations from this machine at one point in time.',
               'Transfer time is not browser load time, Lighthouse performance or Core Web Vitals.',
               'HTML declarations do not establish search rankings or actual mobile usability.',
               'Extracted strings and lists are bounded; very long evidence may be shown as an excerpt.']


async def run_audit(url, use_pagespeed, progress, reserve_pagespeed, key='', fetcher_factory=SafeFetcher):
    started = time.perf_counter()
    report = {'requested_url': url, 'findings': [], 'requests': [], 'redirects': [], 'limitations': LIMITATIONS.copy(),
              'pagespeed': {'status': 'not_requested', 'message': 'Mobile lab measurement was not requested.'}}
    async with fetcher_factory() as fetcher:
        polite = PoliteFetcher(fetcher)
        try:
            await progress('Checking robots.txt and fetching permitted HTML')
            async with asyncio.timeout(35):
                response = await polite.page(url)
            report.update({'final_url': response.url, 'http_status': response.status, 'fetched_at': response.fetched_at,
                           'available': 200 <= response.status < 300, 'https': urlsplit(response.url).scheme == 'https',
                           'tls_verified': urlsplit(response.url).scheme == 'https', 'content_type': response.headers.get('content-type', ''),
                           'html_transfer_ms': response.elapsed_ms, 'body_bytes': len(response.body)})
            def observation(code, level, title, evidence, recommendation):
                report['findings'].append({'code': code, 'level': level, 'title': title, 'evidence': evidence,
                                           'source_url': response.url, 'recommendation': recommendation, 'observed_at': response.fetched_at})
            observation('availability', 'observed' if report['available'] else 'attention', 'HTTP availability observed', f'HTTP {response.status}',
                        'Confirm the expected page is returned. A single response is not an uptime history.')
            observation('https', 'observed' if report['https'] else 'attention', 'HTTPS connection observed' if report['https'] else 'Page returned over HTTP',
                        'TLS certificate/hostname verified by the client.' if report['https'] else 'Final response used unencrypted HTTP.',
                        'Keep HTTPS enabled.' if report['https'] else 'Configure HTTPS and redirect HTTP traffic to it; this run did not probe a separate HTTPS URL.')
            if response.status in {401, 403, 429} or response.headers.get('cf-mitigated', '').lower() == 'challenge':
                report['retry_after'] = response.headers.get('retry-after')
                raise AuditFailure(f'Website returned HTTP {response.status}; no access bypass or automatic retry attempted.', 'access_restricted')
            if not report['available']:
                raise AuditFailure(f'Website returned HTTP {response.status}; SEO findings were not inferred from an error page.', 'http_error')
            if not any(kind in report['content_type'].lower() for kind in ['text/html', 'application/xhtml+xml']):
                raise AuditFailure('Response was not HTML; static SEO checks were not performed.', 'unsupported_content')
            signals, findings = analyze_html(response.body, response.url, response.headers)
            report['html'] = signals
            report['findings'].extend(dict(finding, observed_at=response.fetched_at) for finding in findings)
            if use_pagespeed:
                await progress('Requesting optional PageSpeed mobile lab measurement')
                if await reserve_pagespeed():
                    try:
                        report['pagespeed'] = await measure_pagespeed(fetcher, response.url, key)
                    except AuditFailure as error:
                        report['pagespeed'] = {'status': 'unavailable', 'message': str(error), 'retry_after': error.retry_after}
                else:
                    report['pagespeed'] = {'status': 'unavailable', 'message': 'Local PageSpeed request budget or provider cooldown prevents a new call; no call was made.'}
            report['duration_ms'] = round((time.perf_counter() - started) * 1000, 2)
            return ('partial' if use_pagespeed and report['pagespeed']['status'] != 'available' else 'complete'), report, None
        except TimeoutError:
            return 'error', report, AuditFailure('The 35-second document audit budget expired.', 'timeout')
        except AuditFailure as error:
            return ('blocked' if error.code in {'unsafe_url', 'access_restricted'} else 'error'), report, error
        finally:
            report['requests'] = polite.evidence
            report['diagnostics'] = polite.failures
            report['redirects'] = polite.redirects
            if polite.evidence and polite.evidence[-1].get('retry_after'):
                report['retry_after'] = polite.evidence[-1]['retry_after']
