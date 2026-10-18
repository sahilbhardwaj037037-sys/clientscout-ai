"""Conservative whole-statement checks; never subtract facts or names from prose.

This is a bounded compatibility layer for the existing annotated writer protocol,
not a semantic verifier. Unknown statements fail closed pending the v2 design.
"""
import re

# Non-factual language is permitted as a complete statement, never as a prefix
# exemption for an arbitrary factual assertion or commitment.
COURTESIES = [
    r'i appreciate (?:your time|the online presence you have established)',
    r'thank you for (?:your time|considering this)',
    r'thanks for your time', r'have a (?:lovely|good|great|nice) day',
    r'(?:there are no guarantees|i cannot guarantee results)',
    r'would (?:a brief conversation|a quick chat) be useful',
    r'could we have a brief conversation about a useful next step',
    r'if (?:this is helpful|your team has time), we could discuss a next step',
    r'i would be happy to talk through options',
    r'(?:would|could) (?:you|your team) (?:have time|be available) for a brief conversation',
    r'would (?:next week|a brief chat next week) suit you',
    r'could we discuss (?:a useful|the best) next step',
    r'feel free to reply(?: if you would like to discuss this)?',
    r'if you want to explore this, feel free to reply',
    r'if useful, we could talk through the options',
    r'would you be open to a short conversation',
    r'no pressure(?: at all)?',
]
FRONTEND_SUGGESTIONS = [
    r'i could help refine the visitor experience',
    r'could reviewing image descriptions be a useful next step',
    r'i could suggest a focused review of image descriptions',
]
LINK_INVITATIONS = [
    r'(?:you can )?explore (?:my portfolio|examples|my professional instagram)(?: here)?[:]? LINK(?: LINK)*',
    r'my portfolio is LINK', r'portfolio: LINK', r'LINK(?: LINK)*',
    r'if useful, you can explore my portfolio at LINK',
]
WALKTHROUGHS = [
    r'i could share a short project walkthrough if you would find it useful',
    r'if useful, i could share a walkthrough of an existing project',
]
CLOSING = r'(?:best(?: regards)?|kind regards|warm regards|sincerely|thanks|thank you|regards|cheers|with thanks)'
LINK_MARKER = '\ufff0'


def validate_prose(result, context, declared_wordings, body_with_links, subject_with_links):
    from app.intelligence.writer import normalized_text,wording_key,reject
    body = body_with_links
    # A signature is a distinct trailing line, not a global exemption for a name.
    signature = re.search(r'(?:^|\n)[ \t]*'+CLOSING+r'[,!.]?[ \t]*(?:(?:\r?\n|[ \t]+)([^\r\n]+?))?\s*$', body, re.I)
    if signature:
        sender = signature.group(1)
        if sender and normalized_text(sender) != normalized_text(context['freelancer_name']):
            reject('signature_identity','Unapproved freelancer identity.','unknown_sender')
        body = body[:signature.start()]
    body = normalized_text(body)
    name = re.escape(normalized_text(context['business_name']))
    greeting = re.match(r'^(?:hello|hi|dear)(?: to the team at)? (?:the team at )?'+name+r'(?: team)?[,!:]?(?:\s+|$)',body)
    if greeting:body=body[greeting.end():]

    # Each factual assertion must be a complete approved statement. Only narrow
    # service wrappers are allowed around a noun phrase; no negation/suffixes.
    literals=[]
    for identifier,wording in declared_wordings:
        key=wording_key(wording).rstrip('?!')
        literals.append(re.escape(key))
        if identifier.startswith('service:'):
            literals.extend(re.escape(prefix+key) for prefix in ('i can help with ','i could help with ','if useful, i could help with '))
    patterns=literals+COURTESIES
    if 'frontend' in result.service_ids:
        patterns+=FRONTEND_SUGGESTIONS[:1]
        if 'image_alt_missing' in result.finding_ids:patterns+=FRONTEND_SUGGESTIONS[1:]
    if context['approved_links']:
        marker = re.escape(LINK_MARKER)
        link_atom = '(?:'+marker+'|\\('+marker+'\\)|"'+marker+'"|\''+marker+'\')'
        patterns += [p.replace('LINK',link_atom) for p in LINK_INVITATIONS]
        if any(p['id'] in result.project_ids and p['kind']=='completed_project' for p in context['relevant_projects']):
            patterns.append(r'you can see examples of my work at '+link_atom)
    offers=False
    # Consume whole utterances without changing their meaning. The boundary must
    # be punctuation or end of message; "approved fact, but ..." cannot pass.
    while body:
        matched=False
        for pattern in sorted(patterns+WALKTHROUGHS,key=len,reverse=True):
            match=re.match(r'(?:'+pattern+r')(?:[.!?;](?=\s|$)|$|(?<='+LINK_MARKER+r')(?=\s))\s*',body)
            if match:
                if pattern in WALKTHROUGHS:offers=True
                body=body[match.end():];matched=True;break
        if not matched:reject_statement(body,context)
    if offers!=result.offers_walkthrough or offers and not context['walkthrough_allowed']:
        reject('walkthrough_permission','Unapproved demo/walkthrough offer.','offer_permission')

    subject=normalized_text(subject_with_links)
    if subject:
        subjects=[r'(?:a |one )?(?:thoughtful |small |useful |possible )?(?:refinement|website refinement|website support|website updates|image descriptions)(?: for (?:your website|'+name+r'))?',
                  r'a quick question(?: for '+name+r')?',r'portfolio: '+re.escape(LINK_MARKER)]
        if not any(re.fullmatch(p+r'[?!.]?',subject) for p in subjects):
            reject('unsupported_statement','Subject needs supported, non-assertive wording.','subject_assertion')


def reject_statement(text,context):
    """Diagnostic classification only. Every unmatched statement is rejected."""
    from app.intelligence.writer import reject
    if re.search(r'\b(?:not|untrue|false|never|unless|although)\b',text):
        reject('unsupported_statement','An assertion has unsupported surrounding context.','assertion_context')
    if re.search(r'\b(?:will|promise)\b',text):reject('unapproved_commitment','Unapproved commitment.','commitment')
    if re.search(r'\bguarantee\w*\b',text):reject('prohibited_claim','Unapproved result guarantee.','guaranteed_result')
    if re.search(r'\b(?:revenue|sales|traffic|conversions?|rankings?)\b',text):reject('prohibited_claim','Unsupported commercial claim.','commercial_claim')
    if re.search(r'\d|\b(?:million|thousand|percent)\b',text):reject('prohibited_claim','Unsupported metric or quantity.','numeric_claim')
    if re.search(r'\b(?:missing|broken|slow|losing|insecure)\b',text):reject('prohibited_claim','Unsupported business or website problem.','unsupported_problem')
    if re.search(r'\b(?:guarantee\w*|revenue|sales|traffic|conversions?|rankings?|\d+|million|thousand|percent|missing|slow|free|best|personalized demo)\b',text):
        reject('prohibited_claim','Unsupported metric, result or claim.','unsupported_claim')
    if re.search(r"\b(?:we(?:'ve| have)? (?:spoke|spoken|met|talked)|as we|our previous)\b",text):reject('unsupported_relationship','Unverified relationship.','relationship')
    if re.search(r'\b(?:worked|built|experience|earned|achieved|helped|created|developed|designed|launched)\b',text):
        reject('unsupported_experience_or_praise','Unverified experience or praise.','experience')
    if re.search(r'\b(?:your|you|'+re.escape(context['business_name'].casefold())+r')\b',text):
        reject('unsupported_business_assertion','Unsupported business assertion or offer.','business_assertion')
    reject('unsupported_statement','Statement is outside the supported writing contract.','unrecognized_statement')
