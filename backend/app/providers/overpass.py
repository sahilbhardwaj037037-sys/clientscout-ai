"""Bounded, user-triggered Overpass queries. No Nominatim, scraping or site fetching."""
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import re
import unicodedata
from urllib.parse import urlencode, urlsplit
from app.auditing.network import AuditFailure, SafeFetcher
from app.services.urls import normalize_url

ATTRIBUTION = '© OpenStreetMap contributors'
LICENCE_URL = 'https://opendatacommons.org/licenses/odbl/1-0/'
COPYRIGHT_URL = 'https://www.openstreetmap.org/copyright'
RADIUS = 2000
CATEGORIES = {
    'cafe': ('amenity', 'cafe'), 'restaurant': ('amenity', 'restaurant'), 'bakery': ('shop', 'bakery'),
    'hotel': ('tourism', 'hotel'), 'dentist': ('amenity', 'dentist'), 'pharmacy': ('amenity', 'pharmacy'),
    'salon': ('shop', 'hairdresser'), 'gym': ('leisure', 'fitness_centre'), 'shop': ('shop', None),
    'office': ('office', None), 'car repair': ('shop', 'car_repair'),
}
ALIASES = {'cafes': 'cafe', 'coffee': 'cafe', 'coffee shop': 'cafe', 'restaurants': 'restaurant', 'shops': 'shop', 'retail': 'shop', 'hotels': 'hotel', 'hairdresser': 'salon'}
BUSINESS_AMENITIES = 'cafe|restaurant|fast_food|bar|pub|dentist|pharmacy|clinic|bank|veterinary|fuel'


class ProviderFailure(Exception):
    def __init__(self, message, retry_seconds=60):
        super().__init__(message)
        self.retry_seconds = retry_seconds


def text(value, maximum=200):
    return value.strip()[:maximum] if isinstance(value, str) and value.strip() else None


def location_point(value):
    if not isinstance(value, dict): return None
    latitude, longitude = value.get('lat'), value.get('lon')
    if any(isinstance(number, bool) or not isinstance(number, (float, int)) for number in [latitude, longitude]): return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180: return None
    return (latitude, longitude) if math.isfinite(latitude) and math.isfinite(longitude) else None


def cache_key(endpoint, kind, value):
    return hashlib.sha256(json.dumps([endpoint, kind, value], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def normalized_category(value):
    key = ''.join(char for char in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(char))
    return ALIASES.get(key, key)


def business_query(category, latitude, longitude, limit):
    key = normalized_category(category)
    area = f'(around:{RADIUS},{latitude:.7f},{longitude:.7f})'
    if key in CATEGORIES:
        tag, value = CATEGORIES[key]
        selectors = [f'[{json.dumps(tag)}' + (f'={json.dumps(value)}]' if value else ']')]
        keyword = ''
    else:
        selectors = ['["shop"]', '["office"]', '["craft"]', f'["amenity"~"^({BUSINESS_AMENITIES})$"]', '["tourism"~"^(hotel|hostel|guest_house)$"]', '["leisure"="fitness_centre"]']
        keyword = f'["name"~{json.dumps(re.escape(category), ensure_ascii=False)},i]'
    queries = ''.join(f'nwr{area}{selector}{keyword};' for selector in selectors)
    cap = min(200, max(20, limit * 4))
    return f'[out:json][timeout:20][maxsize:16777216];({queries});out center {cap};', cap


def parse_document(body):
    try: document = json.loads(body)
    except (ValueError, UnicodeError): raise ProviderFailure('Provider returned invalid JSON; no results were substituted.') from None
    if not isinstance(document, dict) or not isinstance(document.get('elements'), list):
        raise ProviderFailure('Provider response is missing an elements list.')
    if document.get('remark'):
        raise ProviderFailure('Overpass reported an incomplete or failed query. Results were not presented as a successful search.')
    if len(document['elements']) > 1000: raise ProviderFailure('Provider returned more records than this bounded search permits.')
    return document


def parse_businesses(document, query, center, cap):
    items, identities, physical, invalid, duplicates = [], set(), set(), 0, 0
    fetched_at = datetime.now(timezone.utc).isoformat()
    for element in document['elements'][:cap]:
        if not isinstance(element, dict): invalid += 1; continue
        kind, identifier, tags = element.get('type'), element.get('id'), element.get('tags')
        point = location_point(element) if kind == 'node' else location_point(element.get('center'))
        if kind not in {'node', 'way', 'relation'} or type(identifier) is not int or not 0 < identifier <= 2**63 - 1 or not isinstance(tags, dict) or point is None:
            invalid += 1; continue
        category = next((text(tags.get(key), 100) for key in ['shop', 'craft', 'office', 'amenity', 'tourism', 'leisure'] if text(tags.get(key), 100)), None)
        key = normalized_category(query.category)
        if key in CATEGORIES:
            tag, expected = CATEGORIES[key]
            matches = bool(text(tags.get(tag))) and (expected is None or tags[tag] == expected)
        else:
            matches = (any(text(tags.get(tag)) for tag in ['shop', 'office', 'craft']) or tags.get('amenity') in BUSINESS_AMENITIES.split('|') or tags.get('tourism') in ('hotel','hostel','guest_house') or tags.get('leisure') == 'fitness_centre') and query.category.casefold() in (text(tags.get('name')) or '').casefold()
        if category is None or not matches: invalid += 1; continue
        # Reject out-of-area records, including malformed/misrouted provider responses.
        latitude, longitude = point
        dy = math.radians(latitude - center['latitude']); dx = math.radians(longitude - center['longitude'])
        haversine = math.sin(dy/2)**2 + math.cos(math.radians(latitude))*math.cos(math.radians(center['latitude']))*math.sin(dx/2)**2
        distance = 6371000 * 2 * math.asin(min(1, math.sqrt(haversine)))
        if distance > RADIUS + 100: invalid += 1; continue
        source_id = f'{kind}/{identifier}'
        name = text(tags.get('name')) or text(tags.get('name:en'))
        raw_website = text(tags.get('website'), 2048) or text(tags.get('contact:website'), 2048)
        website, warning = None, None
        if raw_website:
            try: website, _ = normalize_url(raw_website)
            except ValueError: warning = 'The source website value was invalid/unsafe and was not stored.'
        key = (name.casefold(), round(latitude, 5), round(longitude, 5), website) if name else None
        if source_id in identities or key is not None and key in physical: duplicates += 1; continue
        identities.add(source_id)
        if key is not None: physical.add(key)
        if query.website_filter == 'with' and not website or query.website_filter == 'without' and website: continue
        address = ', '.join(value for key in ['addr:housenumber','addr:street','addr:city','addr:postcode','addr:country'] if (value := text(tags.get(key))))
        items.append({'provider': 'osm_overpass', 'source_id': source_id, 'source_url': f'https://www.openstreetmap.org/{source_id}',
            'name': name, 'website_url': website, 'location': address or None, 'category': category,
            'latitude': latitude, 'longitude': longitude, 'coordinate_kind': 'OSM node' if kind == 'node' else 'OSM object bounding-box center',
            'fetched_at': fetched_at, 'source_timestamp': text(document.get('osm3s', {}).get('timestamp_osm_base'), 100) if isinstance(document.get('osm3s'), dict) else None,
            'attribution': ATTRIBUTION, 'licence': 'ODbL-1.0', 'licence_url': LICENCE_URL, 'unverified': True,
            'warnings': [warning] if warning else []})
        if len(items) == query.limit: break
    return {'items': items, 'invalid_records': invalid, 'duplicates_removed': duplicates, 'candidate_cap': cap,
        'sample_may_be_truncated': len(document['elements']) >= cap, 'center': center, 'radius_metres': RADIUS,
        'attribution': ATTRIBUTION, 'copyright_url': COPYRIGHT_URL, 'licence_url': LICENCE_URL, 'fetched_at': fetched_at,
        'limitations': ['OSM coverage is incomplete; all business details and website availability remain unverified.',
            'This is a bounded sample within 2 km of the resolved center, not a complete city/country directory.',
            'Website missing means no usable website tag was returned; it does not prove the business has no website.',
            'Distinct branches sharing a website are preserved; source ID and exact name/position duplicates are removed.']}


class OverpassProvider:
    id = 'osm_overpass'
    def __init__(self, endpoint, fetcher_factory=SafeFetcher):
        try:
            canonical, _ = normalize_url(endpoint)
        except ValueError: raise ValueError('OVERPASS_API_URL must be a public HTTPS URL.') from None
        parts = urlsplit(endpoint)
        if parts.scheme != 'https' or parts.query or parts.fragment:
            raise ValueError('OVERPASS_API_URL must be HTTPS without credentials/query/fragment.')
        self.endpoint = canonical
        self.fetcher_factory = fetcher_factory

    async def request(self, fetcher, statement, progress):
        for attempt in range(2):
            if attempt:
                await progress('Retrying the same provider once after permitted backoff')
            try:
                response = await fetcher.post(self.endpoint, content=urlencode({'data': statement}).encode(),
                    max_bytes=8 * 1024 * 1024, timeout=35, read_timeout=30,
                    user_agent='ClientScoutAI/0.3B (+https://github.com/sahilbhardwaj037037-sys; local single-user)')
            except AuditFailure as error: raise ProviderFailure('Provider network request stopped: ' + str(error)) from None
            if response.status in {429, 503}:
                wait = 30
                header = response.headers.get('retry-after')
                if header:
                    try:
                        wait = int(header) if header.isdigit() else math.ceil((parsedate_to_datetime(header).astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError): wait = 3600
                wait = max(5, wait)
                # Only one retry and only when the provider explicitly permits a short delay.
                if attempt == 0 and header and wait <= 15:
                    await progress(f'Provider HTTP {response.status}; waiting {wait}s before one retry')
                    await asyncio.sleep(wait)
                    continue
                raise ProviderFailure(f'Provider returned HTTP {response.status}. Wait before manually retrying; no alternate source was substituted.', wait)
            if response.status != 200: raise ProviderFailure(f'Overpass returned HTTP {response.status}; check provider configuration or try later.')
            return parse_document(response.body)
        raise ProviderFailure('Provider retry budget exhausted.')

    async def search(self, query, progress, cache_get, cache_put):
        full_key = cache_key(self.endpoint, 'business-search', query.model_dump())
        cached = cache_get(full_key)
        if cached is not None:
            await progress('Using an attributed cached provider result')
            return dict(cached, cache_hit=True)
        async with self.fetcher_factory() as fetcher:
            parts = query.location.split(',')
            try:
                latitude, longitude = map(float, parts) if len(parts) == 2 else (None, None)
            except ValueError: latitude, longitude = None, None
            if latitude is not None:
                center = {'latitude': latitude, 'longitude': longitude, 'label': query.location, 'kind': 'User-supplied coordinates'}
            else:
                location_key = cache_key(self.endpoint, 'place', query.location.casefold())
                center = cache_get(location_key)
                if center is None:
                    await progress('Resolving the exact OSM place label')
                    literal = json.dumps('^' + re.escape(query.location) + '$', ensure_ascii=False)
                    statement = f'[out:json][timeout:15][maxsize:8388608];(node["place"~"^(city|town|village|hamlet|suburb|neighbourhood|country)$"]["name"~{literal},i];node["place"~"^(city|town|village|hamlet|suburb|neighbourhood|country)$"]["name:en"~{literal},i];);out 10;'
                    data = await self.request(fetcher, statement, progress)
                    places = {element['id']: element for element in data['elements'] if isinstance(element, dict) and element.get('type') == 'node' and type(element.get('id')) is int and 0 < element['id'] <= 2**63 - 1 and location_point(element) is not None and isinstance(element.get('tags'), dict) and element['tags'].get('place') in {'city','town','village','hamlet','suburb','neighbourhood','country'} and any(isinstance(element['tags'].get(key), str) and element['tags'][key].casefold() == query.location.casefold() for key in ['name','name:en'])}
                    if not places: raise ProviderFailure('No exact OSM place label found. Try a local/English place name or latitude, longitude coordinates.')
                    if len(places) != 1: raise ProviderFailure('Location is ambiguous in OSM. Enter latitude, longitude for the intended city/area instead of choosing a location silently.')
                    place = next(iter(places.values())); latitude, longitude = location_point(place)
                    center = {'latitude': latitude, 'longitude': longitude, 'label': text(place['tags'].get('name')) or query.location, 'kind': 'OSM place label', 'source_url': f"https://www.openstreetmap.org/node/{place['id']}"}
                    cache_put(location_key, center)
                    await asyncio.sleep(2)
            latitude, longitude = center['latitude'], center['longitude']
            await progress('Querying bounded OSM business records')
            statement, cap = business_query(query.category, latitude, longitude, query.limit)
            document = await self.request(fetcher, statement, progress)
            result = parse_businesses(document, query, center, cap)
            cache_put(full_key, result)
            return dict(result, cache_hit=False)
