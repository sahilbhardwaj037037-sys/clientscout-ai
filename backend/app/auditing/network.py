"""Pinned public-only sockets. No environment proxy, cookies, auth or auto redirects."""
import asyncio
import ipaddress
import socket
import ssl
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone

import httpcore
import certifi
from app.services.urls import normalize_url

USER_AGENT = 'ClientScoutAudit/0.3 (single-user public website audit)'
BLOCKED_V6 = [ipaddress.ip_network(network) for network in ['64:ff9b::/96', '64:ff9b:1::/48', '2002::/16', '2001::/32']]


class AuditFailure(Exception):
    def __init__(self, message, code='network_error', retry_after=None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


def public_ip(value: str):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise AuditFailure('DNS returned an invalid address.', 'unsafe_url') from None
    if '%' in value or not address.is_global or address.is_multicast:
        raise AuditFailure('Blocked non-public IP address.', 'unsafe_url')
    if address.version == 6 and (address.ipv4_mapped is not None or any(address in network for network in BLOCKED_V6)):
        raise AuditFailure('Blocked IPv6 translation or transition address.', 'unsafe_url')
    return str(address)


async def resolve_public(host, port):
    try:
        records = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), 5)
    except (OSError, TimeoutError):
        raise AuditFailure('Public hostname DNS lookup failed or timed out.', 'dns_error') from None
    addresses = list(dict.fromkeys(public_ip(record[4][0]) for record in records))
    if not addresses:
        raise AuditFailure('DNS returned no addresses.', 'dns_error')
    return addresses


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, resolver=resolve_public, delegate=None):
        self.resolver = resolver
        self.delegate = delegate or httpcore.AnyIOBackend()
        self.connections = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port not in (80, 443):
            raise AuditFailure('Blocked nonstandard network port.', 'unsafe_url')
        addresses = await self.resolver(host, port)
        # Check the entire answer set. Connect to a literal; no second hostname lookup.
        addresses = [public_ip(address) for address in addresses]
        if not addresses:
            raise AuditFailure('DNS returned no public addresses.', 'dns_error')
        selected = addresses[0]
        stream = await self.delegate.connect_tcp(selected, port, timeout=timeout, local_address=None, socket_options=socket_options)
        self.connections.append({'hostname': host, 'validated_addresses': addresses, 'connected_ip': selected})
        # HTTP Host and TLS SNI remain the original hostname in httpcore's connection layer.
        return stream

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


@dataclass
class Fetched:
    url: str
    status: int
    headers: dict
    body: bytes
    elapsed_ms: float
    fetched_at: str
    connections: list


class SafeFetcher:
    def __init__(self, backend=None):
        self.backend = backend or PublicNetworkBackend()
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(cafile=certifi.where()), network_backend=self.backend,
            max_connections=2, max_keepalive_connections=0, retries=0,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.pool.aclose()

    async def get(self, url, max_bytes=2 * 1024 * 1024, timeout=12, read_timeout=8):
        try:
            url, _ = normalize_url(url)
        except ValueError as error:
            raise AuditFailure(str(error), 'unsafe_url') from None
        started = time.perf_counter()
        connections_before = len(self.backend.connections)
        try:
            async with asyncio.timeout(timeout):
                async with self.pool.stream('GET', url, headers={
                    'User-Agent': USER_AGENT, 'Accept': 'text/html,text/plain,application/json;q=0.9,*/*;q=0.1',
                    'Accept-Encoding': 'identity',
                }, extensions={'timeout': {'connect': 5, 'read': read_timeout, 'write': 5, 'pool': 2}}) as response:
                    headers = {}
                    for key, value in response.headers:
                        name = key.decode('ascii', 'replace').lower()
                        text = value.decode('latin1')
                        headers[name] = headers[name] + ', ' + text if name in headers else text
                    if headers.get('content-length', '').isdigit() and int(headers['content-length']) > max_bytes:
                        raise AuditFailure('Response exceeds the permitted body size.', 'body_limit')
                    encoding = headers.get('content-encoding', '').lower()
                    if encoding not in {'', 'identity', 'gzip'}:
                        raise AuditFailure('Unsupported content compression; analysis was not guessed.', 'unsupported_encoding')
                    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == 'gzip' else None
                    body = bytearray()
                    wire_bytes = 0
                    async for chunk in response.aiter_stream():
                        wire_bytes += len(chunk)
                        if wire_bytes > max_bytes:
                            raise AuditFailure('Response exceeds the permitted body size.', 'body_limit')
                        decoded = decompressor.decompress(chunk, max_bytes + 1 - len(body)) if decompressor else chunk
                        body.extend(decoded)
                        if len(body) > max_bytes or decompressor and decompressor.unconsumed_tail:
                            raise AuditFailure('Decoded response exceeds the permitted body size.', 'body_limit')
                    if decompressor and decompressor.unused_data:
                        raise AuditFailure('Concatenated or trailing gzip data is unsupported; no partial HTML was analyzed.', 'unsupported_encoding')
                    if decompressor and not decompressor.eof:
                        raise AuditFailure('Incomplete compressed response.', 'network_error')
                    return Fetched(url, response.status, headers, bytes(body), round((time.perf_counter() - started) * 1000, 2),
                                   datetime.now(timezone.utc).isoformat(), self.backend.connections[connections_before:])
        except AuditFailure:
            raise
        except (TimeoutError, httpcore.TimeoutException):
            raise AuditFailure('Website request timed out.', 'timeout') from None
        except (httpcore.NetworkError, httpcore.ProtocolError, ssl.SSLError, zlib.error, OSError):
            # Never persist exception strings: third-party URLs may contain sensitive query parameters.
            raise AuditFailure('Website connection, TLS verification or response decoding failed.', 'network_error') from None
