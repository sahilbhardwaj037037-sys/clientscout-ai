"""Option A: hard safety gates, unverified prose and content-bound human review.

Only subject/body are retained, in the existing local draft row. No raw response,
claim-text copies, recovery blobs or rejected text are stored by this module.
"""
import hashlib
import json
import re
import unicodedata
from app.schemas.intelligence import HumanWrittenDraft
from app.models.intelligence import OutreachDraft
from app.intelligence.writer import writer_context,approved_url_key,reject

HUMAN_VERSION='human-reviewed-v1'
HUMAN_VERSIONS={'validator_version':'human-safety-v1','prompt_version':'human-writer-v2'}
REVIEW_LABEL='AI-generated · Unverified · Review required'


def human_context(assessment,channel,profile):
    context=writer_context(assessment,channel,profile)
    context.pop('approved_fact_wordings',None)
    return context


def content_hash(subject,body):
    return hashlib.sha256(json.dumps([subject,body],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def is_human_draft(draft):return draft.generator=='gemini' and draft.evidence.get('writer_version')==HUMAN_VERSION


def review_metadata(subject,body):return {'state':'required','factual_status':'unverified','content_hash':content_hash(subject,body)}


def hard_check(subject,body,authorization,*,channel=None):
    from app.core import settings
    text=subject+'\n'+body
    if any(secret and secret in text for secret in (settings.GEMINI_API_KEY,settings.PAGESPEED_API_KEY)) or re.search(r'AIza[\w-]{16,}|\bsk-[A-Za-z0-9_-]{16,}|\b(?:api[_ -]?key|password|secret)\s*[:=]\s*\S+',text,re.I):
        reject('protected_information','Hard-blocked: protected information.','secret')
    if any(unicodedata.category(c) in {'Cc','Cf','Cs'} and c not in '\n\t' for c in text.replace('\r\n','\n')):
        reject('contacts_or_markup','Hard-blocked: unsafe control content.','control')
    if '\n' in subject or '\r' in subject:reject('subject_single_line','Hard-blocked: subject must be single-line.')
    if not body.strip():reject('body_length','Hard-blocked: empty message.')
    if channel=='email' and not subject.strip():reject('email_subject_required','Hard-blocked: email subject required.')
    if channel and channel!='email' and subject:reject('non_email_subject','Hard-blocked: non-email subject must be empty.')
    if re.search(r'[<>\[\]]|`',text):reject('contacts_or_markup','Hard-blocked: markup or placeholders.','markup')
    allowed={approved_url_key(url) for url in authorization['approved_links']}-{None}
    used=set()
    def consume(match):
        token=match.group(0);candidate=token
        while candidate:
            key=approved_url_key(candidate)
            if key in allowed:
                used.add(key);return token[len(candidate):]
            if candidate[-1] not in '.,;!?)\"\'':break
            candidate=candidate[:-1]
        reject('link_allowlist','Hard-blocked: unauthorized URL.','unauthorized_url')
    remaining=re.sub(r'https?://[^\s<>\[\]\"]+',consume,text,flags=re.I)
    if re.search(r'@|\b(?:mailto|tel|sms|javascript|data):|\b[a-z][a-z0-9+.-]*://',remaining,re.I):
        reject('contacts_or_markup','Hard-blocked: contact or unauthorized destination.','contact')
    # Detect bare destinations without a TLD shortlist. Next.js is a capability
    # name, not a link, only when React is authorized. No arbitrary URL exemption.
    domain_text=remaining
    if 'react' in authorization['allowed_services']:domain_text=re.sub(r'\bNext\.js\b','',domain_text)
    if re.search(r'\b[\w-]+\.(?:[a-z]{2,63}|xn--[a-z0-9-]+)\b',domain_text,re.I):
        reject('link_allowlist','Hard-blocked: undeclared destination.','unauthorized_url')
    if re.search(r'\+?\d[\d ()-]{6,}\d|\b\w+\s*(?:\(at\)|\bat\b)\s*\w+\s*(?:\(dot\)|\bdot\b)\s*[a-z]{2,}',remaining,re.I):
        reject('contacts_or_markup','Hard-blocked: private contact information.','contact')
    closing=r'(?:best(?: regards)?|kind regards|warm regards|sincerely|thanks|thank you|regards|cheers|with thanks)'
    signature=re.search(r'(?:^|\n)[ \t]*'+closing+r'(?:[ \t]*,[ \t]*([^\r\n]+)|[,!]?[ \t]*\r?\n[ \t]*([^\r\n]+))\s*$',remaining,re.I)
    if signature:
        sender=signature.group(1) or signature.group(2)
        def normalized(value):return ' '.join(unicodedata.normalize('NFC',value).split()).casefold()
        if normalized(sender)!=normalized(authorization.get('freelancer_name','')):
            reject('signature_identity','Hard-blocked: unauthorized sender identity.','unknown_sender')
    # Negated disclaimers do not promise results. This exemption is local to the
    # guarantee verb; any additional promise/commitment is still checked.
    commitments=re.sub(r"\b(?:no|without|cannot(?:\s+be)?|can['’]t(?:\s+be)?|never|not)\s+(?:any\s+)?guarantee\w*\b",'',remaining,flags=re.I)
    if re.search(r'\bguarantee\w*\b',commitments,re.I):
        reject('prohibited_claim','Hard-blocked: result guarantee.','guaranteed_result')
    if re.search(r"\b(?:i|we)(?:['’]ll| will| promise)\b|\b(?:free|complimentary)\s+(?:custom\s+)?(?:work|demo|redesign|website|mockup)|\b(?:deliver|finish|complete|launch|build)\b[^.!?\n]{0,70}\b(?:by|within|in)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an|next|this|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)\b",commitments,re.I):
        reject('unapproved_commitment','Hard-blocked: unauthorized commitment.','commitment')
    if re.search(r"\b(?:deliver|finish|complete|launch|build|create|develop|design)\b[^.!?\n]{0,100}\b(?:(?:next|this)\s+(?:week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|tomorrow|at no cost|free of charge)\b",commitments,re.I):
        reject('unapproved_commitment','Hard-blocked: unauthorized timeline or free-work commitment.','commitment')
    if re.search(r"\b(?:i|we)\s+(?:(?:can|could|would)\s+)?(?:build|create|deliver|design|develop|provide|make)\s+(?:you\s+)?(?:a|an|the|your)\s+(?:new|custom|personalized|complete|full)\s+(?:preview|demo|website|redesign|mockup)\b",commitments,re.I):
        reject('unapproved_commitment','Hard-blocked: unapproved specific deliverable.','commitment')
    for service,pattern in {'wordpress':r'wordpress|elementor','shopify':r'shopify','react':r'\breact\b|next\.js','python':r'\bpython\b',
                            'other':r'\bseo\b|paid ads|mobile app development|branding'}.items():
        if service not in authorization['allowed_services'] and re.search(r"\b(?:i|we)\s+(?:can\s+|could\s+)?(?:offer|provide|speciali[sz]e|help|build|develop)\b[^.!?\n]{0,80}(?:"+pattern+')',remaining,re.I):
            reject('unsupported_service','Hard-blocked: unauthorized service offer.','service_authorization')
    if re.search(r'\b(?:demo|walkthrough|walk-through)\b',remaining,re.I) and not authorization['walkthrough_allowed']:
        reject('walkthrough_permission','Hard-blocked: demo/walkthrough is not authorized.','offer_permission')
    return sorted(used)


def validate_human(data,context):
    result=HumanWrittenDraft.model_validate(data)
    if len(result.body.split())>220:reject('body_length','Hard-blocked: message exceeds 220 words.')
    hard_check(result.subject,result.body,context,channel=context['channel'])
    return result


def authorization_snapshot(context):
    return {key:context[key] for key in ('approved_links','allowed_services','walkthrough_allowed','freelancer_name')}


def compose_human(assessment,result,context,model):
    result=validate_human(result,context)
    return OutreachDraft(identity_id=assessment.identity_id,assessment_id=assessment.id,channel=context['channel'],generator='gemini',
        subject=result.subject,body=result.body,evidence={'assessment_id':assessment.id,'findings':assessment.report['evidence'],
            'review_required':True,'writer_version':HUMAN_VERSION,**HUMAN_VERSIONS,'model':model,
            'generator_description':'AI-generated · Unverified. Check every claim, experience, link and offer before manual outreach. Human approval is not automated factual verification.',
            'review':review_metadata(result.subject,result.body),'authorization':authorization_snapshot(context)})
