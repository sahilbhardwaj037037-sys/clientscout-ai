"""Offline extraction comparisons and explicit, unverified local observations."""
import pytest
from sqlalchemy.orm import Session
from app.intelligence.contacts import ContactPage, extract_contacts
from app.models.intelligence import ContactMethod, Enrichment
from test_intelligence import enriched, create_identity


@pytest.mark.parametrize('html,emails,protected,visible', [
    ('<footer>info@example.com</footer>', [], 0, True),
    ('<footer>info&#64;example.com</footer>', [], 0, True),
    ('<footer><a href="mailto:info@example.com">Email</a></footer>', ['info@example.com'], 0, False),
    ('<footer><a href="mailto:booking&#64;example.com">Booking</a></footer>', ['booking@example.com'], 0, False),
    ('<footer><a href="/cdn-cgi/l/email-protection"><span class="__cf_email__" data-cfemail="REDACTED">[email protected]</span></a></footer><script src="/cdn-cgi/scripts/fixture/cloudflare-static/email-decode.min.js"></script>', [], 1, False),
    ('<footer id="contact"></footer><script>document.getElementById("contact").innerHTML="info@example.com"</script>', [], 0, False),
    # A hypothetical post-render DOM snapshot, not the retained HAPPY DOM.
    ('<footer id="contact"><a href="mailto:info@example.com">info@example.com</a></footer>', ['info@example.com'], 0, True),
])
def test_offline_html_extraction_matrix(html, emails, protected, visible):
    page=ContactPage();page.feed(html)
    assert [v['value'] for v in extract_contacts(page,'https://example.com/','Fixture Cafe') if v['kind']=='email']==emails
    assert len(page.protected_email_links)==protected
    assert ('info@example.com' in ''.join(page.text))==visible


def payload(**overrides):
    return dict(email='booking@other.example.com',source_url='https://example.com/about',public_business_observed=True,**overrides)


@pytest.mark.anyio
async def test_manual_observation_is_attributed_review_only_persistent_and_local(client,database,monkeypatch):
    lead,_,job=await enriched(database,monkeypatch)
    # Once the existing fixture source is available, prohibit every network path.
    import httpx
    def blocked(*args,**kwargs):raise AssertionError('Manual entry must not fetch a source.')
    monkeypatch.setattr(httpx.AsyncClient,'get',blocked)
    path=f'/api/intelligence/targets/lead/{lead}'
    before=client.get(path).json()
    result=client.post(path+'/manual-email',json=payload())
    assert result.status_code==201, result.text
    row=result.json()
    assert row['status']=='needs_review' and row['domain_association']=='different_domain_unverified'
    assert row['source_kind']=='manual_public_observation' and row['source_url']=='https://example.com/about'
    assert client.post(path+'/manual-email',json=payload()).json()['id']==row['id']
    recovered=client.get(path).json()
    assert recovered['manual_contacts']==[row]
    assert recovered['enrichment']==before['enrichment'] and recovered['assessment']==before['assessment']
    matched=client.post(path+'/manual-email',json={**payload(),'email':'booking@example.com'}).json()
    assert matched['status']=='needs_review' and matched['domain_association']=='matches_website_domain'
    with Session(database) as s:
        assert s.get(Enrichment,job).report==before['enrichment']['report']
        stored=s.get(ContactMethod,row['id'])
        assert stored.status=='needs_review' and stored.provenance['fetched_at'] is None
    assert client.post(path+'/manual-email',json=payload(),headers={'Origin':'https://evil.example'}).status_code==403


@pytest.mark.anyio
async def test_manual_observation_rejects_invalid_unacknowledged_or_unattributed_input(client,database,monkeypatch):
    lead,_,_=await enriched(database,monkeypatch)
    path=f'/api/intelligence/targets/lead/{lead}/manual-email'
    cases=[{'public_business_observed':v} for v in (False,1,'true')]+[
        {'email':'john.smith@example.com'}, {'email':'mailto:info@example.com'},
        {'email':'info@example.com?subject=Hello'}, {'email':'info@example.com\nBcc:x@example.com'},
        {'source_url':'https://unrelated.example/about'}, {'source_url':'https://example.com/?token=secret'},
        {'source_url':'https://example.com/cdn-cgi/l/email-protection'},
        {'source_url':'https://example.com/%63dn-cgi/l/email-protection'},
        {'source_url':'https://user:password@example.com/'},
    ]
    for override in cases:
        response=client.post(path,json={**payload(),**override})
        assert response.status_code==422, (override,response.text)
    missing=payload();missing.pop('public_business_observed')
    assert client.post(path,json=missing).status_code==422
    assert client.get(f'/api/intelligence/targets/lead/{lead}').json()['manual_contacts']==[]
    with Session(database) as s:
        job=s.query(Enrichment).first();job.report={**job.report,'identity':{'status':'needs_review','official':False}};s.commit()
    assert client.post(path,json=payload()).status_code==422


def test_manual_observation_requires_existing_source(client,database):
    lead,_=create_identity(database)
    assert client.post(f'/api/intelligence/targets/lead/{lead}/manual-email',json=payload()).status_code==422
