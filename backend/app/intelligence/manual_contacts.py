"""Explicit local public-business observations, never automated verification."""
from fastapi import HTTPException
from sqlalchemy import select
from app.models.intelligence import Enrichment,ContactMethod
from app.models.lead import now
from app.intelligence.contacts import role_email
from app.services.urls import normalize_url

SOURCE_KIND='manual_public_observation'


def serialize_manual(row):
    p=row.provenance
    return {'id':row.id,'kind':'email','value':row.value,'status':'needs_review','source_kind':SOURCE_KIND,
            'source_url':p['source_url'],'reported_at':p['reported_at'],'domain_association':p['domain_association'],
            'evidence':'User-reported public business-role email. No automated extraction, domain ownership or mailbox verification.'}


def list_manual(session,identity_id):
    if not identity_id:return []
    rows=session.scalars(select(ContactMethod).join(Enrichment).where(Enrichment.identity_id==identity_id,
        ContactMethod.provenance['source_kind'].as_string()==SOURCE_KIND).order_by(ContactMethod.id.desc()).limit(10)).all()
    return [serialize_manual(row) for row in rows]


def add_manual(session,identity,payload):
    # A same-host source page can be associated with the previously checked
    # website. That does NOT verify a user-reported address or a different domain.
    latest=session.scalar(select(Enrichment).where(Enrichment.identity_id==identity.id,
        Enrichment.status.in_(['complete','partial'])).order_by(Enrichment.id.desc()))
    report=latest.report if latest else None
    if not report or report.get('business_snapshot')!=identity.snapshot or not report.get('identity',{}).get('official') or report['identity'].get('status')!='matched':
        raise HTTPException(422,'A previously matched official website source is required for source attribution.')
    source_host=normalize_url(payload.source_url)[1]
    official_url=latest.requested_url or identity.snapshot.get('website_url')
    if not official_url or source_host!=normalize_url(official_url)[1]:
        raise HTTPException(422,'Use a public page on the checked official website as the source. Other email domains remain unconfirmed.')
    value=role_email(payload.email,identity.snapshot.get('name') or '')
    if not value or value!=payload.email.lower():raise HTTPException(422,'Enter an explicitly observed plain business-role address. Personal staff addresses, links and headers are excluded.')
    existing=session.scalar(select(ContactMethod).where(ContactMethod.enrichment_id==latest.id,ContactMethod.kind=='email',ContactMethod.value==value))
    if existing:
        if existing.provenance.get('source_kind')==SOURCE_KIND and existing.provenance.get('source_url')==payload.source_url:return existing
        raise HTTPException(409,'This address already has contact evidence; its provenance was preserved.')
    if len(list_manual(session,identity.id))>=10:raise HTTPException(422,'Ten manual observations are already recorded for this business.')
    email_host=value.rsplit('@',1)[1]
    association='matches_website_domain' if email_host==source_host else 'different_domain_unverified'
    row=ContactMethod(enrichment_id=latest.id,kind='email',value=value,status='needs_review',provenance={
        'source_kind':SOURCE_KIND,'source_url':payload.source_url,'reported_at':now().isoformat(),
        'domain_association':association,'public_business_observed':True,'fetched_at':None})
    session.add(row);session.flush();return row
