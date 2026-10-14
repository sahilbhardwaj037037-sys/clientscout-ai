from typing import Annotated
from urllib.parse import unquote
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database.session import get_session
from app.models.intelligence import Assessment,OutreachDraft
from app.models.discovery import DiscoveredBusiness
from app.models.lead import Lead
from app.schemas.lead import LeadCreate, LeadPatch, LeadRead, LeadStatus
from app.services.imports import MAX_BYTES, parse_csv
from app.services.urls import normalize_url

router = APIRouter(prefix='/api')
DB = Annotated[Session, Depends(get_session)]


def get_lead(session: Session, lead_id: int):
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, 'Lead not found.')
    return lead


def new_lead(payload: LeadCreate, source: str, filename: str | None = None):
    fields = payload.model_dump()
    url, key = normalize_url(fields.pop('website_url'))
    fields['business_name'] = fields['business_name'] or key
    return Lead(**fields, website_url=url, normalized_key=key, original_url=payload.website_url,
                source=source, source_filename=filename)


def duplicate_error(session, key):
    existing = session.scalar(select(Lead).where(Lead.normalized_key == key))
    return HTTPException(409, {'message': 'A lead for this website already exists. Existing details were preserved.',
                              'existing_id': existing.id if existing else None})


@router.get('/leads')
def list_leads(session: DB, status: LeadStatus | None = None, q: str = Query('', max_length=200),
               limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    filters = []
    if status:
        filters.append(Lead.status == status)
    if q.strip():
        term = q.strip()
        filters.append(Lead.business_name.contains(term, autoescape=True) | Lead.website_url.contains(term, autoescape=True)
                       | Lead.location.contains(term, autoescape=True) | Lead.category.contains(term, autoescape=True))
    total = session.scalar(select(func.count()).select_from(Lead).where(*filters))
    leads = session.scalars(select(Lead).where(*filters).order_by(Lead.id.desc()).limit(limit).offset(offset)).all()
    return {'items': [LeadRead.model_validate(lead) for lead in leads], 'total': total, 'limit': limit, 'offset': offset}


@router.post('/leads', response_model=LeadRead, status_code=201)
def create_lead(payload: LeadCreate, session: DB):
    lead = new_lead(payload, 'manual')
    session.add(lead)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise duplicate_error(session, lead.normalized_key) from None
    session.refresh(lead)
    return lead


@router.get('/leads/{lead_id}', response_model=LeadRead)
def read_lead(lead_id: int, session: DB):
    return get_lead(session, lead_id)


@router.patch('/leads/{lead_id}', response_model=LeadRead)
def update_lead(lead_id: int, payload: LeadPatch, session: DB):
    lead = get_lead(session, lead_id)
    fields = payload.model_dump(exclude_unset=True)
    if 'website_url' in fields:
        fields['website_url'], fields['normalized_key'] = normalize_url(fields['website_url'])
    key = fields.get('normalized_key', lead.normalized_key)
    for field, value in fields.items():
        setattr(lead, field, value)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise duplicate_error(session, key) from None
    session.refresh(lead)
    return lead


@router.delete('/leads/{lead_id}', status_code=204)
def delete_lead(lead_id: int, session: DB):
    session.delete(get_lead(session, lead_id))
    session.commit()
    return Response(status_code=204)


@router.post('/imports/csv')
async def import_csv(request: Request, session: DB):
    if request.headers.get('content-type', '').split(';')[0].strip() not in {'text/csv', 'application/csv'}:
        raise HTTPException(415, 'Send a UTF-8 CSV with Content-Type: text/csv.')
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_BYTES:
            raise HTTPException(413, 'CSV must be at most 1 MiB.')
    filename = unquote(request.headers.get('x-import-filename', 'import.csv')).replace('\\', '/').split('/')[-1][:200]
    try:
        rows = parse_csv(bytes(buffer))
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    results = []
    # Parsing finishes before any writes. Accepted rows commit together; rejected and duplicate rows are explicit.
    with session.begin():
        for line, payload, error in rows:
            if payload is None:
                results.append({'line': line, 'outcome': 'invalid', 'message': error})
                continue
            lead = new_lead(payload, 'csv', filename)
            existing = session.scalar(select(Lead).where(Lead.normalized_key == lead.normalized_key))
            if existing:
                results.append({'line': line, 'outcome': 'duplicate', 'lead_id': existing.id, 'message': 'Existing lead preserved.'})
                continue
            try:
                with session.begin_nested():
                    session.add(lead)
                    session.flush()
                results.append({'line': line, 'outcome': 'created', 'lead_id': lead.id})
            except IntegrityError:
                existing = session.scalar(select(Lead).where(Lead.normalized_key == lead.normalized_key))
                results.append({'line': line, 'outcome': 'duplicate', 'lead_id': existing.id if existing else None,
                                'message': 'Existing lead preserved.'})
    return {'filename': filename, 'total': len(rows),
            'created': sum(r['outcome'] == 'created' for r in results),
            'duplicates': sum(r['outcome'] == 'duplicate' for r in results),
            'invalid': sum(r['outcome'] == 'invalid' for r in results), 'rows': results}


@router.get('/dashboard')
def dashboard(session: DB):
    from app.intelligence.freshness import assessment_current
    counts = dict(session.execute(select(Lead.status, func.count()).group_by(Lead.status)).all())
    recent = session.scalars(select(Lead).order_by(Lead.id.desc()).limit(5)).all()
    priorities=session.scalars(select(Assessment).where(Assessment.id.in_(select(func.max(Assessment.id)).group_by(Assessment.identity_id)),Assessment.score>=70,Assessment.qualification=='qualified')).all()
    return {'leads_found': sum(counts.values()), 'discovered_businesses': session.scalar(select(func.count()).select_from(DiscoveredBusiness)),
            'by_status': {status: counts.get(status, 0) for status in ['new', 'shortlisted', 'contacted', 'won', 'archived']},
            'high_priority': sum(assessment_current(session,a) for a in priorities), 'drafts_ready': session.scalar(select(func.count()).select_from(OutreachDraft).where(OutreachDraft.saved.is_(True))),
            'recent': [LeadRead.model_validate(lead) for lead in recent]}
