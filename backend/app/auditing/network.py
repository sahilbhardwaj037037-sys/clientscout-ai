"""Pinned public-only sockets. No environment proxy, cookies, auth or auto redirects."""
import asyncio
import ipaddress
import socket
import ssl
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpcore
import certifi
from app.services.urls import normalize_url

USER_AGENT = 'ClientScoutAudit/0.3 (single-user public website audit)'
BLOCKED_V6 = [ipaddress.ip_network(network) for network in ['64:ff9b::/96', '64:ff9b:1::/48', '2002::/16', '2001::/32']]


class AuditFailure(Exception):
    def __init__(self, message, code='network_error', retry_after=None, diagnostics=None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
        self.diagnostics = diagnostics or {}


def failure_category(code):
    if code in {'unsafe_url', 'access_restricted', 'identity_mismatch', 'redirect_error', 'request_budget'}: return 'policy'
    if code.startswith('dns'): return 'dns'
    if code.startswith('tls'): return 'tls'
    if code.startswith('connect'): return 'connection'
    if code.startswith('read'): return 'read'
    if code.startswith('write'): return 'write'
    if code == 'pool_timeout': return 'pool'
    if code in {'body_limit', 'unsupported_encoding', 'decode_error'}: return 'response'
    return 'timeout' if code == 'timeout' else 'network'


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
    except TimeoutError:
        raise AuditFailure('Public hostname DNS lookup timed out (5-second limit).', 'dns_timeout', diagnostics={'stage':'dns'}) from None
    except OSError:
        raise AuditFailure('Public hostname DNS lookup failed; no socket was opened.', 'dns_error', diagnostics={'stage':'dns'}) from None
    addresses = list(dict.fromkeys(public_ip(record[4][0]) for record in records))
    if not addresses:
        raise AuditFailure('DNS returned no addresses.', 'dns_error')
    return addresses


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, resolver=resolve_public, delegate=None):
        self.resolver = resolver
        self.delegate = delegate or httpcore.AnyIOBackend()
        self.connections = []
        self.attempts = []
        self.resolutions = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port not in (80, 443):
            raise AuditFailure('Blocked nonstandard network port.', 'unsafe_url')
        lookup={'hostname':host,'outcome':'resolving'}
        self.resolutions.append(lookup);dns_started=time.monotonic()
        try:
            addresses = await self.resolver(host, port)
            # Check the entire answer set before any socket, including unused answers.
            addresses = list(dict.fromkeys(public_ip(address) for address in addresses))
            if not addresses:raise AuditFailure('DNS returned no public addresses.', 'dns_error')
            lookup.update(outcome='resolved',validated_addresses=addresses)
        except AuditFailure as error:
            lookup['outcome']=error.code;error.diagnostics.setdefault('stage','dns');raise
        except asyncio.CancelledError:lookup['outcome']='cancelled';raise
        finally:lookup['elapsed_ms']=round((time.monotonic()-dns_started)*1000,2)
        # One DNS answer set, fully validated before either attempt. Prefer a different
        # address family as the alternative when available. No HTTP/TLS/policy retry.
        candidates = [addresses[0]]
        if len(addresses)>1:
            family=ipaddress.ip_address(addresses[0]).version
            candidates.append(next((a for a in addresses[1:] if ipaddress.ip_address(a).version!=family),addresses[1]))
        budget=min(timeout if timeout is not None else 5,5)
        deadline=time.monotonic()+budget
        for index,selected in enumerate(candidates):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise httpcore.ConnectTimeout()
            attempt_timeout=remaining/(len(candidates)-index)
            started=time.monotonic()
            attempt={'hostname':host,'ip':selected,'timeout_seconds':attempt_timeout,'outcome':'connecting'}
            self.attempts.append(attempt)
            try:
                async with asyncio.timeout(attempt_timeout):
                    stream=await self.delegate.connect_tcp(selected,port,timeout=attempt_timeout,local_address=None,socket_options=socket_options)
            except (TimeoutError,httpcore.ConnectTimeout):
                attempt['outcome']='connect_timeout'
                if index==len(candidates)-1:raise httpcore.ConnectTimeout() from None
            except httpcore.ConnectError:
                attempt['outcome']='connect_error'
                if index==len(candidates)-1:raise
            except asyncio.CancelledError:
                attempt['outcome']='cancelled';raise
            else:
                attempt['outcome']='connected'
                self.connections.append({'hostname': host, 'validated_addresses': addresses, 'connected_ip': selected})
                # HTTP Host and TLS SNI remain the original hostname in httpcore.
                return stream
            finally:attempt['elapsed_ms']=round((time.monotonic()-started)*1000,2)

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
    diagnostics: dict = field(default_factory=dict)


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
        return await self._request(url, max_bytes=max_bytes, timeout=timeout, read_timeout=read_timeout)

    async def post(self, url, content, max_bytes=8 * 1024 * 1024, timeout=35, read_timeout=30, user_agent=USER_AGENT):
        return await self._request(url, max_bytes=max_bytes, timeout=timeout, read_timeout=read_timeout, method='POST', content=content, user_agent=user_agent)

    async def _request(self, url, max_bytes, timeout, read_timeout, method='GET', content=None, user_agent=USER_AGENT):
        try:
            url, _ = normalize_url(url)
        except ValueError as error:
            raise AuditFailure(str(error), 'unsafe_url') from None
        started = time.perf_counter()
        connections_before = len(self.backend.connections)
        attempts_before = len(getattr(self.backend,'attempts',[]))
        resolutions_before = len(getattr(self.backend,'resolutions',[]))
        stage='pool';timings={};phase_started=started;wire_bytes=0;body=bytearray();status=None
        phases={'connect_tcp':'connect','start_tls':'tls','send_request_headers':'write','send_request_body':'write','receive_response_headers':'response_headers','receive_response_body':'response_body'}
        async def trace(event,info):
            nonlocal stage,phase_started
            operation,outcome=event.split('.')[-2:]
            phase=phases.get(operation)
            if phase is None:return
            if outcome=='started':stage=phase;phase_started=time.perf_counter()
            elif outcome in {'complete','failed'}:
                timings[phase]=round(timings.get(phase,0)+(time.perf_counter()-phase_started)*1000,2)
        def diagnostics(code=None):
            lookups=getattr(self.backend,'resolutions',[])[resolutions_before:]
            attempts=getattr(self.backend,'attempts',[])[attempts_before:]
            current_stage='dns' if lookups and lookups[-1]['outcome'] in {'resolving','cancelled'} and not attempts else stage
            return {'stage':current_stage,'category':failure_category(code) if code else 'success','elapsed_ms':round((time.perf_counter()-started)*1000,2),'timings_ms':timings.copy(),'http_status':status,'wire_bytes':wire_bytes,'decoded_bytes':len(body),'dns_lookups':lookups,'connection_attempts':attempts,'connections':self.backend.connections[connections_before:],'limits':{'request_seconds':timeout,'connect_seconds':5,'read_seconds':read_timeout,'max_bytes':max_bytes}}
        def failure(message,code):return AuditFailure(message,code,diagnostics=diagnostics(code))
        try:
            async with asyncio.timeout(timeout):
                async with self.pool.stream(method, url, content=content, headers={
                    **({'Content-Type': 'application/x-www-form-urlencoded'} if method == 'POST' else {}),
                    'User-Agent': user_agent, 'Accept': 'text/html,text/plain,application/json;q=0.9,*/*;q=0.1',
                    'Accept-Encoding': 'identity',
                }, extensions={'timeout': {'connect': 5, 'read': read_timeout, 'write': 5, 'pool': 2},'trace':trace}) as response:
                    status=response.status
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
                        raise AuditFailure('Incomplete compressed response.', 'decode_error')
                    return Fetched(url, response.status, headers, bytes(body), round((time.perf_counter() - started) * 1000, 2),
                                   datetime.now(timezone.utc).isoformat(), self.backend.connections[connections_before:],diagnostics())
        except AuditFailure as error:
            error.diagnostics={**diagnostics(error.code),**error.diagnostics}
            raise
        except httpcore.ConnectTimeout:
            raise failure('TLS handshake timed out (5-second limit).' if stage=='tls' else 'TCP connection timed out (5-second aggregate socket budget; at most two validated addresses).','tls_timeout' if stage=='tls' else 'connect_timeout') from None
        except httpcore.ReadTimeout:
            raise failure('Website read timed out while waiting for '+('response headers' if stage=='response_headers' else 'response body')+f' ({read_timeout}-second inactivity limit).','read_timeout') from None
        except httpcore.WriteTimeout:
            raise failure('Website request write timed out (5-second limit).','write_timeout') from None
        except httpcore.PoolTimeout:
            raise failure('HTTP connection pool acquisition timed out (2-second limit).','pool_timeout') from None
        except (TimeoutError,httpcore.TimeoutException):
            details=diagnostics('timeout')
            raise AuditFailure(f'Website request timed out: total {timeout}-second deadline expired during {details["stage"].replace("_"," ")}.','timeout',diagnostics=details) from None
        except httpcore.ConnectError:
            raise failure('TLS certificate/handshake failed; verification remains required.' if stage=='tls' else 'TCP connection failed for the bounded validated public addresses.','tls_error' if stage=='tls' else 'connect_error') from None
        except httpcore.ReadError:
            raise failure('Website response read failed before a complete response was received.','read_error') from None
        except httpcore.WriteError:
            raise failure('Website request write failed.','write_error') from None
        except (ssl.SSLError,zlib.error):
            raise failure('TLS verification failed.' if stage=='tls' else 'Response decoding failed; no partial body was analyzed.','tls_error' if stage=='tls' else 'decode_error') from None
        except (httpcore.NetworkError, httpcore.ProtocolError, OSError):
            # Never persist exception strings: third-party URLs may contain sensitive query parameters.
            raise failure('Website transport or HTTP protocol failed; no partial body was analyzed.', 'network_error') from None
