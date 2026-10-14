"""Deterministic provider, security, lifecycle and licensed persistence coverage."""
import asyncio
from datetime import timedelta
import json
from urllib.parse import parse_qs
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auditing.network import AuditFailure, Fetched
from app.discovery.manager import DiscoveryManager
from app.models.discovery import DiscoverySearch, DiscoveredBusiness
from app.models.lead import now
from app.providers.overpass import OverpassProvider, ProviderFailure, business_query, parse_businesses, parse_document
from app.schemas.discovery import SearchCreate

CENTER = {'latitude': 52.2053, 'longitude': 0.1218, 'label': 'Fixture coordinates'}
def query(**kw): return SearchCreate(location='52.2053, 0.1218', category='cafe', **kw)
def node(identifier=1, **tags): return {'type':'node', 'id':identifier, 'lat':52.2053, 'lon':0.1218, 'tags':{'amenity':'cafe', 'name':'Fixture cafe', **tags}}
def result(elements=None, **kw): return dict(parse_businesses({'elements': elements if elements is not None else [node()]}, query(**kw), CENTER, 20), cache_hit=False)
async def progress(_): pass

class Fetcher:
    def __init__(self, responses): self.responses = list(responses); self.calls = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def post(self, endpoint, **kw):
        self.calls.append((endpoint, kw))
        response = self.responses.pop(0)
        if isinstance(response, Exception): raise response
        return response

def response(status=200, data=None, headers=None): return Fetched('https://overpass-api.de/api/interpreter', status, headers or {}, json.dumps(data or {'elements':[node()]}).encode(), 0, now().isoformat(), [])

@pytest.mark.parametrize('fields', [
    {'location':''}, {'location':'a'}, {'location':'91, 0'}, {'location':'0, 181'}, {'location':'nan, 2'},
    {'location':'https://example.com'}, {'location':'Lon\ndon'}, {'location':'x'*121},
    {'category':''}, {'category':'x'*81}, {'category':'https://example.com'}, {'category':'ca\xfe\x00'},
    {'limit':0}, {'limit':51}, {'limit':True}, {'limit':'10'}, {'provider':'google'}, {'website_filter':'fake'}, {'extra':'fake'},
])
def test_discovery_validation(fields):
    with pytest.raises(ValidationError): SearchCreate.model_validate({'location':'London', 'category':'cafe', **fields})

def test_query_escapes_literal_input_and_enforces_bounds():
    statement, cap = business_query('A";out;[.*', 52.2, .1, 50)
    assert 'around:2000,52.2000000,0.1000000' in statement and 'out center 200' in statement and cap == 200
    assert '\\"' in statement and '\\\\[' in statement and '\\\\.' in statement
    assert business_query('cafés', 0, 0, 10)[0].count('["amenity"="cafe"]') == 1

@pytest.mark.parametrize('body', [b'not json', b'null', b'{"elements":{}}', b'{"elements":[],"remark":"timed out"}', json.dumps({'elements':[{}]*1001}).encode()])
def test_invalid_or_partial_provider_document_is_error(body):
    with pytest.raises(ProviderFailure): parse_document(body)

def test_parse_nullable_websites_unsafe_values_and_evidence():
    values = [node(1), node(2,name='Unsafe fixture',website='http://127.0.0.1/'), node(3,name='Valid fixture',website='example.com')]
    report = result(values)
    assert [x['website_url'] for x in report['items']] == [None,None,'https://example.com/']
    assert report['items'][1]['warnings'] and '127.0.0.1' not in json.dumps(report)
    assert all(x['unverified'] and x['licence'] == 'ODbL-1.0' and x['fetched_at'] for x in report['items'])
    assert report['items'][0]['location'] is None
    assert len(result(values,website_filter='with')['items']) == 1
    assert len(result(values,website_filter='without')['items']) == 2

def test_dedup_preserves_branches_and_parses_way_centers():
    branch = node(3,website='example.com'); branch['lat'] += .005
    way = {'type':'way','id':4,'center':{'lat':52.206,'lon':.122},'tags':{'amenity':'cafe'}}
    report = result([node(1,website='example.com'),node(1),node(2,website='example.com'),branch,way])
    assert len(report['items']) == 3 and report['duplicates_removed'] == 2
    assert report['items'][2]['name'] is None and report['items'][2]['coordinate_kind'] == 'OSM object bounding-box center'

@pytest.mark.parametrize('invalid', [None, {}, node(True), dict(node(),lat=True), dict(node(),lat=float('nan')), dict(node(),lon=180), node(1,amenity='school'), dict(node(),type='fake')])
def test_invalid_or_out_of_scope_records_are_skipped(invalid):
    report = result([invalid]); assert report['items'] == [] and report['invalid_records'] == 1

@pytest.mark.parametrize('endpoint', ['http://example.com','https://127.0.0.1/','https://localhost/','https://user:pass@example.com/','https://example.com:9000/','https://example.com/?token=x','https://example.com/#fragment'])
def test_provider_endpoint_is_https_public_and_has_no_credentials(endpoint):
    with pytest.raises(ValueError): OverpassProvider(endpoint)

@pytest.mark.anyio
async def test_provider_coordinates_cache_and_encoded_server_side_post():
    fetcher = Fetcher([response()]); cache = {}
    provider = OverpassProvider('https://overpass-api.de/api/interpreter',lambda:fetcher)
    first = await provider.search(query(),progress,cache.get,cache.__setitem__)
    second = await provider.search(query(),progress,cache.get,cache.__setitem__)
    assert len(fetcher.calls) == 1 and first['cache_hit'] is False and second['cache_hit'] is True
    assert first['fetched_at'] == second['fetched_at']
    _, sent = fetcher.calls[0]
    assert sent['max_bytes'] == 8*1024*1024 and sent['timeout'] == 35
    assert 'around:2000' in parse_qs(sent['content'].decode())['data'][0] and 'ClientScoutAI' in sent['user_agent']

@pytest.mark.anyio
@pytest.mark.parametrize('elements,message', [([], 'No exact'), ([{'type':'node','id':1,'lat':52,'lon':0,'tags':{'place':'city','name':'Elsewhere'}}], 'No exact'), ([{'type':'node','id':i,'lat':52,'lon':0,'tags':{'place':'city','name':'London'}} for i in [1,2]], 'ambiguous')])
async def test_location_resolution_does_not_invent_or_choose_ambiguous_places(elements,message):
    fetcher = Fetcher([response(data={'elements':elements})]); provider = OverpassProvider('https://example.com/',lambda:fetcher)
    with pytest.raises(ProviderFailure,match=message): await provider.search(SearchCreate(location='London',category='cafe'),progress,lambda _:None,lambda *args:None)
    assert len(fetcher.calls) == 1

@pytest.mark.anyio
async def test_exact_place_is_resolved_and_attributed_before_business_query(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.providers.overpass.asyncio.sleep',sleep)
    place = {'type':'node','id':10,'lat':52.2053,'lon':.1218,'tags':{'place':'city','name':'Cambridge'}}
    fetcher = Fetcher([response(data={'elements':[place]}),response()]); cache={}
    provider = OverpassProvider('https://example.com/',lambda:fetcher)
    report = await provider.search(SearchCreate(location='Cambridge',category='cafe'),progress,cache.get,cache.__setitem__)
    assert len(fetcher.calls) == 2 and report['center']['source_url'].endswith('node/10') and len(cache)==2

@pytest.mark.anyio
@pytest.mark.parametrize('status,header,expected_calls,cooldown', [(429,None,1,30),(503,'7200',1,7200),(429,'5',2,5),(503,'bad',1,3600),(429,'999999999999',1,999999999999),(302,None,1,60)])
async def test_backoff_retry_budget_and_no_redirect_or_provider_substitution(monkeypatch,status,header,expected_calls,cooldown):
    waits=[]
    async def sleep(seconds): waits.append(seconds)
    monkeypatch.setattr('app.providers.overpass.asyncio.sleep',sleep)
    fetcher = Fetcher([response(status,headers={'retry-after':header} if header else {}),response(status,headers={'retry-after':header} if header else {})])
    provider = OverpassProvider('https://example.com/')
    with pytest.raises(ProviderFailure) as error: await provider.request(fetcher,'query',progress)
    assert len(fetcher.calls)==expected_calls and error.value.retry_seconds==cooldown and waits==([5] if expected_calls==2 else [])

@pytest.mark.anyio
@pytest.mark.parametrize('failure',[AuditFailure('Request timed out.','timeout'), AuditFailure('Response exceeds body limit.','body_limit'), AuditFailure('Blocked non-public IP.','unsafe_url')])
async def test_network_security_timeout_and_size_failures_are_actionable(failure):
    with pytest.raises(ProviderFailure,match='network request stopped'):
        await OverpassProvider('https://example.com/').request(Fetcher([failure]),'query',progress)

class Provider:
    id='osm_overpass'
    async def search(self,q,p,get,put): await p('Fixture source parsed'); return result()

@pytest.mark.anyio
async def test_manager_persistence_cooldown_cache_and_restart(database):
    manager = DiscoveryManager(database,Provider()); created = await manager.start(query())
    await asyncio.gather(*list(manager.tasks.values()))
    reopened = DiscoveryManager(database,Provider()); assert reopened.read(created.id).result['items'][0]['website_url'] is None
    manager.cache_put('fixture',{'real':'fixture'}); assert reopened.cache_get('fixture') == {'real':'fixture'}
    with pytest.raises(HTTPException) as error: await reopened.start(query())
    assert error.value.status_code==429 and 'Retry-After' in error.value.headers
    with Session(database) as session:
        session.get(DiscoverySearch,created.id).status='running'; session.commit()
    reopened.recover(); assert reopened.read(created.id).status=='interrupted' and reopened.tasks=={}

@pytest.mark.anyio
async def test_cancel_and_single_active_search_never_produce_results(database):
    started=asyncio.Event(); stopped=asyncio.Event()
    class Slow:
        async def search(self,*args):
            started.set()
            try: await asyncio.sleep(100)
            finally: stopped.set()
    manager=DiscoveryManager(database,Slow()); created=await manager.start(query()); await started.wait()
    with pytest.raises(HTTPException) as error: await manager.start(query())
    assert error.value.status_code==429
    record=await manager.cancel(created.id); assert record.status=='cancelled' and record.result is None and stopped.is_set()

@pytest.mark.anyio
async def test_daily_budget_and_disabled_source(database,monkeypatch):
    with Session(database) as session:
        for _ in range(20): session.add(DiscoverySearch(query=query().model_dump(),status='complete',cooldown_until=now()-timedelta(seconds=1)))
        session.commit()
    manager=DiscoveryManager(database,Provider())
    with pytest.raises(HTTPException,match='20 searches'): await manager.start(query())
    monkeypatch.setattr('app.discovery.manager.DISCOVERY_ENABLED',False)
    with pytest.raises(HTTPException) as disabled: await manager.start(query())
    assert disabled.value.status_code==503

@pytest.mark.anyio
async def test_provider_failure_persists_retry_after_without_fake_results(database):
    class Limited:
        async def search(self,*args): raise ProviderFailure('HTTP 429',604800)
    manager=DiscoveryManager(database,Limited()); created=await manager.start(query()); await asyncio.gather(*list(manager.tasks.values()))
    record=manager.read(created.id); assert record.status=='error' and record.result is None and record.cooldown_until > now()+timedelta(days=6)


def completed_search(database):
    with Session(database) as session:
        row=DiscoverySearch(query=query().model_dump(),status='complete',result=result(),cooldown_until=now())
        session.add(row); session.commit(); return row.id

def test_api_review_save_missing_website_dedup_and_real_dashboard(client,database):
    identifier=completed_search(database)
    assert client.get('/api/discovery/config').json()['max_limit']==50
    assert client.get('/api/discovery/searches').json()['total']==1
    assert client.get(f'/api/discovery/searches/{identifier}').json()['status']=='complete'
    assert client.get('/api/discovery/saved').json()['total']==0
    payload={'source_ids':['node/1'],'licence_confirmed':True}
    first=client.post(f'/api/discovery/searches/{identifier}/save',json=payload).json()
    assert first['saved']==1 and first['items'][0]['website_url'] is None
    second=client.post(f'/api/discovery/searches/{identifier}/save',json=payload).json(); assert second['saved']==0 and second['existing']==1
    assert client.get('/api/discovery/saved').json()['total']==1
    metrics=client.get('/api/dashboard').json(); assert metrics['leads_found']==0 and metrics['discovered_businesses']==1
    with Session(database) as session: assert session.scalar(select(DiscoveredBusiness)).data['source_id']=='node/1'
    assert client.get('/api/leads').json()['total']==0

@pytest.mark.parametrize('payload',[{'source_ids':['node/999'],'licence_confirmed':True},{'source_ids':['node/1'],'licence_confirmed':False},{'source_ids':['node/1'],'licence_confirmed':True,'website_url':'https://fake.example'}])
def test_api_rejects_forged_or_unlicensed_selections(client,database,payload):
    identifier=completed_search(database)
    assert client.post(f'/api/discovery/searches/{identifier}/save',json=payload).status_code==422
    assert client.get('/api/discovery/saved').json()['total']==0

def test_api_license_guard_origin_and_pagination(client,database):
    identifier=completed_search(database)
    with Session(database) as session:
        row=session.get(DiscoverySearch,identifier); data=row.result; data['items'][0]['licence']='unknown'; row.result=dict(data); from sqlalchemy.orm.attributes import flag_modified; flag_modified(row,'result'); session.commit()
    assert client.post(f'/api/discovery/searches/{identifier}/save',json={'source_ids':['node/1'],'licence_confirmed':True}).status_code==422
    assert client.post('/api/discovery/searches',json=query().model_dump(),headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/discovery/saved?limit=101').status_code==422
    assert client.get('/api/discovery/searches/999').status_code==404
    assert client.post('/api/discovery/searches/999/cancel').status_code==404
    assert client.post('/api/discovery/searches',json={'location':'London','category':'cafe','limit':51}).status_code==422

@pytest.mark.anyio
async def test_cancel_before_worker_starts_and_shutdown_interrupts(database):
    class Slow:
        async def search(self,*args): await asyncio.sleep(100)
    manager=DiscoveryManager(database,Slow()); first=await manager.start(query())
    assert (await manager.cancel(first.id)).status=='cancelled'
    with Session(database) as session: session.get(DiscoverySearch,first.id).cooldown_until=now()-timedelta(seconds=1); session.commit()
    second=await manager.start(query()); await asyncio.sleep(0); await manager.shutdown()
    assert manager.read(second.id).status=='interrupted' and manager.read(second.id).result is None

@pytest.mark.anyio
async def test_expired_cache_and_provider_timeout_do_not_claim_success(database):
    class TimedOut:
        async def search(self,*args): raise TimeoutError
    manager=DiscoveryManager(database,TimedOut()); manager.cache_put('expired',{'value':'old'})
    from app.models.discovery import DiscoveryCache
    with Session(database) as session: session.get(DiscoveryCache,'expired').expires_at=now()-timedelta(seconds=1); session.commit()
    assert manager.cache_get('expired') is None
    created=await manager.start(query()); await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(created.id).status=='error' and manager.read(created.id).result is None

def test_api_start_injected_source_and_persistence_after_reopen(client,database):
    client.app.state.discovery_manager.provider=Provider()
    created=client.post('/api/discovery/searches',json=query().model_dump())
    assert created.status_code==202
    identifier=created.json()['id']
    # TestClient yields scheduling to the real manager between requests.
    assert client.get(f'/api/discovery/searches/{identifier}').json()['status']=='complete'
    assert DiscoveryManager(database,Provider()).read(identifier).result['items'][0]['source_id']=='node/1'
    assert client.post(f'/api/discovery/searches/{identifier}/save',json={'source_ids':['node/1'],'licence_confirmed':True}).json()['saved']==1
