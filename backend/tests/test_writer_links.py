from app.intelligence.writer import WRITER_VERSIONS
"""Synthetic outputs only: the rejected job #8 response was not retained."""
import json
import re
import pytest
from pydantic import ValidationError
from app.intelligence.writer import validate_written,WritingValidationError,safe_writer_diagnostics
from app.providers.gemini import write_annotated_proposal as write_proposal,GeminiFailure
from app.schemas.intelligence import FreelancerProfile,AIWrittenDraft
from test_ai_writer import context,sdk
from writer_helpers import written


def link_context(portfolio='https://portfolio.example.com/',instagram=''):
    return context(FreelancerProfile(service_ids=['frontend'],public_details_confirmed=True,
        portfolio_url=portfolio,instagram_url=instagram))


@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setattr('app.providers.gemini.GEMINI_API_KEY','TEST_SECRET_KEY')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')


@pytest.mark.anyio
@pytest.mark.parametrize('profile_url,body_url,declared',[
    ('https://portfolio.example.com/','https://portfolio.example.com/','https://portfolio.example.com/'),
    ('https://portfolio.example.com/','https://portfolio.example.com','https://portfolio.example.com/'),
    ('https://portfolio.example.com/','https://PORTFOLIO.example.com:443/','https://portfolio.example.com'),
    ('https://portfolio.example.com/work!','https://portfolio.example.com/work!','https://portfolio.example.com/work!'),
    ('https://portfolio.example.com/work(v2)','https://portfolio.example.com/work(v2)','https://portfolio.example.com/work(v2)'),
    ('https://portfolio.example.com/work.','https://portfolio.example.com/work.','https://portfolio.example.com/work.'),
    ("https://portfolio.example.com/sam's-work","https://portfolio.example.com/sam's-work","https://portfolio.example.com/sam's-work"),
    ('https://www.fiverr.com/sample_creator','https://www.fiverr.com/sample_creator','https://www.fiverr.com/sample_creator'),
    ('https://www.upwork.com/freelancers/~sample','https://www.upwork.com/freelancers/~sample','https://www.upwork.com/freelancers/~sample'),
])
async def test_approved_links_pass_mocked_provider_without_rewriting(mock_settings,profile_url,body_url,declared):
    ctx=link_context(profile_url);data=written(ctx).model_dump()
    data['body']+=' You can explore my portfolio here: '+body_url;data['used_links']=[declared]
    Client,calls,closed=sdk(data)
    result,_=await write_proposal(ctx,Client)
    assert result.body==data['body'] and result.used_links==[declared]
    assert len(calls)==2 and closed==[True]


def test_reproduced_old_parser_false_positives():
    for approved,body in [('https://portfolio.example.com/','https://portfolio.example.com'),
                          ('https://portfolio.example.com/work!','https://portfolio.example.com/work!'),
                          ('https://portfolio.example.com/work(v2)','https://portfolio.example.com/work(v2)')]:
        old=set(u.rstrip('.,;!?)') for u in re.findall(r'https?://[^\s<>\[\]"\)]+',body))
        assert old!={approved}
        ctx=link_context(approved);data=written(ctx).model_dump()
        data['body']+=' Explore my portfolio: '+body;data['used_links']=[approved]
        assert validate_written(data,ctx).body==data['body']


@pytest.mark.parametrize('wrapper',['{}','{}.', '({})', '{}!', '{};', '"{}"', "'{}'"])
def test_instagram_and_repeated_links_allow_sentence_punctuation(wrapper):
    url='https://www.instagram.com/sample.studio/'
    ctx=link_context(instagram=url);data=written(ctx).model_dump()
    data['body']+=' Explore my professional Instagram: '+wrapper.format(url)+' '+wrapper.format(url)
    data['used_links']=[url,url]
    assert validate_written(data,ctx).used_links==[url,url]


@pytest.mark.anyio
@pytest.mark.parametrize('portfolio',['','https://portfolio.example.com/'])
async def test_no_links_needs_empty_declaration_even_with_available_profile(mock_settings,portfolio):
    ctx=link_context(portfolio);data=written(ctx).model_dump()
    assert data['used_links']==[]
    Client,_,_=sdk(data)
    result,_=await write_proposal(ctx,Client)
    assert result.used_links==[]


@pytest.mark.anyio
@pytest.mark.parametrize('case,reason',[
    ('body_only','missing_declaration'),('declaration_only','unused_declaration'),('different_approved_links','url_mismatch')])
async def test_declaration_mismatches_reject_with_content_free_diagnostics(mock_settings,capsys,case,reason):
    portfolio='https://portfolio.example.com/private-sentinel';instagram='https://www.instagram.com/sample.studio/'
    ctx=link_context(portfolio,instagram);data=written(ctx).model_dump()
    if case!='declaration_only':data['body']+=' Explore my portfolio: '+portfolio
    if case=='declaration_only':data['used_links']=[portfolio]
    if case=='different_approved_links':data['used_links']=[instagram]
    Client,calls,closed=sdk(data)
    with pytest.raises(GeminiFailure) as caught:await write_proposal(ctx,Client)
    assert caught.value.diagnostics=={'stage':'validation','rule':'link_declarations','reason':reason,**WRITER_VERSIONS}
    assert 'private-sentinel' not in str(caught.value)+json.dumps(caught.value.diagnostics)
    assert len(calls)==2 and closed==[True] and capsys.readouterr()==('','')


@pytest.mark.parametrize('url',[
    'https://invented.example.com/', 'https://portfolio.example.com.evil.com/Work',
    'http://portfolio.example.com/Work','https://portfolio.example.com/work',
    'https://portfolio.example.com/Work/','https://portfolio.example.com/Work?tracking=1',
    'https://portfolio.example.com/Work#fragment','https://user@portfolio.example.com/Work',
    'https://portfolio.example.com:444/Work','https://portfolio.example.com/%57ork',
])
@pytest.mark.parametrize('declared',[True,False])
def test_unapproved_urls_never_pass_as_equivalent(url,declared):
    ctx=link_context('https://portfolio.example.com/Work');data=written(ctx).model_dump()
    data['body']+=' Explore my portfolio: '+url
    if declared:data['used_links']=[url]
    with pytest.raises(WritingValidationError) as caught:validate_written(data,ctx)
    assert caught.value.rule=='link_allowlist'


def test_no_profile_context_cannot_accept_profile_links():
    ctx=context();data=written(ctx).model_dump()
    data['body']+=' Explore my portfolio: https://portfolio.example.com/'
    data['used_links']=['https://portfolio.example.com/']
    with pytest.raises(WritingValidationError) as caught:validate_written(data,ctx)
    assert caught.value.rule=='link_allowlist'


def test_links_in_subject_are_also_declared_and_do_not_mask_neighboring_claims():
    ctx=link_context();url=ctx['portfolio_url'];data=written(ctx).model_dump()
    data['subject']='Portfolio: '+url;data['used_links']=[url]
    assert validate_written(data,ctx).subject==data['subject']
    data['body']+=' Guaranteed sales.'
    with pytest.raises(WritingValidationError) as caught:validate_written(data,ctx)
    assert caught.value.rule=='prohibited_claim'


def test_fiverr_and_upwork_have_no_dedicated_profile_fields():
    for field in ('fiverr_url','upwork_url'):
        with pytest.raises(ValidationError):FreelancerProfile.model_validate({field:'https://example.com/'})


def test_declaration_schema_and_diagnostic_contract():
    schema=AIWrittenDraft.model_json_schema()
    assert 'used_links' in schema['required']
    assert 'Use [] when no links appear' in schema['properties']['used_links']['description']
    assert safe_writer_diagnostics({'stage':'validation','rule':'link_declarations','reason':'https://private.example.com/'})=={'stage':'validation','rule':'link_declarations'}
