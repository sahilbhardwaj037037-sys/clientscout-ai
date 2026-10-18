from typing import Annotated,Literal
from fastapi import APIRouter,Depends,HTTPException,Query,Request
from sqlalchemy import func,select,literal,union_all
from sqlalchemy.orm import Session
from app.database.session import get_session
from app.core.settings import GEMINI_API_KEY,GEMINI_MODEL,GEMINI_DAILY_LIMIT
from app.models.lead import Lead
from app.models.discovery import DiscoveredBusiness
from app.models.intelligence import BusinessIdentity,Enrichment,Assessment,OutreachDraft,AIUsage
from app.schemas.intelligence import Target,EnrichCreate,AIRequest,DraftCreate,DraftEdit,DraftReview,FreelancerProfile,ManualBusinessEmail
from app.intelligence.profile import read_profile,save_profile
from app.intelligence.human_writer import is_human_draft,hard_check,content_hash,review_metadata
from app.intelligence.writer import WritingValidationError
from app.intelligence.targets import ensure_identity,business_snapshot
from app.intelligence.manual_contacts import list_manual,add_manual,serialize_manual
from app.intelligence.freshness import require_current
from app.intelligence.scoring import assess,SKILLS
from app.intelligence.drafts import compose
from app.discovery.manager import utc

router=APIRouter(prefix='/api/intelligence')
DB=Annotated[Session,Depends(get_session)]
def serialize(row):return {k:(utc(v).isoformat() if hasattr(v,'tzinfo') else v) for k,v in row.__dict__.items() if not k.startswith('_')}
def escaped(value):return value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')

@router.get('/config')
def config():return {'gemini_configured':bool(GEMINI_API_KEY),'gemini_model':GEMINI_MODEL,'gemini_daily_limit':GEMINI_DAILY_LIMIT,'skills':SKILLS,'max_pages':3,'max_requests':8,'enrichment_daily_limit':10,'cache_hours':24,'sources':['Saved OSM business tags (ODbL)','Permitted business website/contact/about pages','Optional Wikidata business entity (CC0)','Public business social links only; profiles are not fetched']}

@router.get('/freelancer-profile')
def freelancer_profile(s:DB):return read_profile(s.get_bind())
@router.patch('/freelancer-profile')
def update_freelancer_profile(payload:FreelancerProfile,s:DB):return save_profile(s.get_bind(),payload)

@router.get('/targets')
def targets(s:DB,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),q:str=Query('',max_length=100)):
    combined=union_all(select(Lead.id.label('target_id'),literal('lead').label('target_type'),Lead.business_name.label('name'),Lead.website_url.label('website_url'),Lead.category.label('category')),select(DiscoveredBusiness.id,literal('discovery'),DiscoveredBusiness.data['name'].as_string(),DiscoveredBusiness.data['website_url'].as_string(),DiscoveredBusiness.data['category'].as_string())).subquery()
    statement=select(combined)
    if q:statement=statement.where(func.lower(combined.c.name).like('%'+escaped(q.lower())+'%',escape='\\'))
    total=s.scalar(select(func.count()).select_from(statement.subquery()));items=s.execute(statement.order_by(combined.c.target_type,combined.c.target_id).limit(limit).offset(offset)).mappings().all()
    return {'items':[dict(i) for i in items],'total':total,'limit':limit,'offset':offset}

@router.get('/targets/{target_type}/{target_id}')
def target_state(target_type:Literal['lead','discovery'],target_id:int,s:DB):
    record=s.get(Lead if target_type=='lead' else DiscoveredBusiness,target_id)
    if not record:raise HTTPException(404,'Business not found.')
    snapshot={'name':record.business_name,'website_url':record.website_url,'category':record.category,'location':record.location,'source_url':record.website_url,'source_kind':'user_supplied'} if target_type=='lead' else record.data
    column=BusinessIdentity.lead_id if target_type=='lead' else BusinessIdentity.discovered_business_id
    identity=s.scalar(select(BusinessIdentity).where(column==target_id))
    job=s.scalar(select(Enrichment).where(Enrichment.identity_id==identity.id).order_by(Enrichment.id.desc())) if identity else None
    assessment=s.scalar(select(Assessment).where(Assessment.identity_id==identity.id).order_by(Assessment.id.desc())) if identity else None
    return {'business':snapshot,'identity_id':identity.id if identity else None,'manual_contacts':list_manual(s,identity.id if identity else None),'enrichment':serialize(job) if job else None,'assessment':serialize(assessment) if assessment and assessment.report.get('business')==snapshot else None}

@router.post('/targets/{target_type}/{target_id}/manual-email',status_code=201)
def manual_email(target_type:Literal['lead','discovery'],target_id:int,payload:ManualBusinessEmail,s:DB):
    record=s.get(Lead if target_type=='lead' else DiscoveredBusiness,target_id)
    if not record:raise HTTPException(404,'Business not found.')
    column=BusinessIdentity.lead_id if target_type=='lead' else BusinessIdentity.discovered_business_id
    identity=s.scalar(select(BusinessIdentity).where(column==target_id))
    if not identity or business_snapshot(record)!=identity.snapshot:
        raise HTTPException(422,'Business source changed or has not been checked. Review its official website first.')
    row=add_manual(s,identity,payload);s.commit();s.refresh(row);return serialize_manual(row)

@router.post('/enrichments',status_code=202)
async def start(payload:EnrichCreate,request:Request):return await request.app.state.enrichment_manager.start(payload)
@router.get('/enrichments/{identifier}')
def read(identifier:int,request:Request):return request.app.state.enrichment_manager.read(identifier)
@router.post('/enrichments/{identifier}/cancel')
async def cancel(identifier:int,request:Request):return await request.app.state.enrichment_manager.cancel(identifier)

@router.post('/assessments',status_code=201)
def create_assessment(payload:Target,s:DB):
    identity=ensure_identity(s,payload);result=assess(s,identity);s.commit();s.refresh(result);return serialize(result)
@router.get('/assessments/{identifier}')
def read_assessment(identifier:int,s:DB):
    row=s.get(Assessment,identifier)
    if not row:raise HTTPException(404,'Assessment not found.')
    return serialize(row)
@router.get('/assessments')
def assessments(s:DB,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),include_major_chains:bool=False,min_score:int=Query(0,ge=0,le=100),segment:str=Query('',max_length=50),category:str=Query('',max_length=100),website_opportunity:str=Query('',max_length=70),contact_available:Literal['any','yes','no']='any'):
    latest=select(func.max(Assessment.id)).group_by(Assessment.identity_id)
    statement=select(Assessment).join(BusinessIdentity).where(Assessment.id.in_(latest))
    if not include_major_chains:statement=statement.where(Assessment.segment!='major_chain')
    if min_score:statement=statement.where(Assessment.score>=min_score)
    if segment:
        if segment not in {'unknown','independent_small','independent_growing','independent_established','independent_size_unknown','regional_chain','major_chain'}:raise HTTPException(422,'Unknown business segment.')
        statement=statement.where(Assessment.segment==segment)
    if category:statement=statement.where(func.lower(BusinessIdentity.snapshot['category'].as_string()).like('%'+escaped(category.lower())+'%',escape='\\'))
    if website_opportunity:
        if website_opportunity not in {'verified_technical_opportunities','technical_observations_identity_unverified','verified_official','supplied_unverified','no_usable_source_tag','inaccessible','identity_needs_review','official_not_found_bounded','website_candidate_needs_review'}:raise HTTPException(422,'Unknown website opportunity status.')
        statement=statement.where(Assessment.website_status==website_opportunity)
    if contact_available!='any':statement=statement.where(Assessment.report['contact_available'].as_boolean()==(contact_available=='yes'))
    total=s.scalar(select(func.count()).select_from(statement.subquery()));rows=s.scalars(statement.order_by(Assessment.score.desc(),Assessment.id.desc()).limit(limit).offset(offset)).all()
    return {'items':[dict(serialize(r),target_type='lead' if s.get(BusinessIdentity,r.identity_id).lead_id else 'discovery',target_id=s.get(BusinessIdentity,r.identity_id).lead_id or s.get(BusinessIdentity,r.identity_id).discovered_business_id) for r in rows],'total':total,'limit':limit,'offset':offset}

@router.post('/assessments/{identifier}/ai',status_code=202)
async def explanation(identifier:int,payload:AIRequest,request:Request):return await request.app.state.ai_manager.start(identifier,'explanation')
@router.get('/ai/{identifier}')
def ai_read(identifier:int,request:Request):return request.app.state.ai_manager.read(identifier)
@router.get('/usage')
def usage(s:DB):
    from datetime import timedelta
    from app.models.lead import now
    rows=s.scalars(select(AIUsage).where(AIUsage.created_at>=now()-timedelta(hours=24))).all()
    return {'requests':len(rows),'daily_limit':GEMINI_DAILY_LIMIT,'input_tokens':sum(r.input_tokens or 0 for r in rows),'output_tokens':sum(r.output_tokens or 0 for r in rows),'token_measurements_available':any(r.input_tokens is not None or r.output_tokens is not None for r in rows),'recent':[serialize(r) for r in rows[-10:]]}

@router.post('/drafts',status_code=201)
async def generate(payload:DraftCreate,request:Request,s:DB):
    assessment=s.get(Assessment,payload.assessment_id)
    if not assessment:raise HTTPException(404,'Assessment not found.')
    require_current(s,assessment)
    if payload.generator=='gemini':
        if not payload.public_data_consent:raise HTTPException(422,'Confirm sending the bounded public evidence to Gemini first.')
        assessment_id=assessment.id
        # Release the request reader before the manager commits on another connection.
        # The manager revalidates current evidence in its own transaction.
        s.close()
        return await request.app.state.ai_manager.start(assessment_id,'draft',payload.channel,payload.include_profile)
    draft=compose(assessment,payload.channel);s.add(draft);s.commit();s.refresh(draft);return serialize(draft)
@router.get('/drafts')
def drafts(s:DB,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),saved:bool=True,assessment_id:int|None=Query(None,ge=1)):
    if not saved and assessment_id is None:raise HTTPException(422,'Select an assessment to list unsaved drafts.')
    statement=select(OutreachDraft).where(OutreachDraft.saved.is_(saved))
    if assessment_id is not None:
        if not s.get(Assessment,assessment_id):raise HTTPException(404,'Assessment not found.')
        statement=statement.where(OutreachDraft.assessment_id==assessment_id)
    total=s.scalar(select(func.count()).select_from(statement.subquery()))
    return {'items':[serialize(r) for r in s.scalars(statement.order_by(OutreachDraft.id.desc()).limit(limit).offset(offset)).all()],'total':total,'limit':limit,'offset':offset}
@router.get('/drafts/{identifier}')
def draft_read(identifier:int,s:DB):
    row=s.get(OutreachDraft,identifier)
    if not row:raise HTTPException(404,'Draft not found.')
    return serialize(row)
@router.patch('/drafts/{identifier}')
def edit(identifier:int,payload:DraftEdit,s:DB):
    row=s.get(OutreachDraft,identifier)
    if not row:raise HTTPException(404,'Draft not found.')
    if is_human_draft(row):
        try:
            authorization=dict(row.evidence['authorization'])
            profile=read_profile(s.get_bind())
            if profile.public_details_confirmed:authorization['freelancer_name']=profile.display_name
            hard_check(payload.subject,payload.body,authorization,channel=row.channel)
        except WritingValidationError as error:raise HTTPException(422,str(error)) from None
        row.evidence={**row.evidence,'authorization':authorization}
        if row.subject!=payload.subject or row.body!=payload.body:
            row.evidence={**row.evidence,'review':review_metadata(payload.subject,payload.body)}
        # No old-text recovery copies are created on edit.
        s.connection().exec_driver_sql('PRAGMA secure_delete=ON')
    row.body=payload.body;row.subject=payload.subject;row.saved=payload.saved;row.edited=True;s.commit();s.refresh(row);return serialize(row)

@router.post('/drafts/{identifier}/review')
def review_draft(identifier:int,payload:DraftReview,s:DB):
    row=s.get(OutreachDraft,identifier)
    if not row:raise HTTPException(404,'Draft not found.')
    if not is_human_draft(row):raise HTTPException(409,'This review workflow applies only to Human-Reviewed AI Writer drafts.')
    if not row.saved:raise HTTPException(409,'Save the draft before acknowledging review.')
    if not payload.acknowledged:raise HTTPException(422,'Explicit review acknowledgement is required.')
    if payload.content_hash!=content_hash(row.subject,row.body):raise HTTPException(409,'Draft changed. Reload and review the current text.')
    try:hard_check(row.subject,row.body,row.evidence['authorization'],channel=row.channel)
    except WritingValidationError as error:raise HTTPException(422,str(error)) from None
    from app.models.lead import now
    row.evidence={**row.evidence,'review':{'state':'ready','factual_status':'unverified','content_hash':payload.content_hash,'acknowledged_at':now().isoformat()}}
    s.commit();s.refresh(row);return serialize(row)

@router.delete('/drafts/{identifier}/review')
def revoke_review(identifier:int,s:DB):
    row=s.get(OutreachDraft,identifier)
    if not row:raise HTTPException(404,'Draft not found.')
    if not is_human_draft(row):raise HTTPException(409,'Historical draft review metadata is preserved.')
    row.evidence={**row.evidence,'review':review_metadata(row.subject,row.body)}
    s.commit();s.refresh(row);return serialize(row)

@router.delete('/drafts/{identifier}',status_code=204)
def discard_draft(identifier:int,s:DB):
    row=s.get(OutreachDraft,identifier)
    if not row:raise HTTPException(404,'Draft not found.')
    if not is_human_draft(row):raise HTTPException(409,'Historical drafts are preserved. Only Human-Reviewed AI Writer drafts can be discarded here.')
    # Delete the only application-held output copy, including its evidence JSON.
    # Keep content-free usage/attempt rows and remove stale reopening references.
    s.connection().exec_driver_sql('PRAGMA secure_delete=ON')
    for job in s.scalars(select(AIUsage).where(AIUsage.result['draft_id'].as_integer()==identifier)).all():
        job.result={'discarded':True}
    s.delete(row);s.commit()
