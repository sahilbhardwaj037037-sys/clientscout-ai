"""Compose reviewed drafts from allowlisted observed facts and offered services only."""
from fastapi import HTTPException
from app.schemas.intelligence import AISelection
from app.intelligence.scoring import SKILLS
from app.models.intelligence import OutreachDraft

def validate_selection(data,assessment):
    selection=AISelection.model_validate(data)
    allowed={e['id'] for e in assessment.report['evidence']}
    if not set(selection.finding_ids)<=allowed or not set(selection.service_ids)<=set(assessment.report['skill_matches']):raise ValueError('AI selected unsupported facts or services.')
    return selection

def compose(assessment,channel,selection=None,generator='template'):
    if assessment.qualification!='qualified' or assessment.report['identity']['status']!='matched':raise HTTPException(422,'Verify business identity and assess genuine website evidence before drafting.')
    facts=assessment.report['evidence'];name=assessment.report['business'].get('name')
    if not name:raise HTTPException(422,'Business name is missing; research it before drafting.')
    selection=selection or AISelection(opening='direct',finding_ids=[e['id'] for e in facts[:2]],service_ids=assessment.report['skill_matches'][:1],closing='outline')
    selection=validate_selection(selection.model_dump(),assessment)
    chosen=[e for identifier in selection.finding_ids for e in facts if e['id']==identifier]
    opening={'direct':f'Hello {name} team,','brief':f'Hi {name} team,','courteous':f'Hello to the team at {name},'}[selection.opening]
    services=', '.join(SKILLS[s] for s in selection.service_ids)
    observation=('A recorded static homepage check observed: '+ '; '.join(e['title'].lower() for e in chosen)+'. This is limited page evidence, so I would confirm the details with you before recommending changes.') if chosen else 'I offer website development and maintenance support tailored to the scope a business actually needs.'
    closing={'outline':'Would a brief outline of possible next steps be useful?','chat':'Would you be open to a short conversation about whether this would be helpful?','permission':'May I share a short, practical outline for your review?'}[selection.closing]
    body=f'{opening}\n\n{observation}\n\nI can help with {services}, focusing on the observations above and your priorities.\n\n{closing}\n\nBest,\n[Your name]'
    if channel!='email':body=f'{opening} {observation} I can help with {services}. {closing} — [Your name]'
    return OutreachDraft(identity_id=assessment.identity_id,assessment_id=assessment.id,channel=channel,generator=generator,subject=f'Website support for {name}'[:200] if channel=='email' else '',body=body,evidence={'assessment_id':assessment.id,'findings':chosen,'selection':selection.model_dump(),'review_required':True,'generator_description':'Local evidence template; no AI request' if generator=='template' else 'Gemini-assisted selection of approved evidence, services and wording variants; factual content is composed by validated templates.'})
