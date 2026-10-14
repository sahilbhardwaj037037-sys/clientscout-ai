import asyncio
import math
import time
from urllib.parse import urljoin, urlsplit
from protego import Protego
from app.auditing.network import AuditFailure, USER_AGENT
from app.services.urls import normalize_url

REDIRECTS = {301, 302, 303, 307, 308}


def redirect_target(current, location):
    if not location:
        raise AuditFailure('Redirect has no Location header.', 'redirect_error')
    try:
        target, _ = normalize_url(urljoin(current, location))
    except ValueError as error:
        raise AuditFailure('Unsafe redirect: ' + str(error), 'unsafe_url') from None
    if urlsplit(current).scheme == 'https' and urlsplit(target).scheme != 'https':
        raise AuditFailure('HTTPS-to-HTTP downgrade redirect blocked.', 'unsafe_url')
    return target


class PoliteFetcher:
    def __init__(self, fetcher):
        self.fetcher = fetcher
        self.policies = {}
        self.last_request = {}
        self.evidence = []
        self.redirects = []

    @staticmethod
    def origin(url):
        parts = urlsplit(url)
        return f'{parts.scheme}://{parts.netloc}'

    @staticmethod
    def rate_key(url):
        return (urlsplit(url).hostname or '').removeprefix('www.')

    async def robots(self, url):
        origin = self.origin(url)
        if origin in self.policies:
            return self.policies[origin]
        current = origin + '/robots.txt'
        for hop in range(6):
            elapsed = time.monotonic() - self.last_request.get(self.rate_key(current), 0)
            if elapsed < 2: await asyncio.sleep(2 - elapsed)
            response = await self.fetcher.get(current, max_bytes=512 * 1024)
            self.last_request[self.rate_key(current)] = time.monotonic()
            self.evidence.append({'kind': 'robots', 'url': current, 'status': response.status, 'fetched_at': response.fetched_at, 'connections': response.connections, 'retry_after': response.headers.get('retry-after')})
            if response.status in REDIRECTS:
                if hop == 5:
                    raise AuditFailure('robots.txt redirect limit exceeded.', 'access_restricted')
                current = redirect_target(current, response.headers.get('location'))
                continue
            if response.status in {404, 410}:
                policy = (None, 2.0)
            elif response.status == 200:
                if 'html' in response.headers.get('content-type', '').lower() or b'\x00' in response.body or response.body.lstrip().lower().startswith((b'<!doctype html', b'<html')):
                    raise AuditFailure('robots.txt returned HTML or invalid data; permission could not be established.', 'access_restricted')
                try:
                    robots_text = response.body.decode('utf-8-sig')
                except UnicodeDecodeError:
                    raise AuditFailure('robots.txt is not valid UTF-8; permission could not be established.', 'access_restricted') from None
                rules = Protego.parse(robots_text)
                delay = max(2.0, rules.crawl_delay(USER_AGENT) or 0)
                rate = rules.request_rate(USER_AGENT)
                if rate:
                    if rate.start_time is not None or rate.end_time is not None or rate.requests <= 0:
                        raise AuditFailure('Timed robots request-rate restrictions are not supported; no audit attempted.', 'access_restricted')
                    delay = max(delay, rate.seconds / rate.requests)
                if rules.visit_time(USER_AGENT) is not None:
                    raise AuditFailure('robots.txt limits visit times; no audit attempted.', 'access_restricted')
                if not math.isfinite(delay) or delay > 10:
                    raise AuditFailure('robots.txt requires a delay beyond this short audit budget.', 'access_restricted')
                policy = (rules, delay)
            else:
                # Do not treat 401/403/429/5xx, bot challenges or DNS failure as permission.
                raise AuditFailure(f'robots.txt returned HTTP {response.status}; access was not attempted.', 'access_restricted')
            self.policies[origin] = policy
            return policy
        raise AuditFailure('robots.txt redirect limit exceeded.', 'access_restricted')

    async def page(self, url):
        current = url
        seen = set()
        for hop in range(6):
            if current in seen:
                raise AuditFailure('Website redirect loop detected.', 'redirect_error')
            seen.add(current)
            rules, delay = await self.robots(current)
            if rules and not rules.can_fetch(current, USER_AGENT):
                raise AuditFailure('robots.txt disallows this URL for ClientScoutAudit.', 'access_restricted')
            elapsed = time.monotonic() - self.last_request.get(self.rate_key(current), 0)
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)
            response = await self.fetcher.get(current)
            self.last_request[self.rate_key(current)] = time.monotonic()
            self.evidence.append({'kind': 'page', 'url': current, 'status': response.status, 'fetched_at': response.fetched_at, 'connections': response.connections, 'retry_after': response.headers.get('retry-after')})
            if response.status not in REDIRECTS:
                return response
            if hop == 5:
                raise AuditFailure('Website redirect limit exceeded.', 'redirect_error')
            target = redirect_target(current, response.headers.get('location'))
            self.redirects.append({'url': current, 'status': response.status, 'target': target, 'fetched_at': response.fetched_at})
            current = target
        raise AuditFailure('Website redirect limit exceeded.', 'redirect_error')
