"""Regression for lost Overpass remarks, country resolution and safe area planning."""
import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs
import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.session import make_engine
from app.discovery.manager import DiscoveryManager
from app.models.discovery import DiscoverySearch
from app.providers.locations import parse_location,location_query,boundary_is_small
from app.providers.overpass import OverpassProvider,ProviderFailure,business_query,parse_businesses,resolve_location
from app.schemas.discovery import SearchCreate
from test_discovery import Fetcher,response,node,CENTER,progress

COUNTRY={'type':'area','id':3600000001}
def place(identifier=1,name='London'):
    return {'type':'node','id':identifier,'lat':52.2053,'lon':.1218,'tags':{'name':name,'place':'city'}}
def boundary(name='London',large=False):
    return {'type':'relation','id':100,'bounds':dict(zip(['minlat','minlon','maxlat','maxlon'],[51,-1,53,1] if large else [52.2,.11,52.21,.13])),'tags':{'name':name,'boundary':'administrative','admin_level':'8'}}
def metadata(*elements): return response(data={'elements':list(elements)})
def fields(**kw): return SearchCreate(location='London, UK',category='restaurants',**kw)

@pytest.mark.parametrize('location',['London, ZZ','London, Imaginary country','London, UK, extra','osm:relation/0','osm:relation/abc','osm:node/1','osm:relation/1);out;'])
def test_invalid_location_is_rejected_before_provider_work(location):
    with pytest.raises(ValidationError): SearchCreate(location=location,category='restaurant')

@pytest.mark.parametrize('field,value',[('radius_metres',100000),('radius_metres',0),('radius_metres','500'),('search_scope','entire_country')])
def test_unbounded_search_options_are_rejected(field,value):
    with pytest.raises(ValidationError): SearchCreate.model_validate({'location':'London, UK','category':'restaurant',field:value})

def test_qualified_location_query_has_country_scope_exact_labels_and_metadata_cap():
    parsed=parse_location('London, UK'); assert parsed.label=='London' and parsed.country=='GB'
    statement=location_query(parsed)
    assert '["ISO3166-1"="GB"]' in statement and 'node(area.country)["name"="London"]' in statement
    assert '["name"~' not in statement and 'London, UK' not in statement and 'out tags bb 11' in statement
    assert 'amenity' not in statement
    assert parse_location('London, United Kingdom')==parsed
    assert 'rel(100)' in location_query(parse_location('osm:relation/100'))

@pytest.mark.parametrize('category',['restaurant','restaurants',' Restaurants '])
def test_restaurants_map_to_amenity_not_keyword(category):
    q=SearchCreate(location='52.2053, .1218',category=category,radius_metres=500)
    statement,_=business_query(q.category,52.2053,.1218,q.limit,q.radius_metres)
    assert '["amenity"="restaurant"]' in statement and '["name"~' not in statement and '(around:500,' in statement
    report=parse_businesses({'elements':[node(amenity='restaurant')]},q,CENTER,20)
    assert len(report['items'])==1 and report['radius_metres']==500

@pytest.mark.anyio
@pytest.mark.parametrize('status,body,code',[ (200,{'elements':[],'remark':'runtime error: Query timed out after 15 seconds.'},'query_timeout'),(200,{'elements':[],'remark':'runtime error: ran out of memory.'},'query_memory'),(400,'parse error: unknown token','query_syntax'),(504,'Gateway timeout or capacity','provider_capacity'),(429,{},'rate_limit'),(503,{},'provider_unavailable'),(200,{'elements':[],'remark':'some unknown provider failure'},'provider_query_error')])
async def test_http_and_body_evidence_differentiate_actual_failure(status,body,code):
    raw=response(status,data=body if isinstance(body,dict) else None)
    if isinstance(body,str): raw.body=body.encode()
    records=[]
    async def capture(message,diagnostic=None):
        if diagnostic: records.append(diagnostic)
    with pytest.raises(ProviderFailure): await OverpassProvider('https://example.com/').request(Fetcher([raw]),'bounded statement',capture,stage='location_resolution')
    assert records[0]['http_status']==status and records[0]['code']==code and records[0]['response_bytes']==len(raw.body)
    assert records[0]['query']=='bounded statement' and records[0]['query_sha256'] and records[0]['body_excerpt']
    if code!='rate_limit': assert 'HTTP 429' not in records[0]['hint']

@pytest.mark.anyio
async def test_diagnostics_are_redacted_bounded_and_persisted_on_failure(database):
    remark='runtime error: Query timed out; token=secret https://user:password@example.com/private '+('x'*2000)
    fetcher=Fetcher([response(data={'elements':[],'remark':remark})])
    manager=DiscoveryManager(database,OverpassProvider('https://example.com/',lambda:fetcher))
    created=await manager.start(fields()); await asyncio.gather(*list(manager.tasks.values()))
    run=manager.read(created.id)
    assert run.status=='error' and run.result is None and len(run.diagnostics)==1
    trace=run.diagnostics[0]
    assert trace['stage']=='location_resolution' and trace['http_status']==200 and trace['code']=='query_timeout'
    assert len(trace['provider_remark'])<=1000 and len(trace['body_excerpt'])<=1200 and 'password' not in json.dumps(trace) and 'token=secret' not in json.dumps(trace)
    with Session(database) as session: assert session.get(DiscoverySearch,created.id).diagnostics[0]['query_sha256']==trace['query_sha256']

@pytest.mark.anyio
async def test_success_diagnostics_do_not_copy_raw_business_data():
    records=[]
    async def capture(message,diagnostic=None):
        if diagnostic: records.append(diagnostic)
    await OverpassProvider('https://example.com/').request(Fetcher([response()]),'query',capture)
    assert records[0]['elements_returned']==1 and 'body_excerpt' not in records[0] and 'Fixture cafe' not in json.dumps(records)

@pytest.mark.anyio
async def test_country_ambiguity_blocks_business_fetches():
    fetcher=Fetcher([metadata(COUNTRY,place(1),place(2))])
    with pytest.raises(ProviderFailure,match='ambiguous'):
        await OverpassProvider('https://example.com/',lambda:fetcher).search(fields(),progress,lambda _:None,lambda *args:None)
    assert len(fetcher.calls)==1

@pytest.mark.parametrize('elements',[[place()],[COUNTRY,place(1),dict(COUNTRY,id=3600000002)]])
def test_missing_or_ambiguous_country_area_is_not_silently_ignored(elements):
    with pytest.raises(ProviderFailure,match='exactly one country area'): resolve_location({'elements':elements},parse_location('London, UK'))

@pytest.mark.anyio
async def test_large_boundary_explicit_mode_never_sends_city_wide_poi_query(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.providers.overpass.asyncio.sleep',sleep)
    fetcher=Fetcher([metadata(COUNTRY,boundary(large=True))])
    with pytest.raises(ProviderFailure) as error:
        await OverpassProvider('https://example.com/',lambda:fetcher).search(fields(search_scope='boundary'),progress,lambda _:None,lambda *args:None)
    assert error.value.code=='area_too_large' and len(fetcher.calls)==1
    assert 'amenity' not in parse_qs(fetcher.calls[0][1]['content'].decode())['data'][0]

@pytest.mark.anyio
async def test_auto_large_boundary_falls_back_to_bounded_sample_only(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.providers.overpass.asyncio.sleep',sleep)
    # Nearby query uses the actual source bounds center; no invented location.
    poi=node(amenity='restaurant'); poi['lat']=52;poi['lon']=0
    fetcher=Fetcher([metadata(COUNTRY,boundary(large=True)),metadata(poi)])
    result=await OverpassProvider('https://example.com/',lambda:fetcher).search(fields(radius_metres=500),progress,lambda _:None,lambda *args:None)
    statement=parse_qs(fetcher.calls[1][1]['content'].decode())['data'][0]
    assert '(around:500,' in statement and '(area.target)' not in statement
    assert result['search_scope']=='nearby' and result['radius_metres']==500 and result['boundary'] is None
    assert any('not the entire' in line for line in result['limitations'])

@pytest.mark.anyio
async def test_small_boundary_uses_intersection_and_requires_generated_area(monkeypatch):
    async def sleep(_): pass
    monkeypatch.setattr('app.providers.overpass.asyncio.sleep',sleep)
    area={'type':'area','id':3600000100}
    fetcher=Fetcher([metadata(COUNTRY,boundary()),metadata(area,node(amenity='restaurant'))])
    result=await OverpassProvider('https://example.com/',lambda:fetcher).search(fields(),progress,lambda _:None,lambda *args:None)
    statement=parse_qs(fetcher.calls[1][1]['content'].decode())['data'][0]
    assert '(area.target)(52.2000000,0.1100000,52.2100000,0.1300000)' in statement
    assert result['search_scope']=='boundary' and result['radius_metres'] is None and result['boundary']['id']==100
    assert result['invalid_records']==0 and len(result['items'])==1
    missing=Fetcher([metadata(COUNTRY,boundary()),metadata(node(amenity='restaurant'))])
    with pytest.raises(ProviderFailure,match='no generated area'):
        await OverpassProvider('https://example.com/',lambda:missing).search(fields(),progress,lambda _:None,lambda *args:None)


def test_boundary_limits_and_spatial_disagreement_fail_closed():
    assert not boundary_is_small([51,-1,53,1]) and boundary_is_small([52.2,.11,52.21,.13])
    assert not boundary_is_small([89.99,-179,89.991,179])
    with pytest.raises(ProviderFailure): business_query('restaurant',52,0,10,boundary={'id':100,'bounds':[51,-1,53,1]})
    outside=place();outside['lat']=50
    with pytest.raises(ProviderFailure,match='disagree spatially'): resolve_location({'elements':[COUNTRY,outside,boundary()]},parse_location('London, UK'))
    with pytest.raises(ProviderFailure,match='candidate cap'): resolve_location({'elements':[place(i) for i in range(1,12)]},parse_location('London'))


def test_diagnostics_migration_preserves_historic_failed_search(tmp_path):
    engine=make_engine(tmp_path/'historic.db'); config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    with engine.begin() as connection:
        config.attributes['connection']=connection;command.upgrade(config,'0003_discovery')
        connection.execute(text("INSERT INTO discovery_searches (id,query,status,progress,created_at,cooldown_until,error) VALUES (1,:query,'error','Provider search stopped','2026-10-14 08:54:43','2026-10-14 08:55:43','Historic fixture remark was not retained')"),{'query':json.dumps({'location':'London, UK','category':'restaurant','limit':10,'provider':'osm_overpass','website_filter':'any'})})
        command.upgrade(config,'head')
    manager=DiscoveryManager(engine)
    run=manager.read(1);assert run.diagnostics==[] and run.error=='Historic fixture remark was not retained' and run.query['location']=='London, UK'
    with engine.begin() as connection:
        config.attributes['connection']=connection;command.downgrade(config,'0003_discovery')
        assert connection.scalar(text('SELECT error FROM discovery_searches WHERE id=1'))=='Historic fixture remark was not retained'
    engine.dispose()
