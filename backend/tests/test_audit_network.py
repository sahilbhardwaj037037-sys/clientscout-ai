import asyncio
import ipaddress
import ssl
import httpcore
import pytest
from app.auditing.network import AuditFailure, PublicNetworkBackend, SafeFetcher, public_ip, resolve_public
from app.auditing.robots import redirect_target

@pytest.mark.parametrize('address', ['127.0.0.1', '10.1.2.3', '172.16.0.1', '192.168.1.1', '169.254.169.254',
    '100.100.100.200', '0.0.0.0', '255.255.255.255', '224.0.0.1', '::1', 'fe80::1', 'fc00::1', '::ffff:127.0.0.1',
    '64:ff9b::7f00:1', '2002:7f00:1::', '2001:0:4136:e378:8000:63bf:3fff:fdd2'])
def test_nonpublic_and_translation_addresses_are_blocked(address):
    with pytest.raises(AuditFailure): public_ip(address)

@pytest.mark.anyio
async def test_mixed_dns_answer_is_blocked_before_connection():
    calls = []
    class Delegate:
        async def connect_tcp(self, *args, **kwargs): calls.append(args)
    async def resolve(host, port): return ['93.184.216.34', '127.0.0.1']
    backend = PublicNetworkBackend(resolve, Delegate())
    with pytest.raises(AuditFailure): await backend.connect_tcp('example.com', 443)
    assert calls == []

@pytest.mark.anyio
async def test_pinned_socket_keeps_original_host_and_tls_sni():
    connections = []
    tls = []
    class Stream(httpcore.AsyncMockStream):
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls.append((server_hostname, ssl_context.verify_mode, ssl_context.check_hostname))
            return self
    class Delegate:
        async def connect_tcp(self, host, port, **kwargs):
            connections.append((host, port))
            return Stream([b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: text/html\r\n\r\nok'])
    async def resolve(host, port): return ['93.184.216.34']
    async with SafeFetcher(PublicNetworkBackend(resolve, Delegate())) as fetcher:
        response = await fetcher.get('https://example.com/')
        assert response.body == b'ok'
    assert connections == [('93.184.216.34', 443)]
    assert tls == [('example.com', ssl.CERT_REQUIRED, True)]

@pytest.mark.anyio
async def test_dns_rebinding_is_rechecked_for_new_connections():
    rounds = iter([['93.184.216.34'], ['169.254.169.254']])
    calls = []
    async def resolve(host, port): return next(rounds)
    class Delegate:
        async def connect_tcp(self, host, port, **kwargs):
            calls.append(host)
            return httpcore.AsyncMockStream([b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok'])
    async with SafeFetcher(PublicNetworkBackend(resolve, Delegate())) as fetcher:
        await fetcher.get('http://example.com/robots.txt')
        with pytest.raises(AuditFailure): await fetcher.get('http://example.com/')
    assert calls == ['93.184.216.34']

@pytest.mark.anyio
async def test_dns_lookup_has_all_answer_validation(monkeypatch):
    async def records(*args, **kwargs): return [(2, 1, 6, '', ('93.184.216.34', 443)), (2, 1, 6, '', ('10.0.0.1', 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', records)
    with pytest.raises(AuditFailure): await resolve_public('example.com', 443)

@pytest.mark.parametrize('location', ['http://127.0.0.1/', 'http://169.254.169.254/latest/meta-data',
    'https://user:secret@example.com/', 'file:///etc/passwd', 'https://example.com:9000', 'http://example.com/'])
def test_unsafe_redirect_targets_are_blocked(location):
    with pytest.raises(AuditFailure): redirect_target('https://example.com/', location)

@pytest.mark.anyio
async def test_size_limit_and_compressed_expansion_are_bounded():
    import gzip
    async def resolve(host, port): return ['93.184.216.34']
    class Delegate:
        def __init__(self, response): self.response = response
        async def connect_tcp(self, *args, **kwargs): return httpcore.AsyncMockStream([self.response])
    oversized = b'HTTP/1.1 200 OK\r\nContent-Length: 99\r\n\r\n'
    packed = gzip.compress(b'x' * 5000)
    compressed = b'HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: ' + str(len(packed)).encode() + b'\r\n\r\n' + packed
    for raw, maximum in [(oversized, 10), (compressed, 100)]:
        async with SafeFetcher(PublicNetworkBackend(resolve, Delegate(raw))) as fetcher:
            with pytest.raises(AuditFailure, match='body size'): await fetcher.get('http://example.com/', max_bytes=maximum)

@pytest.mark.anyio
async def test_request_timeout_stops_network_work():
    async def resolve(host, port): await asyncio.sleep(5); return ['93.184.216.34']
    async with SafeFetcher(PublicNetworkBackend(resolve)) as fetcher:
        with pytest.raises(AuditFailure, match='timed out'): await fetcher.get('http://example.com/', timeout=.01)

@pytest.mark.anyio
async def test_concatenated_gzip_is_not_silently_analyzed_as_partial_html():
    import gzip
    packed = gzip.compress(b'<title>Partial</title>') + gzip.compress(b'x' * 5000)
    raw = b'HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: ' + str(len(packed)).encode() + b'\r\n\r\n' + packed
    async def resolve(host, port): return ['93.184.216.34']
    class Delegate:
        async def connect_tcp(self, *args, **kwargs): return httpcore.AsyncMockStream([raw])
    async with SafeFetcher(PublicNetworkBackend(resolve, Delegate())) as fetcher:
        with pytest.raises(AuditFailure, match='no partial HTML'): await fetcher.get('http://example.com/', max_bytes=200)
