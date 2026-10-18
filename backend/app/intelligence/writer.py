"""Ground AI prose in approved facts; retain generated prose, never a fallback template."""
import re
import unicodedata
from fastapi import HTTPException
from app.models.intelligence import OutreachDraft
from app.schemas.intelligence import AIWrittenDraft,FreelancerProfile,public_text,profile_url

WRITER_MODEL='gemini-3.5-flash-lite'
VALIDATOR_VERSION='writer-validator-v2'
PROMPT_VERSION='writer-prompt-v2'
WRITER_VERSIONS={'validator_version':VALIDATOR_VERSION,'prompt_version':PROMPT_VERSION}
VALIDATION_RULES=frozenset({'body_length','email_subject_required','non_email_subject','subject_single_line','finding_or_service_allowlist',
    'project_allowlist','link_allowlist','link_declarations','contacts_or_markup','fact_wording','fact_references','finding_required',
    'business_name_required','appreciation_required','signature_identity','prohibited_claim','unsupported_experience_or_praise',
    'technical_service_allowlist','unsupported_service','walkthrough_permission','unapproved_commitment',
    'schema_violation','invalid_json','invalid_response_text','response_too_large','protected_information','invalid_output_type',
    'unsupported_relationship','unsupported_business_assertion','unsupported_statement','response_finish'})
FACT_WORDING_REASONS=frozenset({'unknown_fact','unsupported_wording','claim_not_in_body'})
LINK_DECLARATION_REASONS=frozenset({'missing_declaration','unused_declaration','url_mismatch'})
DIAGNOSTIC_REASONS={'fact_wording':FACT_WORDING_REASONS,'link_declarations':LINK_DECLARATION_REASONS,
    'unsupported_statement':{'assertion_context','subject_assertion','unrecognized_statement'},
    'signature_identity':{'unknown_sender'},'prohibited_claim':{'unsupported_claim','guaranteed_result','commercial_claim','numeric_claim','unsupported_problem'},
    'unsupported_relationship':{'relationship'},'unsupported_business_assertion':{'business_assertion'},
    'unsupported_experience_or_praise':{'experience'},'unapproved_commitment':{'commitment'},
    'protected_information':{'secret'},'contacts_or_markup':{'control','markup','contact'},'link_allowlist':{'unauthorized_url'},'unsupported_service':{'service_authorization'},
    'walkthrough_permission':{'offer_permission'},'response_finish':{'truncated','blocked','missing','unexpected'}}

class WritingValidationError(ValueError):
    def __init__(self,rule,message,reason=None):super().__init__(message);self.rule=rule;self.reason=reason if reason in DIAGNOSTIC_REASONS.get(rule,()) else None

def safe_writer_diagnostics(diagnostics):
    """Persist only fixed codes and known schema field names, never provider values."""
    if not isinstance(diagnostics,dict):return None
    rule=diagnostics.get('rule');stage=diagnostics.get('stage')
    if not isinstance(rule,str) or rule not in VALIDATION_RULES or not isinstance(stage,str) or stage not in {'response','parse','schema','validation'}:return None
    safe={'stage':diagnostics['stage'],'rule':diagnostics['rule']}
    fields=diagnostics.get('fields')
    if isinstance(fields,list):safe['fields']=sorted({f for f in fields if isinstance(f,str) and f in AIWrittenDraft.model_fields})
    reason=diagnostics.get('reason')
    if isinstance(reason,str) and reason in DIAGNOSTIC_REASONS.get(rule,()):safe['reason']=reason
    for versions in (WRITER_VERSIONS,{'validator_version':'human-safety-v1','prompt_version':'human-writer-v1'},{'validator_version':'human-safety-v1','prompt_version':'human-writer-v2'}):
        for key,value in versions.items():
            if diagnostics.get(key)==value:safe[key]=value
    if diagnostics.get('disposition')=='hard_blocked':safe['disposition']='hard_blocked'
    return safe

def reject(rule,message,reason=None):raise WritingValidationError(rule,message,reason)

def schema_diagnostics(error):
    fields=[item['loc'][0] for item in error.errors(include_input=False,include_context=False,include_url=False) if item['loc'] and isinstance(item['loc'][0],str)]
    return safe_writer_diagnostics({'stage':'schema','rule':'schema_violation','fields':fields})
SERVICES={'frontend':'website updates and refinements','wordpress':'WordPress website updates','shopify':'Shopify website updates','react':'React website development','python':'Python web development'}
OBSERVATIONS={
    'title_missing':('The first page title was missing or empty in the downloaded HTML.','A descriptive title could help people understand the page when it appears in a browser tab.'),
    'title_multiple':('The checked page showed more than one page title in its downloaded HTML.','Refining the page title could give visitors a clearer description of the page.'),
    'description_missing':('The first page description was missing or empty in the downloaded HTML.','Adding a short description could help explain what the page offers.'),
    'description_multiple':('The checked page showed more than one page description in its downloaded HTML.','Refining the description could make the page summary clearer.'),
    'canonical_invalid':('The checked page contained an invalid preferred-page link in its downloaded HTML.','Refining that link could make the preferred version of the page clearer.'),
    'canonical_multiple':('The checked page contained multiple preferred-page links in its downloaded HTML.','Refining those links could make the preferred version of the page clearer.'),
    'language_missing':('The checked page did not declare its language in its downloaded HTML.','Adding a language declaration could help assistive tools interpret the page.'),
    'viewport_missing':('The downloaded HTML did not contain a viewport declaration with width=device-width.','Reviewing that setting could help the page adapt to smaller screens; a separate visual check would still be needed.'),
    'image_alt_missing':('Some images on the checked page had no alternative-text attribute in its downloaded HTML.','Reviewing image descriptions could make useful images easier to understand with assistive tools.'),
    'https':('The checked page was served over HTTP rather than HTTPS.','Reviewing HTTPS could help protect information exchanged with the website.'),
}

# Human-vetted alternatives retain the same scope, uncertainty and capability.
# This is a finite allowlist, never fuzzy matching or a model's own safety verdict.
FACT_ALTERNATIVES={
    'website_present':[
        'I appreciate the public website you already have for your business.',
        'Your business already has a public website.',
        'I appreciate that your business already has a public website.',
        "I'm glad your business already has a public website.",
    ],
    'finding:image_alt_missing':[
        'On the page checked, some images had no alt attribute in the downloaded HTML.',
        'In a static check of one page, some images had no alternative-text attribute.',
        'On the checked page, some images were missing alternative-text attributes in the downloaded HTML.',
        'The downloaded HTML for the checked page included images without alternative-text attributes.',
    ],
    'benefit:image_alt_missing':[
        'Adding useful image descriptions could make those images clearer to people using assistive tools.',
        'Clearer image descriptions may help visitors using assistive tools understand useful images.',
        'Reviewing image descriptions may make useful images easier to understand with assistive tools.',
    ],
    'service:frontend':[
        'I could help you refine your existing website.',
        'updates and refinements to your website',
        'I could help with updates and refinements to your website.',
        'If useful, I could help refine your existing website.',
        'Could I help with updates and refinements to your website?',
    ],
}

def approved_wordings(facts):
    return {identifier:[text,*FACT_ALTERNATIVES.get(identifier,[])] for identifier,text in facts.items()}

def normalized_text(text):
    # Case, NFC and whitespace only: do not discard words, numbers or negation.
    return re.sub(r'\s+',' ',unicodedata.normalize('NFC',text)).strip().casefold()

def wording_key(text):return normalized_text(text).removesuffix('.')

def wording_pattern(text):
    return re.compile(r'(?<!\w)'+re.escape(wording_key(text))+r'(?!\w)\.?')

def writer_context(assessment,channel,profile):
    identity=assessment.report.get('identity',{})
    if assessment.qualification!='qualified' or identity.get('status')!='matched' or not identity.get('official'):
        raise HTTPException(422,'Verify official business identity before AI writing.')
    profile=FreelancerProfile.model_validate(profile)
    if not profile.public_details_confirmed or not profile.service_ids:
        raise HTTPException(422,'Save and confirm the services you offer in your freelancer profile before using Gemini AI Writer.')
    allowed_services=[s for s in profile.service_ids if s in assessment.report['skill_matches']]
    if not allowed_services:raise HTTPException(422,'No confirmed offered service matches this assessment.')
    name=public_text(assessment.report['business'].get('name') or '')
    if not name:raise HTTPException(422,'A verified business name is required for AI writing.')
    facts={'website_present':'You already have a public website for your business.'}
    findings=[]
    for evidence in assessment.report['evidence']:
        if evidence['id'] in OBSERVATIONS and evidence.get('source_url') and evidence.get('observed_at'):
            identifier=evidence['id'];observation,benefit=OBSERVATIONS[identifier]
            facts['finding:'+identifier]=observation;facts['benefit:'+identifier]=benefit;findings.append(identifier)
    for service in allowed_services:facts['service:'+service]=SERVICES[service]
    projects=[];links=[]
    if profile.portfolio_url:links.append(profile.portfolio_url)
    if profile.instagram_url:links.append(profile.instagram_url)
    for project in profile.projects:
        if not set(project.service_ids)&set(allowed_services):continue
        projects.append(project.model_dump())
        facts['project:'+project.id]=(f'I have worked on {project.title}.' if project.kind=='completed_project' else f'I have an existing demo called {project.title}.')
        if project.url:links.append(project.url)
    return {'business_name':name,'channel':channel,'approved_facts':facts,'finding_ids':findings,'allowed_services':allowed_services,
            'approved_fact_wordings':approved_wordings(facts),
            'freelancer_name':profile.display_name,'relevant_projects':projects,'approved_links':list(dict.fromkeys(links)),
            'portfolio_url':profile.portfolio_url,'instagram_url':profile.instagram_url,
            'walkthrough_allowed':profile.allow_walkthrough_offer and bool(projects),
            'limitations':'Only a bounded static page check, not a complete audit. No business intent, commercial performance or customer behavior is known.'}

def approved_url_key(value):
    # Require an explicit HTTPS URL. Profile validation rejects credentials,
    # queries/fragments and secrets; normalization preserves path case/slashes.
    if not re.match(r'^https://',value,re.I):return None
    try:return profile_url(value)
    except ValueError:return None

def validate_links(text,declared,approved):
    allowed={approved_url_key(url) for url in approved}-{None}
    declarations={approved_url_key(url) for url in declared}
    if None in declarations or not declarations<=allowed:
        reject('link_allowlist','Unapproved link.')
    used=set()
    def consume(match):
        token=match.group(0);candidate=token
        # Prefer the complete approved URL, including legal path punctuation.
        # Only then try removing surrounding sentence/parenthesis punctuation.
        while candidate:
            key=approved_url_key(candidate)
            if key in allowed:
                used.add(key)
                from app.intelligence.prose import LINK_MARKER
                return LINK_MARKER+token[len(candidate):]
            if candidate[-1] not in ".,;!?)\"'":break
            candidate=candidate[:-1]
        reject('link_allowlist','Unapproved link.')
    remaining=re.sub(r'https?://[^\s<>\[\]"]+',consume,text,flags=re.I)
    if used!=declarations:
        reason='url_mismatch' if used-declarations and declarations-used else 'missing_declaration' if used-declarations else 'unused_declaration'
        reject('link_declarations','Links must exactly match declared approved URLs.',reason)
    return remaining

def validate_written(data,context):
    result=AIWrittenDraft.model_validate(data)
    if not result.body.strip() or len(result.body.split())>220:reject('body_length','Empty or excessively long AI draft.')
    if context['channel']=='email' and not result.subject.strip():reject('email_subject_required','Email subject required.')
    if context['channel']!='email' and result.subject:reject('non_email_subject','Non-email drafts must have an empty subject.')
    if re.search(r'[\r\n]',result.subject):reject('subject_single_line','Subject must be single-line.')
    if not set(result.finding_ids)<=set(context['finding_ids']) or not set(result.service_ids)<=set(context['allowed_services']):reject('finding_or_service_allowlist','Unsupported finding or service.')
    projects={p['id']:p for p in context['relevant_projects']}
    if not set(result.project_ids)<=projects.keys():reject('project_allowlist','Unsupported or unrelated experience.')
    from app.intelligence.prose import LINK_MARKER,validate_prose
    text=result.subject+'\n'+result.body
    if LINK_MARKER in text:reject('contacts_or_markup','Reserved formatting character.')
    without_urls=validate_links(text,result.used_links,context['approved_links'])
    if re.search(r'@|(?:www\.|\b[\w-]+\.(?:[a-z]{2,63}|xn--[a-z0-9-]+)\b)|[<>]|\[[^\]]*\]',without_urls,re.I):reject('contacts_or_markup','Contact, markup, placeholder or undeclared link.')
    facts=context['approved_facts'];wordings=approved_wordings(facts)
    claimed=set();body=normalized_text(result.body);website_in_opening=False;declared_wordings=[]
    for claim in result.claims:
        if claim.fact_id not in facts:reject('fact_wording','Claim references an unknown fact.','unknown_fact')
        if wording_key(claim.text) not in {wording_key(w) for w in wordings[claim.fact_id]}:
            reject('fact_wording','Claim wording is not an approved expression of this fact.','unsupported_wording')
        pattern=wording_pattern(claim.text);matches=list(pattern.finditer(body))
        if not matches:reject('fact_wording','Declared claim does not occur in the body.','claim_not_in_body')
        if claim.fact_id=='website_present':website_in_opening|=any(m.end()<=450 for m in matches)
        # Repeated verified references are harmless; every span is still checked.
        claimed.add(claim.fact_id);declared_wordings.append((claim.fact_id,claim.text))
    required={'website_present'}|{'finding:'+i for i in result.finding_ids}|{'service:'+i for i in result.service_ids}|{'project:'+i for i in result.project_ids}
    permitted=required|{'benefit:'+i for i in result.finding_ids}
    if not required<=claimed or not claimed<=permitted:reject('fact_references','Missing or inconsistent evidence references.')
    if context['finding_ids'] and not result.finding_ids:reject('finding_required','Use a verified opportunity when available.')
    if not re.search(r'(?<!\w)'+re.escape(normalized_text(context['business_name']))+r'(?!\w)',body):reject('business_name_required','Personalize with the verified business name.')
    if not website_in_opening or not re.search(r'\b(?:appreciate|thank|thanks|glad)\b',body[:450]):reject('appreciation_required','Begin with respectful, supported appreciation.')
    subject_with_links,body_with_links=without_urls.split('\n',1)
    validate_prose(result,context,declared_wordings,body_with_links,subject_with_links)
    return result

def compose_written(assessment,result,context,model):
    result=validate_written(result,context)
    chosen=[e for e in assessment.report['evidence'] if e['id'] in result.finding_ids]
    return OutreachDraft(identity_id=assessment.identity_id,assessment_id=assessment.id,channel=context['channel'],generator='gemini',
        subject=result.subject,body=result.body,evidence={'assessment_id':assessment.id,'findings':chosen,'review_required':True,
        'writer_version':'ai-writer-v1',**WRITER_VERSIONS,'model':model,'generator_description':'Gemini AI Writer: AI-written subject and body, checked against approved evidence and confirmed public profile. Review before manual outreach.',
        'grounding':result.model_dump(exclude={'subject','body'}),'profile_project_ids':result.project_ids})
