from app.intelligence.writer import WRITER_VERSIONS
"""Synthetic Gemini outputs only; job #6's discarded wording is unknown."""
import asyncio
import json
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.intelligence.writer import validate_written,WritingValidationError,safe_writer_diagnostics
from app.intelligence.ai_manager import AIManager
from app.models.intelligence import BusinessIdentity,OutreachDraft
from app.intelligence.scoring import assess
from app.providers.gemini import write_annotated_proposal as write_proposal,GeminiFailure,WRITER_GUIDANCE
from app.schemas.intelligence import FreelancerProfile
from test_ai_writer import context,sdk
from test_intelligence import enriched
from writer_helpers import written,confirm_writer

def replace_claim(ctx,identifier,text):
    data=written(ctx).model_dump()
    original=ctx['approved_facts'][identifier]
    if identifier=='service:frontend' and text.startswith(('I could','If useful','Could I')):original='I can help with '+original+'.'
    if identifier=='website_present' and text.startswith(('I appreciate',"I'm glad")):original='I appreciate the online presence you have established. '+original
    data['body']=data['body'].replace(original,text)
    for claim in data['claims']:
        if claim['fact_id']==identifier:claim['text']=text
    return data

@pytest.mark.anyio
@pytest.mark.parametrize('identifier,wording',[
    ('website_present','I appreciate that your business already has a public website.'),
    ('website_present',"I'm glad your business already has a public website."),
    ('finding:image_alt_missing','In a static check of one page, some images had no alternative-text attribute.'),
    ('finding:image_alt_missing','On the checked page, some images were missing alternative-text attributes in the downloaded HTML.'),
    ('benefit:image_alt_missing','Clearer image descriptions may help visitors using assistive tools understand useful images.'),
    ('service:frontend','I could help with updates and refinements to your website.'),
    ('service:frontend','If useful, I could help refine your existing website.'),
    ('service:frontend','Could I help with updates and refinements to your website?'),
])
async def test_vetted_grounded_alternatives_pass_mocked_gemini_without_rewriting(monkeypatch,identifier,wording):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')
    ctx=context();data=replace_claim(ctx,identifier,wording)
    Client,calls,closed=sdk(data)
    result,_=await write_proposal(ctx,Client)
    assert result.body==data['body'] and result.subject==data['subject']
    assert closed==[True] and len(calls)==2
    public=json.loads(calls[1]['contents'])
    assert wording in public['approved_fact_wordings'][identifier]
    assert calls[1]['config'].system_instruction==WRITER_GUIDANCE

@pytest.mark.parametrize('formatting',['case','line_wrap','metadata_period','nfc'])
def test_only_harmless_formatting_differences_are_normalized(formatting):
    ctx=context();data=written(ctx).model_dump()
    if formatting=='case':data['body']=data['body'].upper()
    if formatting=='line_wrap':data['body']=data['body'].replace('public website','public\n  website')
    if formatting=='metadata_period':data['claims'][0]['text']=data['claims'][0]['text'].removesuffix('.')
    if formatting=='nfc':
        profile=FreelancerProfile.model_validate({'service_ids':['frontend'],'public_details_confirmed':True,'projects':[
            {'id':'cafe','title':'Café Website','kind':'completed_project','service_ids':['frontend']}]})
        ctx=context(profile);data=written(ctx,with_profile=True).model_dump();data['body']=data['body'].replace('Café','Cafe\u0301')
    assert validate_written(data,ctx).body==data['body']

def test_repeated_verified_references_still_require_all_other_grounding():
    ctx=context();data=written(ctx).model_dump();data['claims'].append(dict(data['claims'][0]))
    assert validate_written(data,ctx).claims[-1].fact_id=='website_present'
    data['claims']=[claim for claim in data['claims'] if claim['fact_id']!='service:frontend']
    with pytest.raises(WritingValidationError) as caught:validate_written(data,ctx)
    assert caught.value.rule=='fact_references'

@pytest.mark.parametrize('courtesy',[
    'I appreciate your time.',
    'Would a brief conversation be useful?',
    'If this is helpful, we could discuss a next step.',
    'I would be happy to talk through options.',
    'Could reviewing image descriptions be a useful next step?',
    'I could suggest a focused review of image descriptions.',
    'Would your team have time for a brief conversation?',
    'If your team has time, we could discuss a next step.',
])
def test_non_factual_courtesies_proposals_and_questions_need_no_fake_fact_ids(courtesy):
    ctx=context();data=written(ctx).model_dump();data['body']+=' '+courtesy
    result=validate_written(data,ctx)
    assert result.body==data['body'] and all(c.text!=courtesy for c in result.claims)

@pytest.mark.parametrize('identifier,wording',[
    ('website_present','Your website is beautifully designed.'),
    ('website_present','Your business has five locations.'),
    ('website_present','I appreciate that you won a local award.'),
    ('website_present','You already have no public website for your business.'),
    ('finding:image_alt_missing','All images across your website lack alternative text.'),
    ('finding:image_alt_missing','Your customers cannot use your website.'),
    ('benefit:image_alt_missing','Image descriptions will improve your rankings.'),
    ('benefit:image_alt_missing','Could image descriptions guarantee more traffic?'),
    ('service:frontend','If useful, I could double your sales.'),
    ('service:frontend','You asked me to update your website.'),
])
def test_polite_conditional_or_question_forms_do_not_make_unsupported_claims_valid(identifier,wording):
    ctx=context();data=replace_claim(ctx,identifier,wording)
    with pytest.raises(WritingValidationError) as caught:validate_written(data,ctx)
    assert caught.value.rule=='fact_wording' and caught.value.reason=='unsupported_wording'

@pytest.mark.parametrize('extra,rule',[
    ('As we discussed, I could suggest a next step.','unsupported_relationship'),
    ("We've spoken before about your website.",'unsupported_relationship'),
    ('Your business has five locations.','unsupported_business_assertion'),
    ('Fixture Cafe has five locations.','unsupported_business_assertion'),
    ('Your restaurant serves a vegetarian menu.','unsupported_business_assertion'),
    ('Would your team have time for a brief conversation? Your team has a large budget.','unsupported_business_assertion'),
    ('I have worked with famous clients.','unsupported_experience_or_praise'),
    ('I previously helped another cafe.','unsupported_experience_or_praise'),
    ('Would you like guaranteed sales?','prohibited_claim'),
    ('If we work together, I will deliver a redesign.','unapproved_commitment'),
])
def test_unclaimed_prose_cannot_hide_relationships_business_facts_or_promises(extra,rule):
    ctx=context();data=written(ctx).model_dump();data['body']+=' '+extra
    with pytest.raises(WritingValidationError) as caught:validate_written(data,ctx)
    assert caught.value.rule==rule

@pytest.mark.anyio
@pytest.mark.parametrize('case,reason',[
    ('unknown_fact','unknown_fact'),('unsupported_wording','unsupported_wording'),('missing_span','claim_not_in_body'),
])
async def test_fact_wording_subreasons_are_sanitized_without_retaining_response(monkeypatch,capsys,case,reason):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')
    ctx=context();data=written(ctx).model_dump()
    if case=='unknown_fact':data['claims'][0]['fact_id']='PRIVATE SENTINEL'
    if case=='unsupported_wording':data['claims'][0]['text']='PRIVATE SENTINEL'
    if case=='missing_span':data['body']=data['body'].replace(ctx['approved_facts']['website_present'],'PRIVATE SENTINEL')
    Client,calls,closed=sdk(data)
    with pytest.raises(GeminiFailure) as caught:await write_proposal(ctx,Client)
    assert caught.value.diagnostics=={'stage':'validation','rule':'fact_wording','reason':reason,**WRITER_VERSIONS}
    assert 'PRIVATE SENTINEL' not in str(caught.value)+json.dumps(caught.value.diagnostics)
    assert capsys.readouterr()==('','') and len(calls)==2 and closed==[True]

def test_diagnostics_never_accept_model_supplied_reason_values():
    for reason in ('PRIVATE SENTINEL',[],{'text':'PRIVATE CONTENT'}):
        assert safe_writer_diagnostics({'stage':'validation','rule':'fact_wording','reason':reason})=={'stage':'validation','rule':'fact_wording'}

@pytest.mark.anyio
async def test_natural_approved_prose_is_revalidated_and_saved_without_overwriting_history(database,monkeypatch):
    from app.intelligence.drafts import compose
    _,identity_id,_=await enriched(database,monkeypatch)
    with Session(database) as s:
        a=assess(s,s.get(BusinessIdentity,identity_id));s.flush();aid=a.id
        older=compose(a,'email');older.saved=True;s.add(older);s.commit();older_id=older.id
        original=(older.subject,older.body,older.evidence,older.updated_at)
    confirm_writer(database,monkeypatch)
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_API_KEY','TEST_KEY')
    outputs=[]
    async def mock(ctx):
        data=replace_claim(ctx,'service:frontend','I could help with updates and refinements to your website.')
        outputs.append(data);return {'subject':data['subject'],'body':data['body']},{'input_tokens':12,'output_tokens':40}
    manager=AIManager(database,writer_provider=mock)
    job=await manager.start(aid,'draft','email');await asyncio.gather(*list(manager.tasks.values()))
    completed=manager.read(job['id']);assert completed['status']=='complete'
    with Session(database) as s:
        row=s.get(OutreachDraft,completed['result']['draft_id'])
        assert row.body==outputs[0]['body'] and row.subject==outputs[0]['subject'] and not row.saved
        assert row.evidence['review_required'] and row.evidence['writer_version']=='human-reviewed-v1'
        previous=s.get(OutreachDraft,older_id)
        assert (previous.subject,previous.body,previous.evidence,previous.updated_at)==original and previous.saved
        assert s.scalar(select(func.count()).select_from(OutreachDraft))==2
