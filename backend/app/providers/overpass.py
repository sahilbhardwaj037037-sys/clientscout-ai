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
from app.providers.locations import parse_location, location_query, valid_bounds, boundary_is_small, PLACE_TYPES
from app.providers.diagnostics import trace, failure_kind

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
ALIASES = {'cafes': 'cafe', 'coffee': 'cafe', 'coffee shop': 'cafe', 'restaurants': 'restaurant', 'shops': 'shop', 'retail': 'shop', 'hotels': 'hotel', 'hairdresser': 'salon', 'bakeries': 'bakery', 'dentists': 'dentist', 'pharmacies': 'pharmacy', 'salons': 'salon', 'gyms': 'gym', 'offices': 'office'}
BUSINESS_AMENITIES = 'cafe|restaurant|fast_food|bar|pub|dentist|pharmacy|clinic|bank|veterinary|fuel'


class ProviderFailure(Exception):
    def __init__(self, message, retry_seconds=60, code='provider_error'):
        super().__init__(message)
        self.retry_seconds = retry_seconds
        self.code = code


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


def business_query(category, latitude, longitude, limit, radius=RADIUS, boundary=None):
    key = normalized_category(category)
    if boundary:
        bounds = boundary['bounds']
        if not boundary_is_small(bounds): raise ProviderFailure('Administrative boundary exceeds the safe 16 km² / 5 km-span bounding-box budget. Select nearby with 500 m or provide a smaller boundary.', code='area_too_large')
        area_id = 3600000000 + boundary['id']
        area = f'(area.target)({",".join(f"{n:.7f}" for n in bounds)})'
        prefix = f'area({area_id})->.target;.target out ids;'
    else:
        area = f'(around:{radius},{latitude:.7f},{longitude:.7f})'
        prefix = ''
    if key in CATEGORIES:
        tag, value = CATEGORIES[key]
        selectors = [f'[{json.dumps(tag)}' + (f'={json.dumps(value)}]' if value else ']')]
        keyword = ''
    else:
        selectors = ['["shop"]', '["office"]', '["craft"]', f'["amenity"~"^({BUSINESS_AMENITIES})$"]', '["tourism"~"^(hotel|hostel|guest_house)$"]', '["leisure"="fitness_centre"]']
        keyword = f'["name"~{json.dumps(re.escape(category), ensure_ascii=False)},i]'
    queries = ''.join(f'nwr{area}{selector}{keyword};' for selector in selectors)
    cap = min(200, max(20, limit * 4))
    return f'[out:json][timeout:20][maxsize:16777216];{prefix}({queries});out center {cap};', cap


def parse_document(body):
    try: document = json.loads(body)
    except (ValueError, UnicodeError): raise ProviderFailure('Provider returned invalid JSON; no results were substituted.') from None
    if not isinstance(document, dict) or not isinstance(document.get('elements'), list):
        raise ProviderFailure('Provider response is missing an elements list.')
    if document.get('remark'):
        remark = document['remark'] if isinstance(document['remark'], str) else 'Non-text provider remark'
        code, hint = failure_kind(200, remark)
        raise ProviderFailure('Overpass reported an incomplete or failed query. ' + hint, code=code)
    if len(document['elements']) > 1000: raise ProviderFailure('Provider returned more records than this bounded search permits.')
    return document


def parse_businesses(document, query, center, cap, scope='nearby', boundary=None):
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
        if scope == 'boundary':
            south,west,north,east = boundary['bounds']
            inside = south <= latitude <= north and west <= longitude <= east
        else: inside = distance <= query.radius_metres + 100
        if not inside: invalid += 1; continue
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
        'sample_may_be_truncated': len(document['elements']) >= cap, 'center': center, 'radius_metres': query.radius_metres if scope == 'nearby' else None, 'search_scope': scope, 'boundary': boundary if scope == 'boundary' else None,
        'attribution': ATTRIBUTION, 'copyright_url': COPYRIGHT_URL, 'licence_url': LICENCE_URL, 'fetched_at': fetched_at,
        'limitations': ['OSM coverage is incomplete; all business details and website availability remain unverified.',
            f'This is a bounded {query.radius_metres} m nearby sample, not a complete city/country directory.' if scope == 'nearby' else 'This is a candidate-capped sample inside the resolved administrative area and its small bounding box; not a complete directory.',
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

    async def request(self, fetcher, statement, progress, *, stage="provider"):
        for attempt in range(2):
            if attempt:
                await progress('Retrying the same provider once after permitted backoff')
            try:
                response = await fetcher.post(self.endpoint, content=urlencode({'data': statement}).encode(),
                    max_bytes=8 * 1024 * 1024, timeout=35, read_timeout=30,
                    user_agent='ClientScoutAI/0.3B (+https://github.com/sahilbhardwaj037037-sys; local single-user)')
            except AuditFailure as error:
                await progress(f'{stage}: provider transport failed', diagnostic=trace(statement,stage,failure=error))
                raise ProviderFailure(f'{stage}: provider network request stopped: ' + str(error), code=error.code) from None
            evidence = trace(statement,stage,response=response)
            await progress(f'{stage}: received provider HTTP {response.status}', diagnostic=evidence)
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
            if response.status != 200:
                code,hint=failure_kind(response.status,evidence.get('body_excerpt',''))
                raise ProviderFailure(f'{stage}: Overpass HTTP {response.status}. {hint} See saved request diagnostics.',code=code)
            try: return parse_document(response.body)
            except ProviderFailure as error:
                raise ProviderFailure(f'{stage}: HTTP 200 response rejected ({error.code}). {error} See saved provider remark and query.',error.retry_seconds,error.code) from None
        raise ProviderFailure('Provider retry budget exhausted.')

    async def search(self, query, progress, cache_get, cache_put):
        full_key = cache_key(self.endpoint, 'business-search-v2', query.model_dump())
        cached = cache_get(full_key)
        if cached is not None:
            await progress('Using an attributed cached provider result')
            return dict(cached, cache_hit=True)
        requested = parse_location(query.location)
        async with self.fetcher_factory() as fetcher:
            if requested.coordinates:
                latitude,longitude = requested.coordinates
                center = {'latitude':latitude,'longitude':longitude,'label':query.location,'kind':'User-supplied coordinates'}
            else:
                location_key = cache_key(self.endpoint,'place-v2',query.location.casefold())
                center = cache_get(location_key)
                if center is None:
                    await progress('Resolving country-qualified place/boundary metadata before businesses')
                    data = await self.request(fetcher,location_query(requested),progress,stage='location_resolution')
                    center = resolve_location(data,requested)
                    cache_put(location_key,center)
                    await asyncio.sleep(2)
            boundary = center.get('boundary')
            scope = query.search_scope
            if scope == 'boundary':
                if not boundary: raise ProviderFailure('No unambiguous administrative boundary was resolved. Use osm:relation/ID for an administrative boundary, or select nearby coordinates.',code='boundary_unresolved')
                if not boundary_is_small(boundary['bounds']): raise ProviderFailure('Resolved boundary exceeds the safe 16 km² / 5 km-span bounding-box budget. Select nearby (500 m recommended), or a smaller boundary. No city-wide business request was sent.',code='area_too_large')
            elif scope == 'auto': scope = 'boundary' if boundary and boundary_is_small(boundary['bounds']) else 'nearby'
            warnings = []
            if scope == 'nearby' and boundary:
                warnings.append('Using a nearby sample, not the entire resolved administrative boundary. Its bounding box exceeds the small-area budget.' if not boundary_is_small(boundary['bounds']) else 'Nearby mode was requested; administrative membership is not enforced for this sample.')
            if scope == 'nearby' and requested.relation_id:
                warnings.append('The nearby center is the boundary bounding-box center; it is not guaranteed inside the boundary. Choose coordinates for an intentional local fallback.')
            await progress(f'Querying {"small administrative boundary" if scope == "boundary" else str(query.radius_metres) + " m nearby sample"}')
            statement, cap = business_query(query.category,center['latitude'],center['longitude'],query.limit,query.radius_metres,boundary if scope == 'boundary' else None)
            document = await self.request(fetcher,statement,progress,stage='business_search')
            if scope == 'boundary':
                area_id = 3600000000 + boundary['id']
                if not any(isinstance(item,dict) and item.get('type')=='area' and item.get('id')==area_id for item in document['elements']):
                    raise ProviderFailure('Provider has no generated area for this boundary. Try nearby coordinates; no administrative results were claimed.',code='boundary_area_missing')
                document = dict(document,elements=[item for item in document['elements'] if not (isinstance(item,dict) and item.get('type')=='area' and item.get('id')==area_id)])
            result = parse_businesses(document,query,center,cap,scope,boundary)
            result['limitations'].extend(warnings)
            cache_put(full_key,result)
            return dict(result,cache_hit=False)


def resolve_location(document,requested):
    elements = document['elements']
    if requested.country:
        countries = {item.get('id') for item in elements if isinstance(item,dict) and item.get('type')=='area' and type(item.get('id')) is int and item['id']>0}
        if len(countries)!=1: raise ProviderFailure('Provider did not resolve exactly one country area. Check country code or use coordinates; no businesses requested.',code='country_area_unavailable')
        elements = [item for item in elements if not (isinstance(item,dict) and item.get('type')=='area')]
    if len(elements) >= 11: raise ProviderFailure('Location metadata candidate cap reached; name may be ambiguous. Add a country qualifier or use coordinates/osm:relation/ID. No businesses requested.',code='ambiguous_location')
    nodes, boundaries = {}, {}
    for element in elements:
        if not isinstance(element,dict) or type(element.get('id')) is not int or not 0<element['id']<=2**63-1 or not isinstance(element.get('tags'),dict): continue
        tags = element['tags']; identifier=element['id']
        if requested.relation_id:
            if element.get('type')!='relation' or identifier!=requested.relation_id: continue
        elif not any(isinstance(tags.get(key),str) and tags[key].casefold()==requested.label.casefold() for key in ('name','name:en')): continue
        if element.get('type')=='node' and tags.get('place') in PLACE_TYPES and location_point(element): nodes[identifier]=element
        elif element.get('type')=='relation' and tags.get('boundary')=='administrative' and valid_bounds(element.get('bounds')):
            boundaries[identifier]=element
    if len(nodes)>1 or len(boundaries)>1: raise ProviderFailure('Location is ambiguous. Add a country qualifier or use coordinates/osm:relation/ID; no businesses requested.',code='ambiguous_location')
    if not nodes and not boundaries: raise ProviderFailure('No exact OSM place label or administrative boundary found for the supplied location/country. Check spelling or use coordinates/osm:relation/ID.',code='location_not_found')
    node = next(iter(nodes.values()),None); relation = next(iter(boundaries.values()),None)
    boundary = None
    if relation:
        bounds=valid_bounds(relation['bounds'])
        boundary={'id':relation['id'],'bounds':bounds,'name':text(relation['tags'].get('name')) or 'Unnamed source boundary','source_url':f"https://www.openstreetmap.org/relation/{relation['id']}"}
    if node:
        latitude,longitude=location_point(node)
        if boundary:
            south,west,north,east=boundary['bounds']
            if not south<=latitude<=north or not west<=longitude<=east: raise ProviderFailure('Same-name place and boundary metadata disagree spatially. Use coordinates/osm:relation/ID; no businesses requested.',code='ambiguous_location')
        label=text(node['tags'].get('name')) or requested.label
        kind='OSM place label'; source_url=f"https://www.openstreetmap.org/node/{node['id']}"
    else:
        south,west,north,east=boundary['bounds']; latitude=(south+north)/2; longitude=(west+east)/2
        label=boundary['name']; kind='OSM administrative bounding-box center'; source_url=boundary['source_url']
    return {'latitude':latitude,'longitude':longitude,'label':label,'kind':kind,'source_url':source_url,'country_filter':requested.country,'boundary':boundary}
