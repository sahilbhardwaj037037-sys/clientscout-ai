"""Validate stored user input only. Never resolve DNS or fetch a website here."""
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit


def normalize_url(value: str) -> tuple[str, str]:
    value = value.strip()
    if not value or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value) or '\\' in value:
        raise ValueError('Enter a valid public HTTP or HTTPS website URL (maximum 2048 characters).')
    if '://' not in value:
        value = 'https://' + value
    try:
        parts = urlsplit(value)
        host = (parts.hostname or '').rstrip('.').encode('idna').decode('ascii').lower()
        url_port = parts.port
    except (ValueError, UnicodeError):
        raise ValueError('Invalid website URL or port.') from None
    if parts.scheme not in {'http', 'https'} or parts.username is not None or parts.password is not None:
        raise ValueError('Only HTTP/HTTPS URLs without credentials are allowed.')
    if not host or host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid')):
        raise ValueError('Use a public website hostname; local addresses are not allowed.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host or len(host) > 253 or not re.fullmatch(r'[a-z0-9.-]+', host):
            raise ValueError('Use a valid public website hostname.') from None
        if re.fullmatch(r'[0-9.]+', host) or host.startswith('0x'):
            raise ValueError('Nonstandard numeric IP addresses are not allowed.')
        if any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-') for label in host.split('.')):
            raise ValueError('Invalid website hostname.')
    else:
        if not address.is_global or address.is_multicast:
            raise ValueError('Private, loopback, link-local and reserved IP addresses are not allowed.')
    if url_port not in {None, 80, 443}:
        raise ValueError('Only standard website ports (80 or 443) are allowed.')
    host_display = f'[{host}]' if ':' in host else host
    default_port = 80 if parts.scheme == 'http' else 443
    authority = host_display + (f':{url_port}' if url_port and url_port != default_port else '')
    url = urlunsplit((parts.scheme, authority, parts.path or '/', parts.query, ''))
    # One business per hostname, ignoring scheme, www, path, query and standard port.
    key = host.removeprefix('www.')
    return url, key
