from app.intelligence.writer import WRITER_VERSIONS
import asyncio
import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.intelligence.writer import writer_context,validate_written,compose_written,WritingValidationError
from app.intelligence.profile import read_profile,path_for
from app.intelligence.ai_manager import AIManager
from app.providers.gemini import write_annotated_proposal as write_proposal,GeminiFailure,WRITER_GUIDANCE
from app.schemas.intelligence import FreelancerProfile
from app.models.intelligence import OutreachDraft,BusinessIdentity,AIUsage
from app.intelligence.scoring import assess
from test_intelligence import enriched
from writer_helpers import written,confirm_writer,human_written
from app.intelligence.human_writer import HUMAN_VERSIONS

def fixture_assessment():
    return SimpleNamespace(id=2,identity_id=1,qualification='qualified',report={
        'business':{'name':'Fixture Cafe','category':'cafe','notes':'PRIVATE NOTE','email':'personal@example.com','api_key':'SECRET'},
        'identity':{'status':'matched','official':True},'skill_matches':['frontend'],
        'contacts':[{'value':'personal@example.com'},{'value':'+44 1234 567890'}],
        'evidence':[{'id':'image_alt_missing','title':'PRIVATE NOTE unsafe raw title','detail':'personal@example.com SECRET raw HTML',
                     'source_url':'https://example.com/','observed_at':'2026-10-14T08:00:00Z'}]})

def context(profile=None,channel='email'):
    return writer_context(fixture_assessment(),channel,profile or FreelancerProfile(service_ids=['frontend'],public_details_confirmed=True))

def sdk(output=None,error=None,text=None):
    calls=[];closed=[]
    class Models:
        async def generate_content(self,**kwargs):
            calls.append(kwargs)
            if error:raise error
            return SimpleNamespace(candidates=[SimpleNamespace(finish_reason='STOP')],text=text if text is not None else json.dumps(output),usage_metadata=SimpleNamespace(prompt_token_count=50,candidates_token_count=100))
    class Client:
        def __init__(self,**kwargs):calls.append(kwargs);self.aio=SimpleNamespace(models=Models(),aclose=self.close)
        async def close(self):closed.append(True)
    return Client,calls,closed

@pytest.mark.anyio
async def test_sdk_writes_actual_prose_with_bounded_context_and_no_private_data(monkeypatch):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')
    ctx=context();output=written(ctx);Client,calls,closed=sdk(output.model_dump())
    result,tokens=await write_proposal(ctx,Client)
    assert result.subject==output.subject and result.body==output.body
    assert tokens=={'input_tokens':50,'output_tokens':100} and closed==[True]
    assert calls[1]['model']=='gemini-3.5-flash-lite'
    options=calls[0]['http_options'];config=calls[1]['config']
    assert options.base_url=='https://generativelanguage.googleapis.com' and options.retry_options.attempts==1
    assert options.async_client_args['trust_env'] is False and config.automatic_function_calling.disable
    assert config.response_json_schema['properties']['subject'] and config.response_json_schema['properties']['body']
    assert config.system_instruction==WRITER_GUIDANCE
    for forbidden in ('PRIVATE NOTE','personal@example.com','SECRET','+44 1234','raw HTML'):
        assert forbidden not in calls[1]['contents']
    assert len(calls)==2  # One constructor and one provider call, no verification/fallback call.

@pytest.mark.parametrize('patch',[
    {'subject':''},{'subject':'X'*201},{'subject':'Hello\nBcc: victim'}, {'body':'X'*1801},
    {'finding_ids':['invented_weakness']},{'service_ids':['shopify']},{'project_ids':['invented']},
    {'used_links':['https://invented.example.com/']},{'claims':[]},{'offers_walkthrough':True},
])
def test_structured_output_rejects_invalid_and_unapproved_fields(patch):
    ctx=context();data=written(ctx).model_dump();data.update(patch)
    with pytest.raises(ValueError):validate_written(data,ctx)

@pytest.mark.parametrize('claim',[
    'Your website is ugly and your developer is incompetent.',
    'I guarantee increased sales and conversions.',
    'Your business earns 100000 and has poor rankings.',
    'Your customers love your beautiful website.',
    'You are looking for a new developer.',
    'I have worked with famous clients for ten years.',
    'I already built a personalized demo for you.',
    'I can finish in a week for free.',
    'I will deliver a complete redesign.',
    'Contact me at personal@example.com.',
    'My portfolio is https://invented.example.com/',
    'My portfolio is invented.com.',
    'Your page is missing a description.',
    'Best,\nInvented Freelancer',
    'I offer Shopify development.',
    'I can share a demo if you want.',
])
def test_free_prose_rejects_unsafe_unsupported_claims(claim):
    ctx=context();data=written(ctx).model_dump();data['body']+='\n'+claim
    with pytest.raises(ValueError):validate_written(data,ctx)

def test_factual_claims_must_match_allowlist_and_metadata():
    ctx=context();data=written(ctx).model_dump()
    data['claims'][0]['text']='You have an award-winning website.'
    data['body']=data['body'].replace(ctx['approved_facts']['website_present'],data['claims'][0]['text'])
    with pytest.raises(ValueError):validate_written(data,ctx)
    data=written(ctx).model_dump();data['finding_ids']=[]
    with pytest.raises(ValueError):validate_written(data,ctx)

@pytest.mark.parametrize('closing',['Best,\nSam','Best regards,\nSam','Kind regards,\nSam','Warm regards,\nSam','Sincerely,\nSam','Best,'])
def test_normal_closings_do_not_trigger_prohibited_superiority_claims(closing):
    ctx=context(FreelancerProfile(display_name='Sam',service_ids=['frontend'],public_details_confirmed=True))
    result=written(ctx);result.body+='\n\n'+closing
    assert validate_written(result,ctx).body==result.body

def test_approved_courtesy_does_not_trigger_free_work_rule():
    ctx=context();result=written(ctx)
    result.body+=' Feel free to reply if you would like to discuss this.'
    assert validate_written(result,ctx)==result

@pytest.mark.parametrize('suffix,rule',[
    ('\n\nBest,\nUnknown Freelancer','signature_identity'),
    (' I am the best developer.\n\nBest,\nSam','prohibited_claim'),
    (' Feel free to reply for free custom work.','prohibited_claim'),
    (' Feel free to reply for guaranteed sales.','prohibited_claim'),
    (' Feel free to reply and I will deliver a custom redesign.','unapproved_commitment'),
    (' Feel free to reply if you want a personalized demo.','prohibited_claim'),
])
def test_courtesy_exceptions_preserve_identity_and_claim_checks(suffix,rule):
    ctx=context(FreelancerProfile(display_name='Sam',service_ids=['frontend'],public_details_confirmed=True))
    output=written(ctx);output.body+=suffix
    with pytest.raises(WritingValidationError) as caught:validate_written(output,ctx)
    assert caught.value.rule==rule

@pytest.mark.anyio
async def test_empty_optional_profile_fields_work_through_mocked_sdk(monkeypatch):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')
    profile=FreelancerProfile(service_ids=['frontend'],public_details_confirmed=True,instagram_url='',projects=[])
    ctx=context(profile,channel='instagram_dm');output=written(ctx)
    Client,calls,closed=sdk(output.model_dump())
    result,_=await write_proposal(ctx,Client)
    assert result.subject=='' and result.project_ids==[] and result.used_links==[] and not result.offers_walkthrough
    assert ctx['instagram_url']=='' and ctx['relevant_projects']==[] and not ctx['walkthrough_allowed']
    assert len(calls)==2 and closed==[True]

def test_optional_project_url_is_empty_but_incomplete_project_records_are_rejected():
    from pydantic import ValidationError
    profile=FreelancerProfile.model_validate({'service_ids':['frontend'],'public_details_confirmed':True,'projects':[
        {'id':'cafe','title':'Cafe Website','url':'','service_ids':['frontend']}]})
    ctx=context(profile)
    assert ctx['relevant_projects'][0]['url']=='' and ctx['approved_links']==[]
    assert validate_written(written(ctx,with_profile=True),ctx).project_ids==['cafe']
    with pytest.raises(ValidationError):FreelancerProfile.model_validate({'projects':[{'id':'unfinished','title':'','url':'','service_ids':[]}]})

def test_profile_experience_links_and_walkthrough_are_optional_relevant_and_grounded():
    profile=FreelancerProfile.model_validate({'display_name':'Sam','service_ids':['frontend','python'],'public_details_confirmed':True,
        'portfolio_url':'https://portfolio.example.com/','instagram_url':'https://www.instagram.com/sam.projects/',
        'allow_walkthrough_offer':True,'projects':[
            {'id':'cafe-site','title':'Cafe Website','url':'https://projects.example.com/cafe','kind':'completed_project','service_ids':['frontend']},
            {'id':'data-tool','title':'Data Tool','url':'https://projects.example.com/tool','kind':'completed_project','service_ids':['python']}]})
    ctx=context(profile);assert [p['id'] for p in ctx['relevant_projects']]==['cafe-site']
    assert 'https://projects.example.com/tool' not in ctx['approved_links']
    output=written(ctx,with_profile=True)
    output.body+=' I could share a short project walkthrough if you would find it useful.';output.offers_walkthrough=True
    assert validate_written(output,ctx)==output
    output.used_links.append(profile.instagram_url);output.body+=' '+profile.instagram_url
    assert validate_written(output,ctx).used_links[-1]==profile.instagram_url
    ctx['walkthrough_allowed']=False
    with pytest.raises(ValueError):validate_written(output,ctx)
    empty=context();minimal=written(empty)
    assert not minimal.project_ids and not minimal.used_links and not minimal.offers_walkthrough
    assert '[' not in minimal.body and 'portfolio' not in minimal.body.lower()

def test_existing_demo_never_establishes_completed_work_and_non_email_has_no_subject():
    profile=FreelancerProfile.model_validate({'service_ids':['frontend'],'public_details_confirmed':True,'projects':[
        {'id':'demo','title':'Layout Demo','kind':'existing_demo','service_ids':['frontend']}]})
    ctx=context(profile,channel='whatsapp');result=written(ctx,with_profile=True)
    assert not result.subject and 'I have an existing demo called Layout Demo.' in result.body
    assert validate_written(result,ctx)==result
    data=result.model_dump();data['body']+=' I have worked on Layout Demo.'
    with pytest.raises(ValueError):validate_written(data,ctx)

@pytest.mark.anyio
@pytest.mark.parametrize('failure',[400,404,429,500,503])
async def test_sdk_provider_errors_are_redacted_without_model_or_api_fallback(monkeypatch,failure):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')
    error=type('ProviderError',(Exception,),{'code':failure})('TEST_SECRET_KEY private provider body')
    Client,calls,closed=sdk(error=error)
    with pytest.raises(GeminiFailure) as caught:await write_proposal(context(),Client)
    assert caught.value.code==failure and 'TEST_SECRET_KEY' not in str(caught.value)
    assert len(calls)==2 and closed==[True]

@pytest.mark.anyio
async def test_invalid_sdk_writing_is_rejected_without_substitution(monkeypatch):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')
    output=written(context()).model_dump();output['body']+=' Guaranteed sales.'
    Client,calls,closed=sdk(output)
    with pytest.raises(GeminiFailure,match='No template or alternate model'):await write_proposal(context(),Client)
    assert len(calls)==2 and closed==[True]

@pytest.mark.anyio
@pytest.mark.parametrize('case,stage,rule,fields',[
    ('invalid_json','parse','invalid_json',None),
    ('subject_length','schema','schema_violation',['subject']),
    ('body_length','schema','schema_violation',['body']),
    ('body_words','validation','body_length',None),
    ('non_email_subject','validation','non_email_subject',None),
    ('fact_wording','validation','fact_wording',None),
    ('unsafe_claim','validation','prohibited_claim',None),
    ('private_extra_field','schema','schema_violation',[]),
    ('response_length','response','response_too_large',None),
    ('protected_response','response','protected_information',None),
])
async def test_failure_diagnostics_identify_fixed_rules_without_retaining_values(monkeypatch,capsys,case,stage,rule,fields):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')
    ctx=context(channel='instagram_dm');data=written(ctx).model_dump();raw=None
    if case=='invalid_json':raw='{"PRIVATE SENTINEL":'
    if case=='subject_length':data['subject']='X'*201
    if case=='body_length':data['body']='X'*1801
    if case=='body_words':data['body']='word '*221
    if case=='non_email_subject':data['subject']='Unwanted subject'
    if case=='fact_wording':data['claims'][0]['text']='PRIVATE SENTINEL fabricated praise.'
    if case=='unsafe_claim':data['body']+=' Guaranteed sales.'
    if case=='private_extra_field':data['PRIVATE SENTINEL personal@example.com']='PRIVATE CONTENT'
    if case=='response_length':raw='X'*16001
    if case=='protected_response':raw='TEST_SECRET_KEY'
    Client,calls,closed=sdk(data,text=raw)
    with pytest.raises(GeminiFailure) as caught:await write_proposal(ctx,Client)
    expected={'stage':stage,'rule':rule,**WRITER_VERSIONS}
    if fields is not None:expected['fields']=fields
    if case=='fact_wording':expected['reason']='unsupported_wording'
    if case=='unsafe_claim':expected['reason']='guaranteed_result'
    assert caught.value.diagnostics==expected and caught.value.code==-1
    assert 'Validation rule: '+rule in str(caught.value)
    evidence=str(caught.value)+json.dumps(caught.value.diagnostics)
    for private in ('PRIVATE SENTINEL','PRIVATE CONTENT','personal@example.com','TEST_SECRET_KEY'):assert private not in evidence
    assert capsys.readouterr()==('','')
    assert len(calls)==2 and closed==[True]

def test_diagnostic_sanitizer_accepts_only_static_codes_and_schema_fields():
    from app.intelligence.writer import safe_writer_diagnostics
    safe=safe_writer_diagnostics({'stage':'schema','rule':'schema_violation','fields':['body','private@example.com','subject'],'response':'PRIVATE CONTENT'})
    assert safe=={'stage':'schema','rule':'schema_violation','fields':['body','subject']}
    for data in ({'stage':'schema','rule':'PRIVATE CONTENT'},{'stage':'PRIVATE CONTENT','rule':'schema_violation'}, {'stage':[],'rule':[]},None):
        assert safe_writer_diagnostics(data) is None

@pytest.mark.parametrize('field',['subject','body'])
def test_already_parsed_models_are_revalidated_against_character_limits(field):
    from pydantic import ValidationError
    ctx=context();output=written(ctx)
    if field=='subject':output.subject='X'*201
    else:output.body+=' '+('X'*1801)
    with pytest.raises(ValidationError):validate_written(output,ctx)

@pytest.mark.anyio
async def test_model_misconfiguration_is_explicit_without_a_call(monkeypatch):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-other')
    Client,calls,closed=sdk()
    with pytest.raises(GeminiFailure,match='requires configured model'):await write_proposal(context(),Client)
    assert calls==[] and closed==[]

@pytest.mark.anyio
async def test_known_backend_secrets_cannot_enter_public_writer_context(monkeypatch):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')
    ctx=context();ctx['business_name']='TEST_SECRET_KEY'
    Client,calls,closed=sdk()
    with pytest.raises(GeminiFailure,match='No AI call was made'):await write_proposal(ctx,Client)
    assert calls==[] and closed==[]

def test_profile_is_local_validated_and_protected_by_existing_origin_checks(client,database):
    assert not path_for(database).exists()
    empty=client.get('/api/intelligence/freelancer-profile').json()
    assert empty['projects']==[] and not empty['public_details_confirmed']
    profile={'display_name':'Sam','service_ids':['frontend'],'public_details_confirmed':True,'portfolio_url':'https://portfolio.example.com/'}
    assert client.patch('/api/intelligence/freelancer-profile',json=profile,headers={'Origin':'https://evil.example'}).status_code==403
    assert not path_for(database).exists()
    assert client.patch('/api/intelligence/freelancer-profile',json=profile).status_code==200
    assert read_profile(database).display_name=='Sam'
    for patch in ({'display_name':'personal@example.com'},{'portfolio_url':'http://localhost/'},{'portfolio_url':'https://example.com/?token=secret'},
                  {'portfolio_url':'https://example.com/personal%40example.com'}, {'portfolio_url':'https://example.com/token/credential'},
                  {'instagram_url':'https://not-instagram.example.com/sam'}, {'notes':'PRIVATE'}, {'display_name':'API_KEY_SECRET'}):
        assert client.patch('/api/intelligence/freelancer-profile',json={**profile,**patch}).status_code==422
    assert read_profile(database).display_name=='Sam'

@pytest.mark.anyio
@pytest.mark.parametrize('failure',['unsafe_claim','body_length','provider_validation'])
async def test_writer_manager_validates_again_and_preserves_legacy_drafts(client,database,monkeypatch,failure):
    from app.intelligence.drafts import compose
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:
        a=assess(s,s.get(BusinessIdentity,identity_id));s.flush();aid=a.id
        legacy=compose(a,'email',generator='gemini');s.add(legacy);s.commit();legacy_id=legacy.id;old_description=legacy.evidence['generator_description']
    confirm_writer(database,monkeypatch)
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    async def bad(ctx):
        if failure=='provider_validation':raise GeminiFailure(-1,'Rejected writing. No fallback.',{'stage':'validation','rule':'fact_wording'})
        result=human_written(ctx)
        result.body+=' Guaranteed sales.' if failure=='unsafe_claim' else ' '+('X'*1801)
        return result,{'input_tokens':1,'output_tokens':1}
    manager=AIManager(database,writer_provider=bad)
    job=await manager.start(aid,'draft','email');await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(job['id'])['status']=='error'
    expected={'stage':'schema','rule':'schema_violation','fields':['body']} if failure=='body_length' else {'stage':'validation','rule':'fact_wording' if failure=='provider_validation' else 'prohibited_claim'}
    if failure!='provider_validation':expected.update(HUMAN_VERSIONS)
    if failure=='unsafe_claim':expected['reason']='guaranteed_result'
    if failure!='provider_validation':expected['disposition']='hard_blocked'
    assert manager.read(job['id'])['result']['diagnostics']==expected
    with Session(database) as s:
        assert s.scalar(select(func.count()).select_from(OutreachDraft))==1
        assert s.get(OutreachDraft,legacy_id).evidence['generator_description']==old_description

@pytest.mark.anyio
async def test_profile_opt_in_uses_only_confirmed_relevant_public_information(database,monkeypatch):
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=a.id
    confirm_writer(database,monkeypatch,display_name='Sam',portfolio_url='https://portfolio.example.com/')
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    contexts=[]
    async def fake(ctx):contexts.append(ctx);return human_written(ctx),{'input_tokens':1,'output_tokens':1}
    manager=AIManager(database,writer_provider=fake)
    job=await manager.start(aid,'draft','email',include_profile=False);await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(job['id'])['status']=='complete' and contexts[0]['freelancer_name']=='' and contexts[0]['approved_links']==[]
    with Session(database) as s:
        from datetime import timedelta
        from app.models.lead import now
        s.get(AIUsage,job['id']).created_at=now()-timedelta(minutes=1);s.commit()
    next_job=await manager.start(aid,'draft','email',include_profile=True);await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(next_job['id'])['status']=='complete'
    assert contexts[-1]['freelancer_name']=='Sam' and contexts[-1]['approved_links']==['https://portfolio.example.com/']

@pytest.mark.anyio
async def test_writer_requires_confirmed_capabilities_before_reserving_a_paid_job(database,monkeypatch):
    from fastapi import HTTPException
    from app.intelligence.profile import save_profile
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=a.id
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_MODEL','gemini-3.5-flash-lite')
    calls=[]
    async def fake(ctx):calls.append(ctx);raise AssertionError('No request should be reserved.')
    manager=AIManager(database,writer_provider=fake)
    for profile in (FreelancerProfile(),FreelancerProfile(service_ids=['frontend']),FreelancerProfile(service_ids=['python'],public_details_confirmed=True)):
        save_profile(database,profile)
        with pytest.raises(HTTPException) as rejected:await manager.start(aid,'draft','email')
        assert rejected.value.status_code==422
    assert calls==[]
    with Session(database) as s:assert s.scalar(select(func.count()).select_from(AIUsage))==0

@pytest.mark.anyio
@pytest.mark.parametrize('code',[500,503])
async def test_writer_bounded_retry_uses_same_context_and_no_template_provider(database,monkeypatch,code):
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=a.id
    confirm_writer(database,monkeypatch)
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    async def no_sleep(_):pass
    monkeypatch.setattr('app.intelligence.ai_manager.asyncio.sleep',no_sleep)
    calls=[]
    async def retry(ctx):
        calls.append(ctx)
        if len(calls)==1:raise GeminiFailure(code,'Temporary writer failure.')
        return human_written(ctx),{'input_tokens':20,'output_tokens':40}
    async def no_fallback(*args):raise AssertionError('Do not substitute the legacy selection provider.')
    manager=AIManager(database,provider=no_fallback,writer_provider=retry)
    job=await manager.start(aid,'draft','email');await asyncio.gather(*list(manager.tasks.values()))
    result=manager.read(job['id']);assert result['status']=='complete' and len(calls)==2 and calls[0]==calls[1]
    with Session(database) as s:
        assert s.scalar(select(func.count()).select_from(AIUsage))==2
        assert s.scalar(select(func.count()).select_from(OutreachDraft))==1
        assert s.get(OutreachDraft,result['result']['draft_id']).body==human_written(calls[1]).body
