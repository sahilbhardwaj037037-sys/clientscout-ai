"""Versioned deterministic evidence priority. Unknown is not failure or a prediction."""
from datetime import timedelta
from urllib.parse import urlsplit
from sqlalchemy import select
from app.discovery.manager import utc
from app.models.audit import Audit
from app.models.intelligence import Enrichment,Assessment
from app.models.lead import now
from app.services.urls import normalize_url

WEIGHTS={'website_opportunity':35,'audit_potential':25,'independence':15,'contact':15,'skill_match':10}
SKILLS={'wordpress':'WordPress / Elementor','shopify':'Shopify','frontend':'HTML / CSS / JavaScript','react':'React / Next.js','python':'Python / full-stack web development'}
# Domain/name association only: never infer franchise ownership, revenue or staff.
CHAIN_DOMAINS={'starbucks.com':'Starbucks','mcdonalds.com':"McDonald's",'ikea.com':'IKEA'}
ATTENTION={'title_missing','title_multiple','description_missing','description_multiple','canonical_invalid','canonical_multiple','language_missing','viewport_missing','image_alt_missing','https'}

def classify(snapshot,enrichment):
    url=snapshot.get('website_url')
    host=normalize_url(url)[1] if url else ''
    name=(snapshot.get('name') or '').casefold()
    for domain,brand in CHAIN_DOMAINS.items():
        if (host==domain or host.endswith('.'+domain)) and brand.casefold().replace("'",'') in name.replace("'",''):
            return 'major_chain',{'reason':'Name and supplied domain match a known major-chain brand; local ownership/operator is not established.','source_url':url,'confidence':'source association; review branch ownership'}
    statements=(enrichment or {}).get('business_statements',[])
    for statement in statements:
        text=statement['text'].lower()
        if 'regional chain' in text:return 'regional_chain',dict(statement,reason='Self-described regional chain; not a verified branch count.')
        if any(word in text for word in ('independent','family-owned','family owned','locally owned')):
            segment='independent_small' if 'small' in text else 'independent_growing' if 'growing' in text else 'independent_established' if 'established' in text else 'independent_size_unknown'
            return segment,dict(statement,reason='Official-source self-description. No revenue, employee count or legal ownership inferred.')
    brand=(snapshot.get('business_tags') or {}).get('brand')
    return 'unknown',{'reason':'Insufficient reliable independence/size evidence.'+(' Source brand tag needs review: '+brand if isinstance(brand,str) else '')}

def assess(session,identity):
    job=session.scalar(select(Enrichment).where(Enrichment.identity_id==identity.id,Enrichment.status.in_(['complete','partial','blocked'])).order_by(Enrichment.id.desc()))
    enrichment=job.report if job and job.report and job.report.get('business_snapshot')==identity.snapshot and utc(job.created_at)>=now()-timedelta(hours=24) else None
    url=identity.snapshot.get('website_url') or (job.requested_url if job else None)
    audit=None
    if url:
        audit=session.scalar(select(Audit).where(Audit.requested_url==url,Audit.status.in_(['complete','partial']),Audit.created_at>=now()-timedelta(hours=24)).order_by(Audit.id.desc()))
    measured=(enrichment or {}).get('website_report') or (audit.report if audit else None)
    identity_status=(enrichment or {}).get('identity',{}).get('status','needs_review')
    if identity_status=='mismatch':measured=None
    official=(enrichment or {}).get('identity',{}).get('official',False)
    segment,classification=classify(identity.snapshot,enrichment)
    website_status=(enrichment or {}).get('website_status','supplied_unverified' if url else 'no_usable_source_tag')
    findings=[f for f in (measured or {}).get('findings',[]) if f.get('code') in ATTENTION and f.get('level')=='attention' and f.get('source_url')]
    if findings:website_status='verified_technical_opportunities' if official else 'technical_observations_identity_unverified'
    evidence=[{'id':f['code'],'title':f['title'],'detail':str(f['evidence'])[:1000],'recommendation':f['recommendation'],'source_url':f['source_url'],'observed_at':f.get('observed_at') or (measured or {}).get('fetched_at')} for f in findings]
    measured_ok=bool(measured and measured.get('http_status')==200)
    components=[]
    def part(key,points,reason,ids=(),coverage=1):components.append({'key':key,'points':points,'max_points':WEIGHTS[key],'reason':reason,'evidence_ids':list(ids),'coverage':coverage if points is not None else 0})
    part('website_opportunity',min(35,len(findings)*12) if measured_ok else None,'Observed static homepage opportunities only; no design, revenue or active-hiring claim.' if measured_ok else 'Website opportunity is unknown; missing/inaccessible source is not a failure.',[f['id'] for f in evidence])
    psi=(audit.report or {}).get('pagespeed',{}) if audit else (measured or {}).get('pagespeed',{})
    metric=psi.get('performance_score') if psi.get('status')=='available' else None
    # Only already validated provider metrics; unavailable/429 never gets a substitute.
    lab_points=(5 if isinstance(metric,(int,float)) and not isinstance(metric,bool) and metric<80 else 0) if metric is not None else 0
    part('audit_potential',min(20,len(findings)*4)+lab_points if measured_ok else None,'Static evidence contributes up to 20; available measured PageSpeed score can contribute 5. Missing lab metrics remain unknown.',[f['id'] for f in evidence],1 if metric is not None else .8)
    independent=segment.startswith('independent')
    part('independence',15 if independent else 5 if segment=='regional_chain' else 0 if segment=='major_chain' else None,classification['reason'])
    contacts=(enrichment or {}).get('contacts',[])
    available=[c for c in contacts if c['value'] and c['kind'] in {'email','phone','whatsapp','contact_page','contact_form','facebook','instagram','linkedin'}]
    part('contact',15 if any(c['status']=='official_verified' for c in available) else 5 if available else None,'Official-source business contact observed.' if any(c['status']=='official_verified' for c in available) else 'Public listing needs review.' if available else 'No contact found in bounded sources; existence is unknown.')
    skill_matches=['frontend'] if findings else []
    html=(measured or {}).get('html',{})
    # Platform must be explicitly observed by a supported signal, not guessed from design.
    part('skill_match',10 if skill_matches else 0 if measured_ok else None,'Confirmed HTML/SEO/accessibility observations fit offered HTML/CSS/JavaScript services.' if skill_matches else 'No confirmed skill-specific improvement found in available measurements.')
    confidence=round(sum(c['max_points']*c['coverage'] for c in components))
    qualified=measured_ok and identity_status=='matched' and official
    score=sum(c['points'] or 0 for c in components) if qualified else None
    result=Assessment(identity_id=identity.id,enrichment_id=job.id if job else None,audit_id=audit.id if audit else None,score=score,confidence=confidence,segment=segment,qualification='qualified' if qualified else 'needs_research',website_status=website_status,report={'version':'evidence-v1','components':components,'evidence':evidence,'classification':classification,'identity':(enrichment or {}).get('identity',{'status':'needs_review','confidence':0,'reasons':['Run source/identity verification first.']}),'skill_matches':skill_matches or ['frontend'],'skills':SKILLS,'contacts':contacts,'business':identity.snapshot,'measured_at':(measured or {}).get('fetched_at'),'limitations':['Priority is a lower bound from observed evidence, not a sales prediction. Unknown components are unassessed, not verified failures.','Official association requires a matching name/domain and explicit user confirmation; source assertions are not independent legal-ownership verification.','A static homepage check is not a complete SEO/design/mobile audit. No business is claimed to be seeking developers.'],'contact_available':bool(available),'pagespeed_status':psi.get('status','not_requested')})
    session.add(result);session.flush();return result
