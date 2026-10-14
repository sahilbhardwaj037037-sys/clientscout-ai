from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.auditing.manager import AuditManager
from app.core.settings import PAGESPEED_DAILY_LIMIT, PAGESPEED_ENABLED
from app.database.session import get_session
from app.models.audit import Audit
from app.schemas.audit import AuditCreate, AuditRead

router = APIRouter(prefix='/api/audits')


def manager(request: Request) -> AuditManager:
    return request.app.state.audit_manager

Manager = Annotated[AuditManager, Depends(manager)]


@router.get('/config')
def configuration():
    return {'pagespeed_enabled': PAGESPEED_ENABLED, 'pagespeed_daily_limit': PAGESPEED_DAILY_LIMIT,
            'max_active': 2, 'hostname_cooldown_seconds': 60, 'total_timeout_seconds': 100}


@router.post('', response_model=AuditRead, status_code=202)
async def start(payload: AuditCreate, worker: Manager):
    return await worker.start(payload)


@router.get('')
def history(session: Annotated[Session, Depends(get_session)], lead_id: int | None = Query(None, gt=0),
            limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    filters = [Audit.lead_id == lead_id] if lead_id is not None else []
    total = session.scalar(select(func.count()).select_from(Audit).where(*filters))
    records = session.scalars(select(Audit).where(*filters).order_by(Audit.id.desc()).limit(limit).offset(offset)).all()
    return {'items': [AuditRead.model_validate(audit) for audit in records], 'total': total, 'limit': limit, 'offset': offset}


@router.get('/{audit_id}', response_model=AuditRead)
def read(audit_id: int, worker: Manager):
    return worker.read(audit_id)


@router.post('/{audit_id}/cancel', response_model=AuditRead)
async def cancel(audit_id: int, worker: Manager):
    return await worker.cancel(audit_id)
