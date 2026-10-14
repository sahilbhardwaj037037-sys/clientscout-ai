"""One optional CC0 entity lookup by existing OSM business wikidata ID; no search/scrape."""
import json
import re
from app.auditing.network import AuditFailure
from app.intelligence.contacts import role_email
from app.intelligence.identity import name_matches
from app.services.urls import normalize_url

async def directory_contacts(fetcher,snapshot):
    identifier=(snapshot.get('business_tags') or {}).get('wikidata','')
    if not isinstance(identifier,str) or not re.fullmatch(r'Q[1-9][0-9]{0,12}',identifier):return [],'No business-specific Wikidata ID in the saved source; brand IDs are not substituted.'
    source=f'https://www.wikidata.org/wiki/{identifier}'
    response=await fetcher.get(f'https://www.wikidata.org/wiki/Special:EntityData/{identifier}.json',max_bytes=512*1024,timeout=10)
    if response.status!=200:raise AuditFailure(f'Wikidata returned HTTP {response.status}; directory source unavailable.','directory_error',response.headers.get('retry-after'))
    try:
        entity=json.loads(response.body)['entities'][identifier];claims=entity['claims'];label=entity.get('labels',{}).get('en',{}).get('value','')
        def values(key):return [item['mainsnak']['datavalue']['value'] for item in claims.get(key,[])[:10] if item.get('rank')!='deprecated' and 'datavalue' in item.get('mainsnak',{})]
        classes=[v.get('id') for v in values('P31') if isinstance(v,dict)]
        if 'Q5' in classes or not any(v in classes for v in ['Q43229','Q783794','Q4830453','Q11707','Q507619']):return [],'Entity is not an allowlisted organization/business type; personal data was not extracted.'
        if not name_matches(snapshot.get('name'),label):return [],'Directory identity label does not match; records were not combined.'
        result=[]
        for raw in values('P968'):
            value=role_email(raw,snapshot.get('name') or '') if isinstance(raw,str) else None
            if value:result.append({'kind':'email','value':value,'status':'needs_review','source_url':source,'source_kind':'wikidata','licence':'CC0','attribution':'Wikidata contributors','fetched_at':response.fetched_at,'evidence':'Role email on matching organization entity; branch/domain association is unverified.'})
        for raw in values('P856'):
            try:value=normalize_url(raw)[0]
            except (ValueError,TypeError):continue
            # Candidate only; never fetch/merge a directory-supplied domain automatically.
            result.append({'kind':'website_candidate','value':value,'status':'needs_review','source_url':source,'source_kind':'wikidata','licence':'CC0','attribution':'Wikidata contributors','fetched_at':response.fetched_at,'evidence':'Organization website candidate; user must establish official/local identity before use.'})
        return result[:6],'Wikidata CC0 organization record checked; its domain/branch association remains unverified.'
    except (ValueError,KeyError,TypeError,AttributeError):raise AuditFailure('Wikidata response was invalid; no contact data was inferred.','directory_error') from None
