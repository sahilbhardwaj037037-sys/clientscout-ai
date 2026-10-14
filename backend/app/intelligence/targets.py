from fastapi import HTTPException
from sqlalchemy import select
from app.models.lead import Lead
from app.models.discovery import DiscoveredBusiness
from app.models.intelligence import BusinessIdentity

def business_snapshot(record):
    if isinstance(record,Lead):
        return {'name':record.business_name,'website_url':record.website_url,'category':record.category,'location':record.location,'source_url':record.website_url,'source_kind':'user_supplied'}
    return record.data

def ensure_identity(session,target):
    column=BusinessIdentity.lead_id if target.target_type=='lead' else BusinessIdentity.discovered_business_id
    record=session.get(Lead if target.target_type=='lead' else DiscoveredBusiness,target.target_id)
    if record is None:raise HTTPException(404,'Selected business not found.')
    snapshot=business_snapshot(record)
    identity=session.scalar(select(BusinessIdentity).where(column==target.target_id))
    if identity is None:
        identity=BusinessIdentity(snapshot=snapshot,lead_id=record.id if target.target_type=='lead' else None,discovered_business_id=record.id if target.target_type=='discovery' else None);session.add(identity);session.flush()
    else:identity.snapshot=snapshot
    return identity
