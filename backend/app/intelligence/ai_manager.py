import asyncio
from datetime import timedelta
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func,select,update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.settings import GEMINI_API_KEY,GEMINI_MODEL,GEMINI_DAILY_LIMIT
from app.discovery.manager import utc
from app.models.intelligence import AIUsage,Assessment
from app.models.lead import now
from app.providers.gemini import select_context,write_proposal,GeminiFailure
from app.intelligence.writer import WRITER_MODEL,WritingValidationError,schema_diagnostics
from app.intelligence.profile import read_profile
from app.intelligence.human_writer import human_context,compose_human,HUMAN_VERSION,HUMAN_VERSIONS
from app.intelligence.freshness import require_current

def failure_result(error):
    result={'error':str(error) if isinstance(error,(GeminiFailure,HTTPException)) else 'AI operation failed; no simulated output.'}
    if isinstance(error,GeminiFailure) and error.diagnostics:result['diagnostics']=error.diagnostics
    return result

class AIManager:
    def __init__(self,engine,provider=select_context,writer_provider=write_proposal):self.engine=engine;self.provider=provider;self.writer_provider=writer_provider;self.tasks={};self.lock=asyncio.Lock()
    def recover(self):
        try:
            with Session(self.engine) as s:s.execute(update(AIUsage).where(AIUsage.status.in_(['reserved','running','retrying'])).values(status='interrupted',result={'error':'Backend restarted. No automatic AI call resumed.'}));s.commit()
        except SQLAlchemyError:pass
    def read(self,identifier):
        with Session(self.engine) as s:
            row=s.get(AIUsage,identifier)
            if not row:raise HTTPException(404,'AI request not found.')
            return {k:(utc(v).isoformat() if hasattr(v,'tzinfo') else v) for k,v in row.__dict__.items() if not k.startswith('_')}
    def budget(self,s):
        if s.scalar(select(func.count()).select_from(AIUsage).where(AIUsage.created_at>=now()-timedelta(hours=24)))>=GEMINI_DAILY_LIMIT:raise HTTPException(429,'Local Gemini attempted/reserved request budget exhausted.')
        blocked=s.scalar(select(AIUsage).where(AIUsage.cooldown_until>now()).order_by(AIUsage.id.desc()))
        if blocked:raise HTTPException(429,'Gemini provider cooldown active; retry after '+utc(blocked.cooldown_until).isoformat())
    async def start(self,assessment_id,purpose,channel=None,include_profile=False):
        if not GEMINI_API_KEY:raise HTTPException(503,'Gemini key is not configured. Deterministic scoring and local templates remain available.')
        if purpose=='draft' and GEMINI_MODEL!=WRITER_MODEL:raise HTTPException(503,'Configure '+WRITER_MODEL+' for Gemini AI Writer. No automatic model switch is permitted.')
        async with self.lock:
            if any(not t.done() for t in self.tasks.values()):raise HTTPException(429,'One Gemini request is active.')
            with Session(self.engine) as s:
                self.budget(s);assessment=s.get(Assessment,assessment_id)
                if not assessment:raise HTTPException(404,'Assessment not found.')
                require_current(s,assessment)
                public_profile=None
                if purpose=='draft':
                    profile=read_profile(self.engine)
                    public_profile=profile.model_dump() if include_profile else profile.model_copy(update={'display_name':'','portfolio_url':'','instagram_url':'','projects':[],'allow_walkthrough_offer':False}).model_dump()
                    human_context(assessment,channel,public_profile)
                latest=s.scalar(select(AIUsage).order_by(AIUsage.id.desc()))
                if latest and now()-utc(latest.created_at)<timedelta(seconds=30):raise HTTPException(429,'Wait 30 seconds between Gemini starts.')
                row=AIUsage(purpose=purpose,model=GEMINI_MODEL,request={'assessment_id':assessment_id,'channel':channel,**({'writer_profile':public_profile,'writer_version':HUMAN_VERSION,**HUMAN_VERSIONS} if purpose=='draft' else {})},status='reserved');s.add(row);s.commit();identifier=row.id
            task=asyncio.create_task(self.work(identifier));self.tasks[identifier]=task;task.add_done_callback(lambda _,i=identifier:self.tasks.pop(i,None));return self.read(identifier)
    async def work(self,identifier):
        attempt_id=identifier;pending_usage={}
        try:
            async with asyncio.timeout(50):
                for attempt in range(2):
                    with Session(self.engine) as s:
                        parent=s.get(AIUsage,identifier);assessment=s.get(Assessment,parent.request['assessment_id'])
                        if not assessment:raise GeminiFailure(-1,'Business/assessment was removed before generation.')
                        require_current(s,assessment)
                        purpose=parent.purpose;request_data=parent.request
                        attempt_row=parent
                        if attempt:
                            self.budget(s);attempt_row=AIUsage(purpose=parent.purpose,model=GEMINI_MODEL,status='running',request={'parent_id':identifier});s.add(attempt_row)
                        else:parent.status='running'
                        s.commit();attempt_id=attempt_row.id
                        # Detach bounded immutable assessment snapshot before any await.
                        s.refresh(assessment);s.expunge(assessment)
                    try:
                        if purpose=='draft':
                            context=human_context(assessment,request_data['channel'],request_data['writer_profile'])
                            selection,tokens=await self.writer_provider(context)
                        else:selection,tokens=await self.provider(assessment)
                        pending_usage=tokens
                    except GeminiFailure as error:
                        with Session(self.engine) as s:
                            pending_usage=error.usage
                            row=s.get(AIUsage,attempt_id)
                            for key,value in pending_usage.items():setattr(row,key,value)
                            row.status='retrying' if attempt==0 and error.code in {500,503} else 'error';row.result=failure_result(error)
                            if error.code==429:row.cooldown_until=now()+timedelta(hours=1)
                            s.commit()
                        if attempt==0 and error.code in {500,503}:pending_usage={};await asyncio.sleep(2);continue
                        raise
                    with Session(self.engine) as s:
                        parent=s.get(AIUsage,identifier);row=s.get(AIUsage,attempt_id);row.status='complete';row.input_tokens=tokens['input_tokens'];row.output_tokens=tokens['output_tokens']
                        current=s.get(Assessment,assessment.id)
                        if not current:raise GeminiFailure(-1,'Assessment removed; no draft saved.')
                        require_current(s,current)
                        if parent.purpose=='draft':
                            context=human_context(current,parent.request['channel'],parent.request['writer_profile'])
                            try:draft=compose_human(current,selection,context,parent.model)
                            except ValidationError as error:raise GeminiFailure(-1,'Gemini writing failed structured validation. No draft or fallback was saved. Validation rule: schema_violation.',{**schema_diagnostics(error),**HUMAN_VERSIONS,'disposition':'hard_blocked'}) from None
                            except WritingValidationError as error:raise GeminiFailure(-1,'Gemini writing failed evidence validation. No draft or fallback was saved. Validation rule: '+error.rule+'.',{'stage':'validation','rule':error.rule,'reason':error.reason,'disposition':'hard_blocked',**HUMAN_VERSIONS}) from None
                            except (ValueError,TypeError):raise GeminiFailure(-1,'Gemini writing failed evidence validation. No draft or fallback was saved.') from None
                            s.add(draft);s.flush();parent.result={'draft_id':draft.id}
                        else:current.ai_context={'selection':selection.model_dump(),'description':'Gemini selected approved evidence/services; deterministic facts, classification and score unchanged.'};parent.result={'assessment_id':current.id}
                        parent.status='complete';s.commit();return
        except asyncio.CancelledError:
            self.finish_failed(identifier,attempt_id,'interrupted',{'error':'Local AI worker stopped. A delivered provider request cannot be recalled.'},pending_usage)
        except Exception as error:
            self.finish_failed(identifier,attempt_id,'error',failure_result(error),pending_usage)

    def finish_failed(self,identifier,attempt_id,status,result,usage):
        # Final validation/transaction errors must also terminate the retry row.
        # Usage belongs to the actual attempt only, avoiding double counting.
        from app.providers.gemini import safe_usage
        try:
            with Session(self.engine) as s:
                for row_id in {identifier,attempt_id}:
                    row=s.get(AIUsage,row_id)
                    if row:
                        row.status=status;row.result=result
                        if row_id==attempt_id:
                            for key,value in safe_usage(usage).items():setattr(row,key,value)
                s.commit()
        except SQLAlchemyError:pass
    async def shutdown(self):
        tasks=list(self.tasks.values())
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
