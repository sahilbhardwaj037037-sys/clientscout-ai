"""Shared local settings. Root .env overrides shared defaults; process env wins."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / '.env', override=False)
DEFAULTS = json.loads((ROOT / 'config/local.json').read_text())


def port(name: str, default: int) -> int:
    value = int(os.environ.get(name) or default)
    if not 1 <= value <= 65535:
        raise ValueError(f'{name} must be between 1 and 65535')
    return value


API_PORT = port('CLIENTSCOUT_API_PORT', DEFAULTS['api_port'])
FRONTEND_PORT = port('CLIENTSCOUT_FRONTEND_PORT', DEFAULTS['frontend_port'])
DB_PATH = Path(os.environ.get('CLIENTSCOUT_DB_PATH') or ROOT / 'backend/data/clientscout.db').expanduser()
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH
DB_PATH = DB_PATH.resolve()

PAGESPEED_API_KEY = os.environ.get('PAGESPEED_API_KEY', '').strip()
_pagespeed_flag = (os.environ.get('PAGESPEED_ENABLED') or ('true' if PAGESPEED_API_KEY else 'false')).lower()
if _pagespeed_flag not in {'true', 'false'}:
    raise ValueError('PAGESPEED_ENABLED must be true or false.')
PAGESPEED_ENABLED = _pagespeed_flag == 'true'
PAGESPEED_DAILY_LIMIT = int(os.environ.get('PAGESPEED_DAILY_LIMIT') or 10)
if not 1 <= PAGESPEED_DAILY_LIMIT <= 100:
    raise ValueError('PAGESPEED_DAILY_LIMIT must be between 1 and 100.')

_discovery_flag = (os.environ.get('DISCOVERY_ENABLED') or 'true').lower()
if _discovery_flag not in {'true', 'false'}:
    raise ValueError('DISCOVERY_ENABLED must be true or false.')
DISCOVERY_ENABLED = _discovery_flag == 'true'
OVERPASS_API_URL = os.environ.get('OVERPASS_API_URL') or 'https://overpass-api.de/api/interpreter'

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY','').strip()
GEMINI_MODEL = os.environ.get('GEMINI_MODEL') or 'gemini-2.5-flash-lite'
import re
if not re.fullmatch(r'gemini-[a-z0-9.-]{1,70}',GEMINI_MODEL):
    raise ValueError('GEMINI_MODEL must be an explicit Gemini model identifier, not a URL.')
GEMINI_DAILY_LIMIT = int(os.environ.get('GEMINI_DAILY_LIMIT') or 10)
if not 1 <= GEMINI_DAILY_LIMIT <= 100:raise ValueError('GEMINI_DAILY_LIMIT must be 1..100.')
