from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.settings import DISCOVERY_ENABLED
from app.database.session import get_session
from app.discovery.manager import DiscoveryManager
from app.models.discovery import DiscoveredBusiness, DiscoverySearch
from app.providers.overpass import ATTRIBUTION, CATEGORIES, COPYRIGHT_URL, LICENCE_URL
from app.schemas.discovery import SaveSelection, SearchCreate, SearchRead

router = APIRouter(prefix='/api/discovery')
DB = Annotated[Session, Depends(get_session)]


def manager(request: Request): return request.app.state.discovery_manager
Manager = Annotated[DiscoveryManager, Depends(manager)]


def business_read(record):
    from app.discovery.manager import utc
    return {'id': record.id, **record.data, 'saved_at': utc(record.saved_at)}


@router.get('/config')
def configuration():
    return {'providers': [{'id': 'osm_overpass', 'name': 'OpenStreetMap · Overpass', 'configured': DISCOVERY_ENABLED,
                          'status': 'Configured; live availability checked when searching' if DISCOVERY_ENABLED else 'Disabled',
                          'attribution': ATTRIBUTION, 'copyright_url': COPYRIGHT_URL, 'licence_url': LICENCE_URL}],
            'categories': list(CATEGORIES), 'max_limit': 50, 'default_limit': 10, 'radius_metres': 2000,
            'search_interval_seconds': 30, 'daily_search_limit': 20, 'cache_hours': 24}


@router.post('/searches', response_model=SearchRead, status_code=202)
async def start(payload: SearchCreate, worker: Manager): return await worker.start(payload)


@router.get('/searches')
def history(session: DB, limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    total = session.scalar(select(func.count()).select_from(DiscoverySearch))
    records = session.scalars(select(DiscoverySearch).order_by(DiscoverySearch.id.desc()).limit(limit).offset(offset)).all()
    return {'items': [SearchRead.model_validate(record) for record in records], 'total': total, 'limit': limit, 'offset': offset}


@router.get('/searches/{identifier}', response_model=SearchRead)
def read(identifier: int, worker: Manager): return worker.read(identifier)


@router.post('/searches/{identifier}/cancel', response_model=SearchRead)
async def cancel(identifier: int, worker: Manager): return await worker.cancel(identifier)


@router.post('/searches/{identifier}/save')
def save(identifier: int, payload: SaveSelection, session: DB):
    record = session.get(DiscoverySearch, identifier)
    if record is None: raise HTTPException(404, 'Discovery search not found.')
    if record.status != 'complete' or not record.result: raise HTTPException(409, 'Only completed source results can be reviewed and saved.')
    candidates = {item['source_id']: item for item in record.result['items']}
    source_ids = list(dict.fromkeys(payload.source_ids))
    if any(identifier not in candidates for identifier in source_ids): raise HTTPException(422, 'Selection includes a record not returned by this search.')
    created, existing, saved = 0, 0, []
    for source_id in source_ids:
        candidate = candidates[source_id]
        if candidate.get('licence') != 'ODbL-1.0' or candidate.get('provider') != 'osm_overpass':
            raise HTTPException(422, 'Saving is unavailable for this source licence.')
    for source_id in source_ids:
        candidate = candidates[source_id]
        business = session.scalar(select(DiscoveredBusiness).where(DiscoveredBusiness.provider == candidate['provider'], DiscoveredBusiness.source_id == source_id))
        if business is not None:
            existing += 1; saved.append(business_read(business)); continue
        try:
            with session.begin_nested():
                business = DiscoveredBusiness(provider=candidate['provider'], source_id=source_id, data=candidate)
                session.add(business); session.flush()
            created += 1; saved.append(business_read(business))
        except IntegrityError:
            business = session.scalar(select(DiscoveredBusiness).where(DiscoveredBusiness.provider == candidate['provider'], DiscoveredBusiness.source_id == source_id))
            existing += 1
            if business is not None: saved.append(business_read(business))
    session.commit()
    return {'saved': created, 'existing': existing, 'items': saved, 'attribution': ATTRIBUTION, 'licence_url': LICENCE_URL}


@router.get('/saved')
def saved_businesses(session: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    total = session.scalar(select(func.count()).select_from(DiscoveredBusiness))
    records = session.scalars(select(DiscoveredBusiness).order_by(DiscoveredBusiness.id.desc()).limit(limit).offset(offset)).all()
    return {'items': [business_read(record) for record in records], 'total': total, 'limit': limit, 'offset': offset,
            'attribution': ATTRIBUTION, 'licence_url': LICENCE_URL}
