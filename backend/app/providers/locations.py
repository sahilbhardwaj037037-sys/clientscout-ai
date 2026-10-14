"""Pure location validation/query planning; no geocoder/network or guessed coordinates."""
from dataclasses import dataclass
import json
import math
import re

PLACE_TYPES = ('city', 'town', 'village', 'hamlet', 'suburb', 'neighbourhood', 'country')
COUNTRY_ALIASES = {'uk':'GB','gb':'GB','united kingdom':'GB','great britain':'GB', 'us':'US','usa':'US','united states':'US','united states of america':'US', 'india':'IN','canada':'CA','australia':'AU','germany':'DE','france':'FR','ireland':'IE','new zealand':'NZ','singapore':'SG','netherlands':'NL','spain':'ES','italy':'IT'}
# ISO codes can be supplied explicitly; unknown country names are never guessed.
ISO_CODES = frozenset('AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split())
MAX_BOUNDARY_KM2 = 16
MAX_BOUNDARY_SPAN_KM = 5

@dataclass(frozen=True)
class Location:
    label: str | None = None
    country: str | None = None
    coordinates: tuple | None = None
    relation_id: int | None = None


def parse_location(value):
    if value.startswith('osm:'):
        match = re.fullmatch(r'osm:relation/([1-9][0-9]{0,15})', value)
        if not match: raise ValueError('Use osm:relation/<positive OSM boundary ID>, or a place/country or coordinates.')
        return Location(relation_id=int(match[1]))
    parts = [part.strip() for part in value.split(',')]
    if len(parts) == 2:
        try: latitude, longitude = map(float, parts)
        except ValueError: pass
        else:
            if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError('Coordinates must be latitude (-90..90), longitude (-180..180).')
            return Location(coordinates=(latitude,longitude))
        country = COUNTRY_ALIASES.get(parts[1].casefold())
        if country is None and parts[1].upper() in ISO_CODES: country = parts[1].upper()
        if len(parts[0]) < 2 or not country: raise ValueError('Use City, country (e.g. London, UK), a two-letter ISO country code, or coordinates. Additional address/state qualifiers are not supported.')
        return Location(label=parts[0],country=country)
    if len(parts) != 1 or not parts[0]: raise ValueError('Use one place name, City, country, osm:relation/ID, or latitude, longitude.')
    return Location(label=parts[0])


def location_query(location):
    if location.relation_id:
        return f'[out:json][timeout:15][maxsize:8388608];rel({location.relation_id})["boundary"="administrative"];out tags bb 1;'
    names = list(dict.fromkeys([location.label, location.label.title()]))
    scope = '(area.country)' if location.country else ''
    prefix = f'area["ISO3166-1"={json.dumps(location.country)}]["boundary"="administrative"]["admin_level"="2"]->.country;.country out ids;' if location.country else ''
    statements=[]
    for name in names:
        for tag in ('name','name:en'):
            literal=f'[{json.dumps(tag)}={json.dumps(name,ensure_ascii=False)}]'
            statements.extend([f'node{scope}{literal}["place"~"^({"|".join(PLACE_TYPES)})$"];',f'rel{scope}{literal}["boundary"="administrative"];'])
    return '[out:json][timeout:15][maxsize:8388608];'+prefix+'('+''.join(statements)+');out tags bb 11;'


def valid_bounds(value):
    if not isinstance(value,dict): return None
    numbers = [value.get(key) for key in ('minlat','minlon','maxlat','maxlon')]
    if any(isinstance(n,bool) or not isinstance(n,(int,float)) for n in numbers): return None
    south,west,north,east=numbers
    if not (-90<=south<north<=90 and -180<=west<east<=180): return None
    return numbers


def boundary_is_small(bounds):
    south,west,north,east=bounds
    height=111.32*(north-south)
    # Upper bound across all latitudes in this bbox (not just its center).
    nearest_equator=0 if south<=0<=north else min(abs(south),abs(north))
    width=111.32*(east-west)*math.cos(math.radians(nearest_equator))
    return east-west <= 1 and height <= MAX_BOUNDARY_SPAN_KM and width <= MAX_BOUNDARY_SPAN_KM and width*height <= MAX_BOUNDARY_KM2
