import asyncio
from datetime import datetime, timezone
import pytest
from app.auditing.network import AuditFailure, Fetched
from app.auditing.runner import run_audit
from app.auditing.html import analyze_html
from app.auditing.pagespeed import parse_pagespeed
from app.auditing.robots import PoliteFetcher

HTML = b'<!doctype html><html lang="en"><head><title>Fixture title</title><meta name="description" content="Fixture description"><link rel="canonical" href="/canonical"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><h1>Fixture heading</h1><img src="a"><img src="b" alt=""></body></html>'

def fetched(url, status=200, body=HTML, headers=None):
    return Fetched(url, status, headers or {'content-type': 'text/html; charset=utf-8'}, body, 12.5, datetime.now(timezone.utc).isoformat(), [])

class FixtureFetcher:
    def __init__(self, responses): self.responses = responses; self.calls = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def get(self, url, **kwargs):
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, Exception): raise value
        return value

@pytest.mark.anyio
async def test_real_observation_structure_without_invented_metrics(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep', sleep)
    fetcher = FixtureFetcher({'https://example.com/robots.txt': fetched('https://example.com/robots.txt', 404, b''), 'https://example.com/': fetched('https://example.com/')})
    async def progress(_): pass
    async def reserve(): raise AssertionError('PageSpeed not requested')
    status, report, error = await run_audit('https://example.com/', False, progress, reserve, fetcher_factory=lambda: fetcher)
    assert status == 'complete' and error is None
    assert report['html']['titles'] == ['Fixture title'] and report['html']['meta_descriptions'] == ['Fixture description']
    assert report['html']['canonicals'] == [{'raw': '/canonical', 'resolved': 'https://example.com/canonical'}]
    assert report['html']['images_without_alt'] == 1 and report['html']['viewport']
    assert report['tls_verified'] is True and report['html_transfer_ms'] == 12.5
    assert report['pagespeed']['status'] == 'not_requested'
    assert all(finding['source_url'] == 'https://example.com/' and finding['observed_at'] for finding in report['findings'])

@pytest.mark.anyio
@pytest.mark.parametrize('robots_body', [b'User-agent: *\nDisallow: /private*', b'User-agent: ClientScoutAudit\nDisallow: /private$', b'User-agent: *\nCrawl-delay: 20'])
async def test_robots_restrictions_stop_before_page(robots_body):
    fetcher = FixtureFetcher({'https://example.com/robots.txt': fetched('https://example.com/robots.txt', 200, robots_body, {'content-type': 'text/plain'})})
    with pytest.raises(AuditFailure): await PoliteFetcher(fetcher).page('https://example.com/private')
    assert fetcher.calls == ['https://example.com/robots.txt']

@pytest.mark.anyio
@pytest.mark.parametrize('status', [401, 403, 429, 500, 503])
async def test_robots_fail_closed(status):
    fetcher = FixtureFetcher({'https://example.com/robots.txt': fetched('https://example.com/robots.txt', status, b'')})
    with pytest.raises(AuditFailure): await PoliteFetcher(fetcher).page('https://example.com/')
    assert len(fetcher.calls) == 1

@pytest.mark.anyio
async def test_public_redirect_rechecks_destination_robots(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep', sleep)
    fetcher = FixtureFetcher({
        'https://example.com/robots.txt': fetched('https://example.com/robots.txt', 404, b''),
        'https://example.com/': fetched('https://example.com/', 302, b'', {'location': 'https://other.example.org/'}),
        'https://other.example.org/robots.txt': fetched('https://other.example.org/robots.txt', 200, b'User-agent: *\nDisallow: /', {'content-type': 'text/plain'})})
    with pytest.raises(AuditFailure): await PoliteFetcher(fetcher).page('https://example.com/')
    assert fetcher.calls[-1] == 'https://other.example.org/robots.txt'

@pytest.mark.anyio
async def test_private_redirect_is_never_fetched(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep', sleep)
    fetcher = FixtureFetcher({'https://example.com/robots.txt': fetched('https://example.com/robots.txt', 404, b''),
                              'https://example.com/': fetched('https://example.com/', 302, b'', {'location': 'http://169.254.169.254/'})})
    with pytest.raises(AuditFailure): await PoliteFetcher(fetcher).page('https://example.com/')
    assert len(fetcher.calls) == 2

@pytest.mark.anyio
async def test_http_error_does_not_infer_seo(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep', sleep)
    fetcher = FixtureFetcher({'https://example.com/robots.txt': fetched('https://example.com/robots.txt', 404, b''),
                              'https://example.com/': fetched('https://example.com/', 404, HTML)})
    async def noop(*args): return True
    status, report, error = await run_audit('https://example.com/', False, noop, noop, fetcher_factory=lambda: fetcher)
    assert status == 'error' and error.code == 'http_error' and 'html' not in report
    assert report['http_status'] == 404 and report['available'] is False


def test_static_findings_explain_absence_and_noindex_without_scores():
    signals, findings = analyze_html(b'<html><meta name="robots" content="noindex"><h1>A</h1><h1>B</h1><img src="a"></html>', 'https://example.com/', {})
    codes = {finding['code'] for finding in findings}
    assert {'title_missing', 'description_missing', 'canonical_missing', 'noindex_observed', 'image_alt_missing', 'viewport_missing'} <= codes
    assert all('score' not in finding for finding in findings)
    assert signals['h1_count'] == 2


def psi_data():
    return {'lighthouseResult': {'requestedUrl': 'https://example.com/', 'finalUrl': 'https://example.com/', 'configSettings': {'formFactor': 'mobile'}, 'fetchTime': '2026-10-14T00:00:00Z', 'lighthouseVersion': 'fixture', 'categories': {'performance': {'score': .84}}, 'audits': {'largest-contentful-paint': {'numericValue': 2100, 'numericUnit': 'ms'}}}}


def test_pagespeed_uses_exact_numeric_provider_metrics_only():
    result = parse_pagespeed(psi_data(), 'https://example.com/')
    assert result['performance_score'] == 84 and result['metrics'][0]['value'] == 2100
    assert len(result['metrics']) == 1 and 'lab' in result['limitation']

@pytest.mark.parametrize('mutation', ['runtime', 'desktop', 'wrong_url', 'no_metrics'])
def test_pagespeed_rejects_failed_or_wrong_measurements(mutation):
    data = psi_data(); run = data['lighthouseResult']
    if mutation == 'runtime': run['runtimeError'] = {'code': 'FAILED_DOCUMENT_REQUEST'}
    if mutation == 'desktop': run['configSettings']['formFactor'] = 'desktop'
    if mutation == 'wrong_url': run['requestedUrl'] = 'https://other.example.org/'
    if mutation == 'no_metrics': run['audits'] = {}
    with pytest.raises(AuditFailure): parse_pagespeed(data, 'https://example.com/')

@pytest.mark.anyio
async def test_pagespeed_failure_retains_html_without_fake_metrics(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep', sleep)
    async def fail(*args): raise AuditFailure('Provider unavailable', 'pagespeed_error')
    monkeypatch.setattr('app.auditing.runner.measure_pagespeed', fail)
    fetcher = FixtureFetcher({'https://example.com/robots.txt': fetched('https://example.com/robots.txt', 404, b''), 'https://example.com/': fetched('https://example.com/')})
    async def noop(*args): return True
    status, report, error = await run_audit('https://example.com/', True, noop, noop, fetcher_factory=lambda: fetcher)
    assert status == 'partial' and error is None and report['html']['titles'] == ['Fixture title']
    assert report['pagespeed']['status'] == 'unavailable' and report['pagespeed']['message'] == 'Provider unavailable'
    assert 'metrics' not in report['pagespeed']


def test_malformed_canonical_is_reported_without_following_it():
    signals, findings = analyze_html(b'<html><link rel="canonical" href="https://[bad/"></html>', 'https://example.com/', {})
    assert signals['canonicals'][0]['resolved'] is None
    assert 'canonical_invalid' in {finding['code'] for finding in findings}

@pytest.mark.anyio
async def test_redirect_loop_is_bounded_and_not_analyzed(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep', sleep)
    fetcher = FixtureFetcher({'https://example.com/robots.txt': fetched('https://example.com/robots.txt', 404, b''),
                              'https://example.com/': fetched('https://example.com/', 302, b'', {'location': '/'})})
    with pytest.raises(AuditFailure, match='loop'): await PoliteFetcher(fetcher).page('https://example.com/')
    assert len(fetcher.calls) == 2

@pytest.mark.anyio
async def test_pagespeed_quota_and_key_are_not_reflected_in_errors():
    from app.auditing.pagespeed import measure_pagespeed, ENDPOINT
    class Provider:
        async def get(self, url, **kwargs):
            assert 'private-fixture-key' in url and kwargs['read_timeout'] == 60
            return fetched(ENDPOINT, 429, b'private-fixture-key', {'retry-after': '3600'})
    with pytest.raises(AuditFailure) as failure: await measure_pagespeed(Provider(), 'https://example.com/', 'private-fixture-key')
    assert 'private-fixture-key' not in str(failure.value) and failure.value.retry_after == '3600'

@pytest.mark.anyio
async def test_invalid_robots_encoding_fails_closed_before_page():
    fetcher = FixtureFetcher({'https://example.com/robots.txt': fetched('https://example.com/robots.txt', 200, b'User-agent: *\nDisallow: /\xff', {'content-type': 'text/plain'})})
    with pytest.raises(AuditFailure, match='UTF-8'): await PoliteFetcher(fetcher).page('https://example.com/')
    assert len(fetcher.calls) == 1
