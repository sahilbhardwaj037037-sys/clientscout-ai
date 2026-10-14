import asyncio
from urllib.parse import urlsplit
from app.auditing.html import analyze_html
from app.auditing.network import AuditFailure,SafeFetcher
from app.auditing.robots import PoliteFetcher
from app.intelligence.contacts import ContactPage,KINDS,extract_contacts,osm_contacts,safe_link
from app.intelligence.identity import verify_identity
from app.providers.wikidata import directory_contacts
from app.services.urls import normalize_url

class BudgetFetcher:
    def __init__(self,delegate):self.delegate=delegate;self.calls=0
    async def get(self,*args,**kwargs):
        if self.calls>=8:raise AuditFailure('Eight-request enrichment budget exhausted; no additional source fetched.','request_budget')
        self.calls+=1;return await self.delegate.get(*args,**kwargs)

async def enrich(snapshot,url,official_confirmed,use_directory,progress,fetcher_factory=SafeFetcher):
    report={'business_snapshot':snapshot,'identity':{'status':'needs_review','confidence':0,'official':False,'reasons':['No website identity check completed.']},'contacts':osm_contacts(snapshot),'pages':[],'requests':[],'limitations':['Public business contact methods only. Personal staff addresses are excluded. Missing means not observed in these bounded sources, not proof of absence.','No social profile was fetched, login bypassed or contact form submitted.'],'website_report':None,'business_statements':[],'website_status':'no_usable_source_tag' if not url else 'supplied_unverified'}
    error=None
    async with fetcher_factory() as raw:
        fetcher=BudgetFetcher(raw)
        if use_directory:
            try:
                await progress('Checking one business-specific CC0 directory entity')
                contacts,note=await directory_contacts(fetcher,snapshot);report['contacts'].extend(contacts);report['limitations'].append(note)
            except AuditFailure as failure:report['limitations'].append(str(failure))
        if url:
            _,host=normalize_url(url);polite=PoliteFetcher(fetcher,allowed_hosts={host})
            queue=[url];seen=set()
            for index in range(3):
                if not queue:break
                target=queue.pop(0)
                if target in seen:continue
                seen.add(target)
                try:
                    await progress(f'Checking permitted business page {index+1} of at most 3')
                    response=await polite.page(target)
                    if response.status in {401,403,429} or response.headers.get('cf-mitigated','').lower()=='challenge':raise AuditFailure(f'Business page returned HTTP {response.status}; access stopped.','access_restricted',response.headers.get('retry-after'))
                    if response.status!=200:raise AuditFailure(f'Business page returned HTTP {response.status}; no contact absence inferred.','http_error',response.headers.get('retry-after'))
                    if not any(t in response.headers.get('content-type','').lower() for t in ['text/html','application/xhtml+xml']):raise AuditFailure('Business response is not HTML; no contact data inferred.','unsupported_content')
                    page=ContactPage();page.feed(response.body.decode('utf-8','replace'))
                    identity,organizations=verify_identity(snapshot,page,response.url,official_confirmed)
                    report['pages'].append({'url':response.url,'fetched_at':response.fetched_at,'http_status':response.status,'identity':identity})
                    if identity['status']=='mismatch':
                        report['identity']=identity;report['website_status']='identity_needs_review';error='Website identity mismatch; website contacts were not combined.';break
                    if index>0 and identity['status']=='needs_review' and report['identity']['status']=='matched':identity=report['identity']
                    if index==0:
                        report['identity']=identity;report['website_status']='verified_official' if identity['official'] else 'supplied_unverified'
                        signals,findings=analyze_html(response.body,response.url,response.headers)
                        report['website_report']={'final_url':response.url,'http_status':response.status,'html':signals,'findings':[dict(f,observed_at=response.fetched_at) for f in findings],'fetched_at':response.fetched_at,'pagespeed':{'status':'not_requested'},'https':urlsplit(response.url).scheme=='https','tls_verified':urlsplit(response.url).scheme=='https'}
                    # If no name evidence, collect no website methods until human verification.
                    if identity['confidence']>=50:
                        page.organizations=organizations
                        for method in extract_contacts(page,response.url,snapshot.get('name') or ''):
                            method.update(status='needs_review' if method['kind'] in {'facebook','instagram','linkedin'} else 'official_verified' if identity['official'] else 'public_unverified',source_url=response.url,source_kind='website',licence='User-confirmed permitted website access; redistribution rights not established',attribution=snapshot.get('name'),fetched_at=response.fetched_at)
                            report['contacts'].append(method)
                        if identity['official']:
                            import re
                            content=' '.join(page.text)
                            for sentence in re.split(r'[.!?\n]',content):
                                if re.search(r'\b(independent|family.owned|locally.owned|independently operated|regional chain)\b',sentence,re.I) and re.search(r'\b(we are|we run|we operate|our business|our company|our shop|our restaurant)\b',sentence,re.I) and not re.search(r'\b(not|never)\b',sentence,re.I) and len(report['business_statements'])<5:
                                    report['business_statements'].append({'text':sentence.strip()[:300],'source_url':response.url,'observed_at':response.fetched_at})
                    if index==0:
                        for link in page.links:
                            candidate=safe_link(response.url,link['href'])
                            if candidate and normalize_url(candidate)[1]==host and not urlsplit(candidate).query and any(part in urlsplit(candidate).path.lower().strip('/').split('/') for part in ['contact','contact-us','about','about-us']) and candidate not in queue and candidate not in seen:
                                queue.append(candidate)
                            if len(queue)>=2:break
                except AuditFailure as failure:
                    error=str(failure);report['limitations'].append(error)
                    if index==0:report['website_status']='inaccessible'
                    report['retry_after']=failure.retry_after;break
            report['requests']=polite.evidence
            if report['identity']['status']=='mismatch':report['contacts']=[c for c in report['contacts'] if c['source_kind']=='osm'];report['website_report']=None;report['business_statements']=[]
        unique={}
        for c in report['contacts']:
            key=(c['kind'],c['value'])
            if key not in unique or c['status']=='official_verified':unique[key]=c
        report['contacts']=list(unique.values())[:30]
        for kind in KINDS:
            if not any(c['kind']==kind for c in report['contacts']):report['contacts'].append({'kind':kind,'value':'','status':'source_inaccessible' if error else 'not_found','source_url':url or snapshot.get('source_url'),'source_kind':'bounded_research','licence':None,'attribution':None,'fetched_at':report['pages'][-1]['fetched_at'] if report['pages'] else None,'evidence':'Not observed in supported permitted sources; absence is not established.'})
    return ('partial' if error and report['pages'] else 'blocked' if error else 'complete'),report,error
