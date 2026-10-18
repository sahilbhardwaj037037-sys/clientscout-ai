"""Option A production contract: offline SDK, temporary database, no live calls."""
import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.intelligence.human_writer import (human_context,validate_human,compose_human,HUMAN_VERSION,HUMAN_VERSIONS,content_hash,hard_check)
from app.intelligence.writer import WritingValidationError
from app.intelligence.ai_manager import AIManager
from app.models.intelligence import OutreachDraft,BusinessIdentity,AIUsage,Assessment
from app.intelligence.scoring import assess
from app.providers.gemini import write_proposal,GeminiFailure,HUMAN_GUIDANCE,human_guidance,CHANNEL_GUIDANCE
from app.schemas.intelligence import FreelancerProfile,HumanWrittenDraft
from test_ai_writer import fixture_assessment,sdk
from test_intelligence import enriched
from writer_helpers import confirm_writer

NATURAL={'subject':'A small idea for your online presence',
 'body':"Hello Fixture Cafe team,\n\nIt's good to see an existing home for your business online. The page checked included images without alt attributes; a focused review could help clarify which images need descriptions. I could help refine those details while keeping what you already have. Would a quick conversation be useful?\n\nThanks for your time."}


def ctx(profile=None,channel='email'):
    return human_context(fixture_assessment(),channel,profile or FreelancerProfile(service_ids=['frontend'],public_details_confirmed=True))

@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_PROVIDER_SECRET')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')

@pytest.mark.anyio
@pytest.mark.parametrize('channel',['email','whatsapp','contact_form','linkedin_dm','instagram_dm'])
async def test_natural_subject_body_only_written_by_production_adapter(mocked,channel):
    context=ctx(channel=channel);data={**NATURAL,'subject':NATURAL['subject'] if channel=='email' else ''}
    Client,calls,closed=sdk(data)
    result,tokens=await write_proposal(context,Client)
    assert result.model_dump()==data and tokens=={'input_tokens':50,'output_tokens':100}
    schema=calls[1]['config'].response_json_schema
    assert set(schema['properties'])=={'subject','body'} and schema['additionalProperties'] is False
    assert calls[1]['config'].system_instruction==human_guidance(channel)
    assert 'approved_fact_wordings' not in json.loads(calls[1]['contents'])
    for secret in ('PRIVATE NOTE','personal@example.com','SECRET','raw HTML'):
        assert secret not in calls[1]['contents']
    assert len(calls)==2 and closed==[True]

@pytest.mark.parametrize('sentence',[
    'Have a lovely day.', 'Would next week suit you?', 'There are no guarantees.',
    'I cannot guarantee results.', 'Results cannot be guaranteed.', 'If you want to explore this, feel free to reply.',
    'Could I suggest a review of the visitor experience?',
    # These are NOT accepted as verified facts. Option A retains them solely for
    # human review rather than claiming a semantic verifier proved them true.
    'Your website attracts a million visitors.', 'We spoke at a conference.',
    'Your booking form stops visitors from contacting you.',
])
def test_unfamiliar_prose_and_uncertain_assertions_require_review(sentence):
    context=ctx();data={**NATURAL,'body':NATURAL['body']+' '+sentence}
    result=validate_human(data,context)
    draft=compose_human(SimpleNamespace(id=2,identity_id=1,report=fixture_assessment().report),result,context,'gemini-3.5-flash-lite')
    assert draft.body==data['body'] and draft.evidence['review']['state']=='required'
    assert draft.evidence['review']['factual_status']=='unverified'
    assert 'grounding' not in draft.evidence and 'claims' not in draft.evidence

@pytest.mark.anyio
@pytest.mark.parametrize('addition,rule',[
    (' personal@example.com','contacts_or_markup'), (' +44 1234 567890','contacts_or_markup'),
    (' john (at) example (dot) com','contacts_or_markup'),
    (' TEST_PROVIDER_SECRET','protected_information'), (' API_KEY=PRIVATE_VALUE','protected_information'),
    (' https://invented.example.com/','link_allowlist'), (' invented.xyz','link_allowlist'),
    (' https://portfolio.example.com.evil.com/','link_allowlist'),
    (' https://user@portfolio.example.com/','link_allowlist'),
    (' javascript:alert(1)','contacts_or_markup'), (' <script>private</script>','contacts_or_markup'),
    (' [My name]','contacts_or_markup'), ('\x00PRIVATE','contacts_or_markup'), ('\u202ePRIVATE','contacts_or_markup'),
    (' I guarantee increased sales.','prohibited_claim'), (' I will build a custom redesign.','unapproved_commitment'),
    (" I'll create a new demo.",'unapproved_commitment'),
    (' I can finish within two days.','unapproved_commitment'), (' A free custom demo.','unapproved_commitment'),
    (' I could share a demo.','walkthrough_permission'), (' I offer Shopify updates.','unsupported_service'),
])
async def test_hard_blocks_never_return_text_and_have_static_diagnostics(mocked,addition,rule,capsys,caplog):
    data={**NATURAL,'body':NATURAL['body']+addition};Client,calls,closed=sdk(data)
    with pytest.raises(GeminiFailure) as caught:await write_proposal(ctx(),Client)
    failure=caught.value
    assert failure.diagnostics['rule']==rule and failure.diagnostics['disposition']=='hard_blocked'
    assert all(failure.diagnostics[k]==v for k,v in HUMAN_VERSIONS.items())
    assert failure.usage=={'input_tokens':50,'output_tokens':100}
    assert addition.strip() not in str(failure)+json.dumps(failure.diagnostics)
    assert len(calls)==2 and closed==[True] and capsys.readouterr()==('','') and not caplog.records

@pytest.mark.anyio
@pytest.mark.parametrize('patch',[{'body':None},{'body':'X'*1801},{'subject':'x\ny'},{'claims':[]},{'body':20},{'subject':''}])
async def test_invalid_schema_or_channel_never_becomes_review_draft(mocked,patch):
    Client,_,_=sdk({**NATURAL,**patch})
    with pytest.raises(GeminiFailure) as caught:await write_proposal(ctx(),Client)
    assert caught.value.diagnostics['disposition']=='hard_blocked'


def test_link_and_walkthrough_authorization_with_missing_optional_fields():
    profile=FreelancerProfile(display_name='Sam',service_ids=['frontend'],public_details_confirmed=True,
        portfolio_url='https://portfolio.example.com/',instagram_url='https://www.instagram.com/sample/',
        projects=[{'id':'site','title':'Website','service_ids':['frontend'],'kind':'completed_project'}],allow_walkthrough_offer=True)
    context=ctx(profile)
    data={**NATURAL,'body':NATURAL['body']+' Explore my portfolio: https://portfolio.example.com/. I could share a walkthrough of an existing project.'}
    assert validate_human(data,context).body==data['body']
    with pytest.raises(WritingValidationError):validate_human(data,ctx())
    data={**NATURAL,'body':NATURAL['body']+' https://portfolio.example.com/?tracking=1'}
    with pytest.raises(WritingValidationError):validate_human(data,context)

async def prepare(database,monkeypatch):
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:
        a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=a.id
    confirm_writer(database,monkeypatch)
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    return aid

async def generated(database,monkeypatch,*,body=None):
    aid=await prepare(database,monkeypatch)
    async def fake(context):return HumanWrittenDraft(**{**NATURAL,**({'body':body} if body else {})}),{'input_tokens':12,'output_tokens':30}
    manager=AIManager(database,writer_provider=fake)
    job=await manager.start(aid,'draft','email')
    await asyncio.gather(*list(manager.tasks.values()))
    return manager.read(job['id']),aid

@pytest.mark.anyio
async def test_save_reload_review_edit_and_stale_acknowledgement(client,database,monkeypatch):
    job,aid=await generated(database,monkeypatch);assert job['status']=='complete'
    draft_id=job['result']['draft_id'];path=f'/api/intelligence/drafts/{draft_id}'
    draft=client.get(path).json();assert draft['body']==NATURAL['body'] and not draft['saved']
    assert draft['evidence']['writer_version']==HUMAN_VERSION
    digest=draft['evidence']['review']['content_hash']
    assert client.get(f'/api/intelligence/drafts?assessment_id={aid}&saved=false').json()['items'][0]['id']==draft_id
    assert client.get('/api/intelligence/drafts').json()['items']==[]
    assert client.post(path+'/review',json={'acknowledged':True,'content_hash':digest}).status_code==409
    saved=client.patch(path,json={**NATURAL,'saved':True}).json()
    assert saved['evidence']['review']['state']=='required'
    assert client.get('/api/dashboard').json()['drafts_ready']==0
    assert client.post(path+'/review',json={'acknowledged':False,'content_hash':digest}).status_code==422
    assert client.post(path+'/review',json={'acknowledged':True,'content_hash':'0'*64}).status_code==409
    ack=client.post(path+'/review',json={'acknowledged':True,'content_hash':digest})
    assert ack.status_code==200 and ack.json()['evidence']['review']['state']=='ready'
    assert ack.json()['evidence']['review']['factual_status']=='unverified'
    assert client.get('/api/dashboard').json()['drafts_ready']==1
    changed={**NATURAL,'body':NATURAL['body']+' Thank you for considering this.','saved':True}
    edited=client.patch(path,json=changed).json()
    assert edited['evidence']['review']['state']=='required' and edited['evidence']['review']['content_hash']!=digest
    assert client.get('/api/dashboard').json()['drafts_ready']==0
    assert client.post(path+'/review',json={'acknowledged':True,'content_hash':digest}).status_code==409
    recovered=client.get('/api/intelligence/drafts').json()['items'][0]
    assert recovered['body']==changed['body'] and recovered['evidence']['review']['state']=='required'

@pytest.mark.anyio
async def test_discard_removes_only_new_content_and_preserves_usage_and_history(client,database,monkeypatch,caplog):
    sentinel='UNIQUE_PROPOSAL_CONTENT_FOR_DISCARD'
    job,aid=await generated(database,monkeypatch,body=NATURAL['body']+' '+sentinel)
    did=job['result']['draft_id'];path=f'/api/intelligence/drafts/{did}'
    from app.intelligence.drafts import compose
    with Session(database) as s:
        older=compose(s.get(Assessment,aid),'email',generator='gemini')
        s.add(older);s.commit();old_id=older.id;old_body=older.body
    foreign={'Origin':'https://evil.example'}
    assert client.delete(path,headers=foreign).status_code==403
    assert client.delete(path).status_code==204
    assert client.get(path).status_code==404 and client.delete(path).status_code==404
    assert client.get('/api/intelligence/ai/'+str(job['id'])).json()['result']=={'discarded':True}
    assert client.get(f'/api/intelligence/drafts?assessment_id={aid}&saved=false').json()['total']==1
    assert client.delete(f'/api/intelligence/drafts/{old_id}').status_code==409
    with Session(database) as s:
        usage=s.get(AIUsage,job['id']);assert usage.input_tokens==12 and usage.output_tokens==30
        assert s.get(OutreachDraft,old_id).body==old_body
        assert sentinel not in json.dumps([r.result for r in s.scalars(select(AIUsage))])
    assert sentinel not in caplog.text
    assert sentinel.encode() not in Path(database.url.database).read_bytes()

@pytest.mark.anyio
@pytest.mark.parametrize('bad_body',['Contact private@example.com.','API_KEY=SECRET_VALUE','https://evil.xyz/','I will deliver tomorrow.'])
async def test_hard_blocked_edits_preserve_existing_row(client,database,monkeypatch,bad_body):
    job,_=await generated(database,monkeypatch);path='/api/intelligence/drafts/'+str(job['result']['draft_id'])
    before=client.get(path).json()
    r=client.patch(path,json={'subject':NATURAL['subject'],'body':bad_body,'saved':True})
    assert r.status_code==422 and bad_body not in r.text
    assert client.get(path).json()==before

@pytest.mark.anyio
async def test_hard_blocked_provider_response_creates_no_draft_or_copy(client,database,monkeypatch,mocked,caplog):
    aid=await prepare(database,monkeypatch)
    raw={**NATURAL,'body':'PRIVATE_BLOCKED_SENTINEL private@example.com'};Client,_,_=sdk(raw)
    async def fake(context):return await write_proposal(context,Client)
    manager=AIManager(database,writer_provider=fake);job=await manager.start(aid,'draft','email')
    await asyncio.gather(*list(manager.tasks.values()));result=manager.read(job['id'])
    assert result['status']=='error' and result['result']['diagnostics']['disposition']=='hard_blocked'
    assert result['input_tokens']==50 and result['output_tokens']==100
    with Session(database) as s:
        assert s.scalar(select(func.count()).select_from(OutreachDraft))==0
        assert 'PRIVATE_BLOCKED_SENTINEL' not in json.dumps([r.result for r in s.scalars(select(AIUsage))])
    assert 'PRIVATE_BLOCKED_SENTINEL' not in caplog.text

@pytest.mark.anyio
async def test_explicit_consent_is_still_required_before_any_reservation(client,database,monkeypatch):
    aid=await prepare(database,monkeypatch)
    payload={'assessment_id':aid,'generator':'gemini','review_confirmed':True,'public_data_consent':False}
    assert client.post('/api/intelligence/drafts',json=payload).status_code==422
    assert client.post('/api/intelligence/drafts',json={**payload,'public_data_consent':True},headers={'Origin':'https://evil.example'}).status_code==403
    with Session(database) as s:assert s.scalar(select(func.count()).select_from(AIUsage))==0

@pytest.mark.anyio
async def test_profile_opt_out_cannot_send_or_use_saved_optional_links(database,monkeypatch,mocked):
    aid=await prepare(database,monkeypatch)
    confirm_writer(database,monkeypatch,display_name='PUBLIC_NAME_SENTINEL',portfolio_url='https://portfolio.example.com/',
        instagram_url='https://www.instagram.com/sample/')
    data={**NATURAL,'body':NATURAL['body']+' https://portfolio.example.com/'}
    Client,calls,_=sdk(data)
    async def fake(context):return await write_proposal(context,Client)
    manager=AIManager(database,writer_provider=fake)
    job=await manager.start(aid,'draft','email',include_profile=False)
    await asyncio.gather(*list(manager.tasks.values()))
    public=json.loads(calls[1]['contents'])
    assert public['approved_links']==[] and public['freelancer_name']=='' and public['relevant_projects']==[]
    assert 'PUBLIC_NAME_SENTINEL' not in calls[1]['contents']
    assert manager.read(job['id'])['status']=='error'
    with Session(database) as s:assert s.scalar(select(func.count()).select_from(OutreachDraft))==0

@pytest.mark.anyio
async def test_content_free_revocation_survives_reload_and_keeps_original_text(client,database,monkeypatch):
    job,_=await generated(database,monkeypatch);path='/api/intelligence/drafts/'+str(job['result']['draft_id'])
    client.patch(path,json={**NATURAL,'saved':True})
    digest=client.get(path).json()['evidence']['review']['content_hash']
    for invalid in (False,1,'true',None):
        assert client.post(path+'/review',json={'acknowledged':invalid,'content_hash':digest}).status_code==422
    assert client.post(path+'/review',json={'acknowledged':True,'content_hash':digest},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post(path+'/review',json={'acknowledged':True,'content_hash':digest}).status_code==200
    assert client.delete(path+'/review',headers={'Origin':'https://evil.example'}).status_code==403
    revoked=client.delete(path+'/review');assert revoked.status_code==200
    assert revoked.json()['evidence']['review']['state']=='required'
    assert client.get(path).json()['body']==NATURAL['body']
    assert client.get('/api/dashboard').json()['drafts_ready']==0

@pytest.mark.parametrize('text',[
    'I can deliver a demo next week.', 'I could finish in ten days.',
    'I can create a custom preview for your business.', 'I can build a website at no cost.',
])
def test_prohibited_deliverables_and_timelines_even_when_walkthrough_allowed(text):
    authorization={**ctx(),'walkthrough_allowed':True}
    with pytest.raises(WritingValidationError) as caught:hard_check('A useful conversation',text,authorization)
    assert caught.value.rule=='unapproved_commitment'

@pytest.mark.parametrize('sender',['Invented Sender','Will'])
def test_sender_authorization_never_masks_promises(sender):
    context=ctx(FreelancerProfile(display_name='Will',service_ids=['frontend'],public_details_confirmed=True))
    data={**NATURAL,'body':NATURAL['body']+'\n\nThanks,\n'+sender}
    if sender=='Will':assert validate_human(data,context).body==data['body']
    else:
        with pytest.raises(WritingValidationError):validate_human(data,context)
    data['body']='I will create a custom preview.\n\nThanks,\nWill'
    with pytest.raises(WritingValidationError) as caught:validate_human(data,context)
    assert caught.value.rule=='unapproved_commitment'

FORMATTED_EMAIL={
    'subject':'A focused refinement for your existing website',
    'body':"Hello Fixture Cafe team,\n\nI appreciate that you already have a public website for your business.\n\nA focused review of image descriptions could be a useful next step. I could help refine those details while building on what you already have.\n\nWould a brief conversation about possible refinements be useful?\n\nKind regards,\nSam",
}

@pytest.mark.anyio
async def test_email_formatting_survives_sdk_storage_edit_reload_and_review(client,database,monkeypatch,mocked):
    aid=await prepare(database,monkeypatch)
    confirm_writer(database,monkeypatch,display_name='Sam')
    Client,calls,closed=sdk(FORMATTED_EMAIL)
    async def fake(context):return await write_proposal(context,Client)
    manager=AIManager(database,writer_provider=fake)
    job=await manager.start(aid,'draft','email',include_profile=True)
    await asyncio.gather(*list(manager.tasks.values()))
    completed=manager.read(job['id']);assert completed['status']=='complete'
    instructions=calls[1]['config'].system_instruction
    assert instructions.startswith(HUMAN_GUIDANCE) and CHANNEL_GUIDANCE['email'] in instructions
    assert 'actual blank lines' in instructions and 'Kind regards' in instructions
    assert closed==[True] and len(calls)==2
    path='/api/intelligence/drafts/'+str(completed['result']['draft_id'])
    loaded=client.get(path).json()
    assert loaded['subject']==FORMATTED_EMAIL['subject'] and loaded['body']==FORMATTED_EMAIL['body']
    assert loaded['body'].split('\n\n')[0]=='Hello Fixture Cafe team,'
    assert loaded['body'].split('\n\n')[-1]=='Kind regards,\nSam'
    assert r'\n' not in loaded['body']
    edited={**FORMATTED_EMAIL,'body':FORMATTED_EMAIL['body'].replace('possible refinements','these small refinements'),'saved':True}
    saved=client.patch(path,json=edited);assert saved.status_code==200
    reloaded=client.get('/api/intelligence/drafts').json()['items'][0]
    assert reloaded['body']==edited['body'] and reloaded['body'].count('\n\n')==4
    assert reloaded['subject']==FORMATTED_EMAIL['subject']
    acknowledged=client.post(path+'/review',json={'acknowledged':True,'content_hash':reloaded['evidence']['review']['content_hash']})
    assert acknowledged.status_code==200 and acknowledged.json()['body']==edited['body']
    assert acknowledged.json()['evidence']['review']['factual_status']=='unverified'

@pytest.mark.anyio
@pytest.mark.parametrize('channel,body',[
    ('whatsapp',"Hi Fixture Cafe team! A review of image descriptions could be useful.\n\nWould a quick chat help?"),
    ('instagram_dm',"Hi Fixture Cafe team! Could a focused review of image descriptions be useful?"),
    ('linkedin_dm',"Hello Fixture Cafe team, I offer website refinements.\n\nWould a short conversation about image descriptions be useful?"),
    ('contact_form',"Hello Fixture Cafe team,\n\nI offer website refinements and could review image descriptions. Would a brief conversation help?"),
])
async def test_each_non_email_channel_gets_distinct_instructions_and_keeps_its_layout(mocked,channel,body):
    Client,calls,_=sdk({'subject':'','body':body})
    output,_=await write_proposal(ctx(channel=channel),Client)
    assert output.subject=='' and output.body==body
    guidance=calls[1]['config'].system_instruction
    assert CHANNEL_GUIDANCE[channel] in guidance and CHANNEL_GUIDANCE['email'] not in guidance
    assert 'EMAIL FORMAT:' not in guidance


def test_signature_without_shared_name_uses_only_a_closing():
    data={**FORMATTED_EMAIL,'body':FORMATTED_EMAIL['body'].removesuffix('\nSam')}
    assert validate_human(data,ctx()).body.endswith('Kind regards,')
    with pytest.raises(WritingValidationError):validate_human(FORMATTED_EMAIL,ctx())
    assert 'never invent a name' in CHANNEL_GUIDANCE['email']
