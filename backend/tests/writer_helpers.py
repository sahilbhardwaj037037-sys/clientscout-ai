from app.intelligence.profile import save_profile
from app.schemas.intelligence import FreelancerProfile,AIWrittenDraft

def confirm_writer(database,monkeypatch,**overrides):
    monkeypatch.setattr('app.intelligence.ai_manager.GEMINI_MODEL','gemini-3.5-flash-lite')
    monkeypatch.setattr('app.providers.gemini.GEMINI_MODEL','gemini-3.5-flash-lite')
    profile=FreelancerProfile.model_validate({'service_ids':['frontend'],'public_details_confirmed':True,**overrides})
    save_profile(database,profile)
    return profile

def written(context,with_profile=False):
    facts=context['approved_facts'];identifiers=['website_present','service:frontend']
    finding=context['finding_ids'][:1]
    if finding:identifiers+=['finding:'+finding[0],'benefit:'+finding[0]]
    projects=[];links=[]
    if with_profile and context['relevant_projects']:
        projects=[context['relevant_projects'][0]['id']];identifiers+=['project:'+projects[0]]
        links=context['approved_links'][:1]
    body=f"Hello {context['business_name']} team,\n\nI appreciate the online presence you have established. {facts['website_present']}\n\n"
    if finding:body+=facts['finding:'+finding[0]]+' '+facts['benefit:'+finding[0]]+'\n\n'
    body+='I can help with '+facts['service:frontend']+'. '
    if projects:body+=facts['project:'+projects[0]]+' '
    if links:body+='You can explore examples here: '+links[0]+' '
    body+='Could we have a brief conversation about a useful next step?'
    return AIWrittenDraft(subject='A thoughtful refinement for your website' if context['channel']=='email' else '',body=body,
        finding_ids=finding,service_ids=['frontend'],project_ids=projects,used_links=links,
        claims=[{'fact_id':i,'text':facts[i]} for i in identifiers],offers_walkthrough=False)


def human_written(context):
    from app.schemas.intelligence import HumanWrittenDraft
    output=written(context)
    return HumanWrittenDraft(subject=output.subject,body=output.body)
