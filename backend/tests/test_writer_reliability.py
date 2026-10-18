"""Independent authored corpus using HAPPY's audited evidence/profile shape.

No production phrase builder generates the proposals. Public name HAPPY and its
one observed image-alt finding are retained; personal name/URL are synthetic.
No live database access, provider calls or rejected live responses are used.
"""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from google.genai import types
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.intelligence.writer import writer_context,validate_written,WritingValidationError,WRITER_VERSIONS,OBSERVATIONS
from app.intelligence.profile import save_profile,read_profile,path_for,MAX_PROFILE_BYTES
from app.intelligence.ai_manager import AIManager
from app.intelligence.scoring import assess
from app.models.intelligence import AIUsage,OutreachDraft,BusinessIdentity
from app.schemas.intelligence import FreelancerProfile
from app.providers.gemini import write_annotated_proposal as write_proposal,GeminiFailure
from app.auditing.html import analyze_html
from test_ai_writer import sdk
from test_intelligence import enriched
from writer_helpers import confirm_writer,written,human_written
from app.intelligence.human_writer import HUMAN_VERSIONS

CORPUS=json.loads((Path(__file__).parent/'fixtures/happy_writer_corpus.json').read_text())

def happy_context(**profile_changes):
    profile=FreelancerProfile.model_validate({'display_name':'Sam','service_ids':['python','react','shopify','wordpress','frontend'],
        'public_details_confirmed':True,'portfolio_url':'https://portfolio.example.com/','instagram_url':'','projects':[],**profile_changes})
    assessment=SimpleNamespace(qualification='qualified',report={'business':{'name':'HAPPY'},'identity':{'status':'matched','official':True},
        'skill_matches':['frontend'],'evidence':[{'id':'image_alt_missing','source_url':'https://example.com/','observed_at':'2026-10-14T00:00:00Z'}]})
    return writer_context(assessment,'email',profile)

@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','OFFLINE_TEST_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')

@pytest.mark.anyio
@pytest.mark.parametrize('index',range(len(CORPUS)))
async def test_independently_authored_proposals_preserved_exactly(mock_settings,index):
    data=copy.deepcopy(CORPUS[index]);ctx=happy_context();Client,calls,closed=sdk(data)
    result,_=await write_proposal(ctx,Client)
    assert result.subject==data['subject'] and result.body==data['body']
    assert ctx['allowed_services']==['frontend'] and ctx['relevant_projects']==[] and not ctx['walkthrough_allowed']
    assert len(calls)==2 and closed==[True]

@pytest.mark.parametrize('extra',[
    'Your booking form stops visitors from contacting you.',
    'Your site attracts a million visitors.', 'Your site attracts 1000000 visitors.',
    'We spoke at the conference.', 'My projects have earned international recognition.',
    'I offer mobile app development.', 'I can build a custom preview for your business.',
    'I guarantee higher sales.', 'You requested this redesign.',
    'Your team needs a new developer.', 'Visitors abandon your checkout.',
    'Your restaurant serves award-winning food.', 'I built websites for famous clients.',
    'Would you like me to fix your broken booking form?',
    'If you want higher rankings, I can guarantee them.',
    'If useful, I could offer paid ads.',
    'If we met last week, you know my work.',
    'I can deliver a personalized demo tomorrow.',
    'Your website is beautiful.', 'The website fails on phones.',
    'Explore my portfolio at invented.xyz.', 'Visit invented.co.uk.',
    'Visit https://portfolio.example.com.evil.org/.',
    'My portfolio: https://user@portfolio.example.com/',
    'My portfolio: https://portfolio.example.com/?token=PRIVATE',
    'Best,\nInvented Sender', 'Thanks,\nInvented Sender',
    'Cheers, Invented Sender', 'Warm regards,\nInvented Sender',
    'Signed by Invented Sender',
])
def test_independent_negative_corpus(extra):
    data=copy.deepcopy(CORPUS[0]);data['body']=data['body'].replace('\n\nKind regards,\nSam','\n'+extra)
    with pytest.raises(ValueError):validate_written(data,happy_context())

@pytest.mark.parametrize('prefix,suffix',[
    ('It is untrue that ',''), ('It is false that ',''), ('Never assume that ',''),
    ('Not only do we know that ', ', but your website is failing.'),
    ('', ', which proves your business is struggling.'),
    ('If ', ', then your website needs a redesign.'),
])
def test_approved_fact_cannot_be_embedded_in_unsupported_assertion(prefix,suffix):
    data=copy.deepcopy(CORPUS[0]);fact=data['claims'][1]['text']
    data['body']=data['body'].replace(fact,prefix+fact.rstrip('.')+suffix+'.')
    with pytest.raises(ValueError):validate_written(data,happy_context())

@pytest.mark.parametrize('sender',['Sam','Will','Best','May'])
def test_names_never_mask_commitments(sender):
    data=copy.deepcopy(CORPUS[0]);data['body']=data['body'].replace('Kind regards,\nSam',f'I will create a custom redesign.\n\nKind regards,\n{sender}')
    with pytest.raises(WritingValidationError) as caught:validate_written(data,happy_context(display_name=sender))
    assert caught.value.rule=='unapproved_commitment'

@pytest.mark.parametrize('closing',['Thanks','Thank you','Cheers','Regards','With thanks','Best regards'])
def test_verified_signatures_are_allowed(closing):
    data=copy.deepcopy(CORPUS[0]);data['body']=data['body'].replace('Kind regards,',closing+',')
    assert validate_written(data,happy_context()).body==data['body']

@pytest.mark.parametrize('courtesy',['Have a lovely day.','Would next week suit you?','There are no guarantees.',
    'If you want to explore this, feel free to reply.','Could we discuss the best next step?',
    'I could help refine the visitor experience.'])
def test_courtesies_are_whole_statements_not_prefix_exemptions(courtesy):
    data=copy.deepcopy(CORPUS[0]);data['body']=data['body'].replace('\n\nKind regards,',' '+courtesy+'\n\nKind regards,')
    assert validate_written(data,happy_context()).body==data['body']
    data['body']=data['body'].replace(courtesy,courtesy.rstrip('.?')+', and your visitors cannot book online.')
    with pytest.raises(ValueError):validate_written(data,happy_context())

def test_business_name_normalization_has_boundaries():
    data=copy.deepcopy(CORPUS[0]);ctx=happy_context();ctx['business_name']='HAPPY Cafe'
    data['body']=data['body'].replace('HAPPY team','HAPPY\n Cafe team')
    data['subject']='A quick question'
    assert validate_written(data,ctx).body==data['body']
    data['body']=data['body'].replace('HAPPY\n Cafe','UNHAPPY Cafe')
    with pytest.raises(WritingValidationError) as caught:validate_written(data,ctx)
    assert caught.value.rule=='business_name_required'

def test_viewport_wording_preserves_the_actual_observation():
    _,findings=analyze_html(b'<meta name="viewport" content="initial-scale=1">','https://example.com/',{'content-type':'text/html'})
    assert any(f['code']=='viewport_missing' for f in findings)
    assert OBSERVATIONS['viewport_missing'][0]=='The downloaded HTML did not contain a viewport declaration with width=device-width.'

def test_profile_byte_limit_is_checked_before_overwrite(database):
    original=FreelancerProfile(display_name='Sam');save_profile(database,original)
    before=path_for(database).read_bytes()
    profile=FreelancerProfile(portfolio_url='https://example.com/'+'界'*1900,service_ids=['frontend'],projects=[
        {'id':f'project-{i}','title':'Example','service_ids':['frontend'],'url':'https://example.com/'+'界'*1900+str(i)} for i in range(5)])
    assert len(json.dumps(profile.model_dump(),ensure_ascii=False).encode())>MAX_PROFILE_BYTES
    with pytest.raises(HTTPException) as caught:save_profile(database,profile)
    assert caught.value.status_code==422 and path_for(database).read_bytes()==before
    assert read_profile(database)==original

@pytest.mark.anyio
@pytest.mark.parametrize('finish,reason',[('MAX_TOKENS','truncated'),('SAFETY','blocked'),('RECITATION','blocked'),(None,'missing'),('OTHER','unexpected')])
async def test_sdk_finish_reason_and_failed_usage_are_sanitized(mock_settings,finish,reason,capsys):
    response=types.GenerateContentResponse(candidates=[types.Candidate(finish_reason=finish,content=types.Content(parts=[types.Part(text=json.dumps(CORPUS[0]))]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=42,candidates_token_count=87))
    class Client:
        def __init__(self,**kwargs):self.aio=SimpleNamespace(models=self,aclose=self.close)
        async def generate_content(self,**kwargs):return response
        async def close(self):pass
    with pytest.raises(GeminiFailure) as caught:await write_proposal(happy_context(),Client)
    assert caught.value.diagnostics=={'stage':'response','rule':'response_finish','reason':reason,**WRITER_VERSIONS}
    assert caught.value.usage=={'input_tokens':42,'output_tokens':87}
    assert 'HAPPY' not in str(caught.value)+json.dumps(caught.value.diagnostics) and capsys.readouterr()==('','')

@pytest.mark.anyio
@pytest.mark.parametrize('mode',['final_validation','cancelled','provider_validation'])
async def test_retry_terminal_state_and_usage_preserve_history(database,monkeypatch,mode):
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:
        a=assess(s,s.get(BusinessIdentity,identity_id));s.commit();aid=a.id
    confirm_writer(database,monkeypatch)
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    async def no_sleep(_):pass
    monkeypatch.setattr('app.intelligence.ai_manager.asyncio.sleep',no_sleep)
    calls=[]
    async def fake(ctx):
        calls.append(ctx)
        if len(calls)==1:raise GeminiFailure(503,'Synthetic temporary error.')
        if mode=='cancelled':raise asyncio.CancelledError
        if mode=='provider_validation':raise GeminiFailure(-1,'Rejected.',{'stage':'validation','rule':'prohibited_claim'},usage={'input_tokens':12,'output_tokens':34})
        data=human_written(ctx);data.body+=' Guaranteed sales.'
        return data,{'input_tokens':12,'output_tokens':34}
    manager=AIManager(database,writer_provider=fake);job=await manager.start(aid,'draft','email')
    await asyncio.gather(*list(manager.tasks.values()),return_exceptions=True)
    with Session(database) as s:
        rows=s.scalars(select(AIUsage).order_by(AIUsage.id)).all()
        assert len(rows)==2 and {r.status for r in rows}==({'interrupted'} if mode=='cancelled' else {'error'})
        assert all(rows[0].request[k]==v for k,v in HUMAN_VERSIONS.items())
        assert s.scalar(select(func.count()).select_from(OutreachDraft))==0
        if mode!='cancelled':assert sum(r.input_tokens or 0 for r in rows)==12 and sum(r.output_tokens or 0 for r in rows)==34

@pytest.mark.parametrize('extra,reason',[
    ('I guarantee higher sales.','guaranteed_result'),
    ('Your site attracts a million visitors.','numeric_claim'),
    ('This could increase your sales.','commercial_claim'),
    ('Your booking form is broken.','unsupported_problem'),
])
def test_prohibited_subcodes_do_not_retain_wording(extra,reason):
    data=copy.deepcopy(CORPUS[0]);data['body']=data['body'].replace('\n\nKind regards,',' '+extra+'\n\nKind regards,')
    with pytest.raises(WritingValidationError) as caught:validate_written(data,happy_context())
    assert caught.value.rule=='prohibited_claim' and caught.value.reason==reason
    assert extra not in str(caught.value)

@pytest.mark.anyio
async def test_prompt_block_feedback_is_explicit_and_sanitized(mock_settings):
    response=types.GenerateContentResponse(prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason='SAFETY'),
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=42))
    class Client:
        def __init__(self,**kwargs):self.aio=SimpleNamespace(models=self,aclose=self.close)
        async def generate_content(self,**kwargs):return response
        async def close(self):pass
    with pytest.raises(GeminiFailure) as caught:await write_proposal(happy_context(),Client)
    assert caught.value.diagnostics=={'stage':'response','rule':'response_finish','reason':'blocked',**WRITER_VERSIONS}
    assert caught.value.usage=={'input_tokens':42,'output_tokens':None}


def test_portfolio_url_alone_does_not_authorize_work_experience():
    data=copy.deepcopy(CORPUS[0]);data['body']=data['body'].replace('\n\nKind regards,',' You can see examples of my work at https://portfolio.example.com/.\n\nKind regards,')
    data['used_links']=['https://portfolio.example.com/']
    with pytest.raises(ValueError):validate_written(data,happy_context())
