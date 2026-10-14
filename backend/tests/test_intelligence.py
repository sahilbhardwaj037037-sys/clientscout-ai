import asyncio
from datetime import timedelta
from types import SimpleNamespace
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.auditing.network import AuditFailure,Fetched
from app.auditing.robots import PoliteFetcher
from app.intelligence.contacts import ContactPage,extract_contacts,role_email
from app.intelligence.identity import verify_identity
from app.intelligence.enrichment import enrich,BudgetFetcher
from app.intelligence.manager import EnrichmentManager
from app.intelligence.ai_manager import AIManager
from app.intelligence.scoring import assess,classify
from app.intelligence.drafts import compose,validate_selection
from app.intelligence.targets import ensure_identity
from app.models.intelligence import Enrichment,Assessment,AIUsage,OutreachDraft,BusinessIdentity,ContactMethod
from app.models.lead import Lead,now
from app.schemas.intelligence import Target,EnrichCreate,AISelection
from app.providers.gemini import select_context,GeminiFailure
from app.providers.wikidata import directory_contacts

URL='https://example.com/'
HTML=b'''<html><title>Fixture Cafe</title><script type="application/ld+json">{"@type":"Restaurant","name":"Fixture Cafe","email":"info@example.com","telephone":"+44 1234 567890","sameAs":["https://www.instagram.com/fixturecafe/"]}</script><body><p>We are a small independent business.</p><a href="mailto:john.smith@example.com">Staff email</a><a href="/contact">Contact</a></body></html>'''
CONTACT=b'<title>Contact</title><form action="/contact/send"></form><a href="mailto:hello@example.com">Business contact</a>'
class Fetcher:
    def __init__(self,pages):self.pages=pages;self.calls=[]
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def get(self,url,**kw):
        self.calls.append(url);status,body,headers=self.pages.get(url,(404,b'',{}));return Fetched(url,status,headers,body,1,now().isoformat(),[])
def snapshot():return {'name':'Fixture Cafe','website_url':URL,'category':'cafe','location':'London','source_url':URL,'source_kind':'user_supplied'}
async def progress(_):pass
async def fixture_runner(data,url,official,directory,p):
    async def no_sleep(_):pass
    return await enrich(data,url,official,directory,p,lambda:Fetcher({URL:(200,HTML,{'content-type':'text/html'}),'https://example.com/contact':(200,CONTACT,{'content-type':'text/html'})}))
def create_identity(database):
    with Session(database) as s:
        lead=Lead(business_name='Fixture Cafe',website_url=URL,normalized_key='example.com',source='manual',original_url=URL,category='cafe',location='London',notes='PRIVATE NOTE NOT FOR AI');s.add(lead);s.flush();identity=ensure_identity(s,Target(target_type='lead',target_id=lead.id));s.commit();return lead.id,identity.id
async def enriched(database,monkeypatch):
    async def no_sleep(_):pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep',no_sleep)
    lead_id,_=create_identity(database);manager=EnrichmentManager(database,fixture_runner);job=await manager.start(EnrichCreate(target_type='lead',target_id=lead_id,permission_confirmed=True,official_confirmed=True));await asyncio.gather(*list(manager.tasks.values()));return lead_id,job['identity_id'],job['id']

@pytest.mark.parametrize('raw',['john.smith@example.com','first.last@gmail.com','info@localhost','info@example.com\nBcc:other@example.com','info@bad..example.com'])
def test_personal_or_invalid_emails_are_not_collected(raw):assert role_email(raw,'Fixture Cafe') is None

def test_public_business_contacts_forms_social_links_provenance_and_no_guessing():
    page=ContactPage();page.feed(HTML.decode());methods=extract_contacts(page,URL,'Fixture Cafe')
    assert any(c['value']=='info@example.com' for c in methods) and not any('john.smith' in c['value'] for c in methods)
    assert any(c['kind']=='instagram' for c in methods) and any(c['kind']=='contact_page' for c in methods)
    contact=ContactPage();contact.feed(CONTACT.decode());assert any(c['kind']=='contact_form' for c in extract_contacts(contact,URL+'contact','Fixture Cafe'))
    unsafe=ContactPage();unsafe.feed('<footer><a href="javascript:alert(1)">Facebook</a><a href="https://www.linkedin.com/in/person">LinkedIn</a></footer><a href="tel:+441234567890">Call John</a>')
    assert extract_contacts(unsafe,URL,'Fixture Cafe')==[]

def test_name_address_coordinates_and_domain_mismatches_need_review():
    page=ContactPage();page.feed(HTML.decode());verified,_=verify_identity(snapshot(),page,URL,True);assert verified['status']=='matched' and verified['official']
    unknown,_=verify_identity(snapshot(),page,URL,False);assert unknown['status']=='needs_review' and not unknown['official']
    page.organizations=[{'name':'Other Business'}];assert verify_identity(snapshot(),page,URL,True)[0]['status']=='mismatch'
    page.organizations=[{'name':'Fixture Cafe','geo':{'latitude':40,'longitude':-70}}];data=dict(snapshot(),latitude=51.5,longitude=0);assert verify_identity(data,page,URL,True)[0]['status']=='mismatch'
    assert verify_identity(snapshot(),page,'https://different.example/',True)[0]['status']=='mismatch'

@pytest.mark.anyio
async def test_bounded_permitted_sources_missing_data_and_source_identity(monkeypatch):
    async def no_sleep(_):pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep',no_sleep)
    fetcher=Fetcher({URL:(200,HTML,{'content-type':'text/html'}),URL+'contact':(200,CONTACT,{'content-type':'text/html'})})
    status,report,error=await enrich(snapshot(),URL,True,False,progress,lambda:fetcher)
    assert status=='complete' and error is None and len(report['pages'])==2 and len(fetcher.calls)==3
    assert all('instagram' not in u for u in fetcher.calls)
    assert any(c['kind']=='email' and c['status']=='official_verified' and c['source_url']==URL for c in report['contacts'])
    assert any(c['kind']=='linkedin' and c['status']=='not_found' for c in report['contacts'])
    bad=Fetcher({URL:(200,HTML.replace(b'Fixture Cafe',b'Wrong Business'),{'content-type':'text/html'})})
    status,report,error=await enrich(snapshot(),URL,True,False,progress,lambda:bad)
    assert report['identity']['status']=='mismatch' and not any(c['value'] for c in report['contacts']) and report['website_report'] is None

@pytest.mark.anyio
async def test_robots_denial_unsafe_cross_host_redirect_and_request_budget(monkeypatch):
    async def no_sleep(_):pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep',no_sleep)
    robots=Fetcher({URL+'robots.txt':(200,b'User-agent: *\nDisallow: /',{})})
    status,report,error=await enrich(snapshot(),URL,True,False,progress,lambda:robots)
    assert status=='blocked' and robots.calls==[URL+'robots.txt'] and all(c['status']=='source_inaccessible' for c in report['contacts'])
    redirected=Fetcher({URL:(302,b'',{'location':'https://other.example/'})})
    with pytest.raises(AuditFailure,match='Cross-domain'):await PoliteFetcher(redirected,allowed_hosts={'example.com'}).page(URL)
    assert 'https://other.example/' not in redirected.calls
    bounded=BudgetFetcher(Fetcher({}))
    for _ in range(8):await bounded.get(URL)
    with pytest.raises(AuditFailure,match='Eight-request'):await bounded.get(URL)

@pytest.mark.anyio
async def test_contact_persistence_cache_cooldown_and_stale_name_research(database,monkeypatch):
    lead_id,identity_id,job_id=await enriched(database,monkeypatch)
    manager=EnrichmentManager(database,fixture_runner);reused=await manager.start(EnrichCreate(target_type='lead',target_id=lead_id,permission_confirmed=True,official_confirmed=True));assert reused['id']==job_id and reused['reused']
    with pytest.raises(HTTPException) as cooldown:await manager.start(EnrichCreate(target_type='lead',target_id=lead_id,permission_confirmed=True,official_confirmed=True,refresh=True))
    assert cooldown.value.status_code==429
    with Session(database) as s:
        assert s.scalar(select(func.count()).select_from(ContactMethod))>0
        identity=s.get(BusinessIdentity,identity_id);a=assess(s,identity);s.commit();assert a.qualification=='qualified' and a.segment=='independent_small' and a.score>0
        old_score=a.score;b=assess(s,identity);s.commit();assert b.score==old_score and b.report==a.report
        lead=s.get(Lead,lead_id);lead.business_name='Different Business';s.commit();identity=ensure_identity(s,Target(target_type='lead',target_id=lead_id));fresh=assess(s,identity);assert fresh.score is None and fresh.qualification=='needs_research'

@pytest.mark.anyio
async def test_enrichment_cancel_recovery_and_daily_budget(database):
    lead_id,_=create_identity(database)
    async def slow(*args):await asyncio.sleep(100)
    manager=EnrichmentManager(database,slow);job=await manager.start(EnrichCreate(target_type='lead',target_id=lead_id,permission_confirmed=True));await asyncio.sleep(0)
    assert (await manager.cancel(job['id']))['status']=='cancelled'
    with Session(database) as s:
        row=s.get(Enrichment,job['id']);row.status='running';s.commit()
    manager.recover();assert manager.read(job['id'])['status']=='interrupted'


def test_major_chain_association_and_unknown_size_are_evidence_limited():
    major,reason=classify({'name':'Starbucks','website_url':'https://www.starbucks.com/'},None);assert major=='major_chain' and 'ownership' in reason['reason']
    assert classify({'name':'Small sounding Cafe','website_url':URL},None)[0]=='unknown'
    assert classify(snapshot(),{'business_statements':[{'text':'We are an independent business','source_url':URL,'observed_at':now().isoformat()}]})[0]=='independent_size_unknown'

@pytest.mark.anyio
async def test_local_drafts_are_fact_bound_editable_and_cascade_with_business(database,monkeypatch):
    lead_id,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:
        a=assess(s,s.get(BusinessIdentity,identity_id));s.commit()
        for channel in ['email','whatsapp','contact_form','linkedin_dm','instagram_dm']:
            draft=compose(a,channel);assert 'Fixture Cafe' in draft.body and 'PRIVATE NOTE' not in draft.body and 'conversion' not in draft.body;s.add(draft)
        s.commit();assert s.scalar(select(func.count()).select_from(OutreachDraft))==5
        bad={'opening':'direct','finding_ids':['invented_weakness'],'service_ids':['frontend'],'closing':'chat'}
        with pytest.raises(ValueError):validate_selection(bad,a)
        with pytest.raises(ValueError):validate_selection(dict(bad,score=100),a)
        s.delete(s.get(Lead,lead_id));s.commit();assert s.scalar(select(func.count()).select_from(OutreachDraft))==0

@pytest.mark.anyio
async def test_official_sdk_structured_selection_boundaries_and_key_redaction(database,monkeypatch):
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();s.refresh(a);s.expunge(a)
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_PRIVATE_KEY')
    requests=[]
    class Models:
        async def generate_content(self,**kwargs):requests.append(kwargs);return SimpleNamespace(text=json.dumps({'opening':'direct','finding_ids':[],'service_ids':['frontend'],'closing':'outline'}),usage_metadata=SimpleNamespace(prompt_token_count=123,candidates_token_count=12))
    class Client:
        def __init__(self,**kwargs):requests.append(kwargs);self.aio=SimpleNamespace(models=Models(),aclose=self.close)
        async def close(self):pass
    selection,usage=await select_context(a,Client);assert usage=={'input_tokens':123,'output_tokens':12}
    assert requests[0]['http_options'].retry_options.attempts==1 and requests[0]['http_options'].async_client_args['trust_env'] is False
    assert 'PRIVATE NOTE' not in requests[1]['contents'] and 'info@example.com' not in requests[1]['contents']
    assert requests[1]['config'].automatic_function_calling.disable is True and requests[1]['config'].response_json_schema
    class BadModels:
        async def generate_content(self,**kwargs):raise type('ProviderError',(Exception,),{'code':429})('TEST_PRIVATE_KEY provider body')
    class Bad(Client):
        def __init__(self,**kwargs):super().__init__(**kwargs);self.aio.models=BadModels()
    with pytest.raises(GeminiFailure) as error:await select_context(a,Bad)
    assert error.value.code==429 and 'TEST_PRIVATE_KEY' not in str(error.value)

@pytest.mark.anyio
async def test_ai_quota_usage_no_paid_model_fallback_and_core_scoring(database,monkeypatch):
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=a.id
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    calls=[]
    async def quota(a):calls.append(a.id);raise GeminiFailure(429,'Quota exhausted; no substitute.')
    manager=AIManager(database,quota);job=await manager.start(aid,'draft','email');await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(job['id'])['status']=='error' and calls==[aid]
    with pytest.raises(HTTPException):await manager.start(aid,'draft','email')
    with Session(database) as s:assert s.scalar(select(func.count()).select_from(OutreachDraft))==0 and s.get(Assessment,aid).score is not None

@pytest.mark.anyio
async def test_ai_success_saves_actual_selection_and_tokens(database,monkeypatch):
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=a.id
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    async def provider(a):return AISelection(opening='brief',finding_ids=[a.report['evidence'][0]['id']],service_ids=['frontend'],closing='permission'),{'input_tokens':40,'output_tokens':20}
    manager=AIManager(database,provider);job=await manager.start(aid,'draft','whatsapp');await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(job['id'])['status']=='complete' and manager.read(job['id'])['result']['draft_id']
    with Session(database) as s:assert s.get(AIUsage,job['id']).input_tokens==40 and s.scalar(select(OutreachDraft)).generator=='gemini'


def test_api_permissions_missing_key_source_lookup_and_unknowns(client):
    lead=client.post('/api/leads',json={'website_url':URL,'business_name':'Fixture Cafe'}).json();identifier=lead['id']
    assert client.get(f'/api/intelligence/targets/lead/{identifier}').json()['assessment'] is None
    assert client.get('/api/intelligence/targets').json()['total']==1
    payload={'target_type':'lead','target_id':identifier,'permission_confirmed':False}
    assert client.post('/api/intelligence/enrichments',json=payload).status_code==422
    payload['permission_confirmed']=True;payload['website_url']='http://127.0.0.1/'
    assert client.post('/api/intelligence/enrichments',json=payload).status_code==422
    assert client.post('/api/intelligence/assessments',json={'target_type':'lead','target_id':identifier},headers={'Origin':'https://evil.example'}).status_code==403
    a=client.post('/api/intelligence/assessments',json={'target_type':'lead','target_id':identifier}).json();assert a['score'] is None and a['qualification']=='needs_research'
    assert client.post(f"/api/intelligence/assessments/{a['id']}/ai",json={'public_data_consent':True}).status_code==503
    assert client.post('/api/intelligence/drafts',json={'assessment_id':a['id'],'review_confirmed':True}).status_code==422
    assert client.get('/api/intelligence/assessments?min_score=101').status_code==422
    assert client.get('/api/intelligence/assessments?segment=madeup').status_code==422

@pytest.mark.anyio
async def test_changed_business_cannot_use_old_qualified_assessment(client,database,monkeypatch):
    lead_id,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:
        assessment=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=assessment.id
    assert client.patch(f'/api/leads/{lead_id}',json={'business_name':'Another Business'}).status_code==200
    result=client.post('/api/intelligence/drafts',json={'assessment_id':aid,'review_confirmed':True})
    assert result.status_code==422
    assert client.get('/api/intelligence/drafts').json()['total']==0

@pytest.mark.anyio
async def test_refreshing_assessment_cannot_extend_expired_source_evidence(client,database,monkeypatch):
    _,identity_id,job_id=await enriched(database,monkeypatch)
    with Session(database) as s:
        assessment=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=assessment.id
        job=s.get(Enrichment,job_id);job.created_at=now()-timedelta(hours=25);s.commit()
    assert client.post('/api/intelligence/drafts',json={'assessment_id':aid,'review_confirmed':True}).status_code==422

@pytest.mark.anyio
async def test_non_html_jsonld_graph_cannot_crash_contact_extraction(monkeypatch):
    async def no_sleep(_):pass
    monkeypatch.setattr('app.auditing.robots.asyncio.sleep',no_sleep)
    body=HTML+b'<script type="application/ld+json">{"@graph": {"bad":"shape"}}</script>'
    status,report,error=await enrich(snapshot(),URL,True,False,progress,lambda:Fetcher({URL:(200,body,{'content-type':'text/html'}),URL+'contact':(200,CONTACT,{'content-type':'text/html'})}))
    assert status=='complete' and error is None
    assert report['identity']['status']=='matched'

@pytest.mark.anyio
async def test_directory_entity_identity_and_personal_data_exclusion():
    data=dict(snapshot(),business_tags={'wikidata':'Q123'})
    entity={'labels':{'en':{'value':'Fixture Cafe'}},'claims':{'P31':[{'mainsnak':{'datavalue':{'value':{'id':'Q4830453'}}}}],'P968':[{'mainsnak':{'datavalue':{'value':'info@example.com'}}},{'mainsnak':{'datavalue':{'value':'john.smith@example.com'}}}],'P856':[{'mainsnak':{'datavalue':{'value':'http://127.0.0.1/'}}}]}}
    url='https://www.wikidata.org/wiki/Special:EntityData/Q123.json'
    fetcher=Fetcher({url:(200,json.dumps({'entities':{'Q123':entity}}).encode(),{})})
    contacts,_=await directory_contacts(fetcher,data)
    assert len(contacts)==1 and contacts[0]['value']=='info@example.com' and contacts[0]['licence']=='CC0' and contacts[0]['status']=='needs_review'
    entity['claims']['P31'][0]['mainsnak']['datavalue']['value']['id']='Q5'
    fetcher.pages[url]=(200,json.dumps({'entities':{'Q123':entity}}).encode(),{})
    assert (await directory_contacts(fetcher,data))[0]==[]
    entity['claims']['P31'][0]['mainsnak']['datavalue']['value']['id']='Q4830453'
    entity['labels']['en']['value']='Other Branch'
    fetcher.pages[url]=(200,json.dumps({'entities':{'Q123':entity}}).encode(),{})
    assert (await directory_contacts(fetcher,data))[0]==[]

@pytest.mark.anyio
async def test_enrichment_daily_budget(database):
    lead_id,identity_id=create_identity(database)
    with Session(database) as s:
        for i in range(10):s.add(Enrichment(identity_id=identity_id,status='cancelled',created_at=now()-timedelta(minutes=i+1),next_allowed_at=now()-timedelta(minutes=1)))
        s.commit()
    with pytest.raises(HTTPException,match='10 enrichment'):await EnrichmentManager(database,fixture_runner).start(EnrichCreate(target_type='lead',target_id=lead_id,permission_confirmed=True))

@pytest.mark.anyio
async def test_ai_rejects_business_change_during_provider_request(database,monkeypatch):
    lead_id,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=a.id
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    async def provider(a):
        with Session(database) as s:
            s.get(Lead,lead_id).business_name='Changed during request';s.commit()
        return AISelection(opening='direct',finding_ids=[],service_ids=['frontend'],closing='chat'),{'input_tokens':40,'output_tokens':20}
    manager=AIManager(database,provider);job=await manager.start(aid,'draft','email');await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(job['id'])['status']=='error'
    with Session(database) as s:assert s.scalar(select(func.count()).select_from(OutreachDraft))==0

@pytest.mark.anyio
async def test_ai_one_retry_is_counted_against_daily_budget(database,monkeypatch):
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=a.id
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_DAILY_LIMIT',1)
    async def no_sleep(_):pass
    monkeypatch.setattr('app.intelligence.ai_manager.asyncio.sleep',no_sleep)
    calls=[]
    async def failure(a):calls.append(a.id);raise GeminiFailure(503,'Provider temporarily unavailable.')
    manager=AIManager(database,failure);job=await manager.start(aid,'draft','email');await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(job['id'])['status']=='error' and len(calls)==1
    with Session(database) as s:assert s.scalar(select(func.count()).select_from(AIUsage))==1
