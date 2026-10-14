import json
import math
from urllib.parse import urlencode
from app.auditing.network import AuditFailure
from app.services.urls import normalize_url

ENDPOINT = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed'
METRICS = {'first-contentful-paint': ('First Contentful Paint', 'ms'), 'largest-contentful-paint': ('Largest Contentful Paint', 'ms'),
           'total-blocking-time': ('Total Blocking Time', 'ms'), 'cumulative-layout-shift': ('Cumulative Layout Shift', 'unitless'),
           'speed-index': ('Speed Index', 'ms')}


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def parse_pagespeed(data, requested_url):
    lighthouse = data.get('lighthouseResult')
    if not isinstance(lighthouse, dict) or lighthouse.get('runtimeError'):
        raise AuditFailure('PageSpeed did not return a successful Lighthouse run.', 'pagespeed_error')
    final = lighthouse.get('finalUrl')
    try:
        final, _ = normalize_url(final or '')
        requested, _ = normalize_url(lighthouse.get('requestedUrl') or '')
    except ValueError:
        raise AuditFailure('PageSpeed returned an invalid measured URL.', 'pagespeed_error') from None
    if requested != requested_url:
        raise AuditFailure('PageSpeed response does not match the requested URL.', 'pagespeed_error')
    settings = lighthouse.get('configSettings', {})
    if (settings.get('formFactor') or settings.get('emulatedFormFactor')) != 'mobile':
        raise AuditFailure('PageSpeed response is not a mobile measurement.', 'pagespeed_error')
    performance = lighthouse.get('categories', {}).get('performance', {}).get('score')
    audits = lighthouse.get('audits', {})
    metrics = []
    for key, (label, unit) in METRICS.items():
        audit = audits.get(key, {})
        value = audit.get('numericValue')
        if numeric(value) and audit.get('numericUnit') == unit:
            metrics.append({'id': key, 'label': label, 'value': value, 'unit': unit})
    if not metrics:
        raise AuditFailure('PageSpeed returned no supported numeric lab metrics.', 'pagespeed_error')
    recommendations = []
    for key, audit in audits.items():
        details = audit.get('details') or {}
        saved_ms = details.get('overallSavingsMs')
        saved_bytes = details.get('overallSavingsBytes')
        if numeric(saved_ms) and saved_ms > 0 or numeric(saved_bytes) and saved_bytes > 0:
            recommendations.append({'id': key, 'title': str(audit.get('title', key))[:300],
                                    'estimated_savings_ms': saved_ms if numeric(saved_ms) else None,
                                    'estimated_savings_bytes': saved_bytes if numeric(saved_bytes) else None})
    return {'status': 'available', 'source': 'Google PageSpeed Insights / Lighthouse mobile lab', 'source_url': ENDPOINT,
            'requested_url': requested_url, 'final_url': final, 'fetch_time': lighthouse.get('fetchTime'),
            'lighthouse_version': lighthouse.get('lighthouseVersion'),
            'performance_score': round(performance * 100, 2) if numeric(performance) and performance <= 1 else None,
            'metrics': metrics, 'recommendations': recommendations[:20],
            'warnings': [str(warning)[:1000] for warning in lighthouse.get('runWarnings', [])[:20]],
            'limitation': 'One emulated mobile lab run; not real-user field data, a sales score or proof of mobile usability.'}


async def measure_pagespeed(fetcher, url, key):
    params = {'url': url, 'strategy': 'mobile', 'category': 'performance'}
    if key: params['key'] = key
    # Fixed provider origin, pinned public transport, no redirects, no retries. Never log/persist this request URL.
    response = await fetcher.get(ENDPOINT + '?' + urlencode(params), max_bytes=4 * 1024 * 1024, timeout=60, read_timeout=60)
    if response.status != 200:
        raise AuditFailure(f'PageSpeed returned HTTP {response.status}. No mobile metrics were substituted.', 'pagespeed_error', retry_after=response.headers.get('retry-after') or ('3600' if response.status == 429 else None))
    try:
        data = json.loads(response.body)
        if not isinstance(data, dict): raise ValueError()
        return parse_pagespeed(data, url)
    except (ValueError, TypeError, AttributeError):
        raise AuditFailure('PageSpeed returned an unsupported response; no metrics were substituted.', 'pagespeed_error') from None
