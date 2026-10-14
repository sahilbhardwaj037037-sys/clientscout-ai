"""Fail closed when a qualified snapshot no longer describes current source evidence."""
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from app.discovery.manager import utc
from app.intelligence.targets import business_snapshot
from app.models.intelligence import BusinessIdentity, Enrichment
from app.models.lead import Lead, now
from app.models.discovery import DiscoveredBusiness

def assessment_current(session, assessment):
    cutoff=now()-timedelta(hours=24)
    if assessment.qualification!='qualified' or utc(assessment.created_at)<cutoff:
        return False
    identity=session.get(BusinessIdentity,assessment.identity_id)
    if identity is None:return False
    record=session.get(Lead,identity.lead_id) if identity.lead_id else session.get(DiscoveredBusiness,identity.discovered_business_id)
    if record is None or business_snapshot(record)!=assessment.report.get('business'):return False
    latest=session.scalar(select(Enrichment).where(Enrichment.identity_id==identity.id).order_by(Enrichment.id.desc()))
    return bool(latest and latest.id==assessment.enrichment_id and utc(latest.created_at)>=cutoff and latest.status in {'complete','partial'} and latest.report and latest.report.get('business_snapshot')==assessment.report['business'] and latest.report.get('identity',{}).get('official') and latest.report['identity'].get('status')=='matched')

def require_current(session, assessment):
    if not assessment_current(session,assessment):
        raise HTTPException(422,'Business or source evidence changed/expired. Refresh source verification and assessment before generating a draft or Gemini context.')
