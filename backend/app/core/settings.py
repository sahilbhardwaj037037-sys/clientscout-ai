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
