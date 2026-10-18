"""One durable offline worker. No discovery, transport, AI or subprocess imports."""
import asyncio
import hashlib
import json
from contextlib import contextmanager
from datetime import timedelta,timezone
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select,func,update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.models.lead import now
from app.models.research import (ResearchPlanRevision,ResearchJob,ResearchStep,ResearchAttempt,
    ResearchApproval,ResearchEvent,ResearchWorkerLease)
from app.schemas.research import ResearchPlan,OfflineResult

def utc(value):return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

TERMINAL={'cancelled','failed','completed'}
MESSAGES={
 'created':'Foundation task saved and paused. No live research is connected.',
 'queued':'Offline checks queued.', 'paused':'Paused. No additional steps will start.',
 'cancelling':'Cancellation requested. Waiting for the active local check to stop.',
 'cancelled':'Cancelled. Previously completed results were preserved.',
 'claimed':'Local check started.', 'step_completed':'Local check completed; no external requests were made.',
 'completed':'Foundation checks completed. No businesses were discovered or researched.',
 'expired':'Task expired. Create a new plan revision to continue.',
 'budget_exhausted':'Task budget exhausted. Resume cannot reset it; create a new revision or cancel.',
 'retry_scheduled':'Local check failed. One bounded retry is waiting.',
 'step_failed':'Local check failed. Review details before creating a new revision.',
 'step_timeout':'Local check exceeded its reserved runtime slot.',
 'invalid_result':'Local check returned an invalid result; no output was persisted.',
 'interrupted':'Worker interrupted. Completed results are preserved; resume safe local steps explicitly.',
 'dispatch_uncertain':'Dispatch cannot be reconciled safely. No automatic replay is allowed. Cancel this task; provider reconciliation is not connected in 5.1.',
 'unsupported_action':'This foundation cannot execute external actions. No request was dispatched.',
}

def fingerprint(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def event(s,job,code,step=None,attempt=None):
    if code not in MESSAGES: raise ValueError('Unknown event code')
    s.add(ResearchEvent(job_id=job.id,code=code,step_id=step.id if step else None,attempt_id=attempt.id if attempt else None))

def changed(job,clock): job.version+=1;job.updated_at=clock()

async def offline_step(kind,plan_hash):
    # Deliberately no network, business lookup, user-code execution or artificial work.
    if kind not in {'validate_plan','summarize_plan'}: raise ValueError('Unsupported offline action')
    return OfflineResult(kind='plan_validated' if kind=='validate_plan' else 'foundation_summary',plan_hash=plan_hash)

class ResearchManager:
    def __init__(self,engine,runner=offline_step,clock=now,poll_seconds=.5,lease_seconds=15):
        self.engine=engine;self.runner=runner;self.clock=clock;self.poll_seconds=poll_seconds;self.lease_seconds=lease_seconds
        self.owner=str(uuid4());self.epoch=None;self.healthy=True;self.closing=False
        self.pump=None;self.beat=None;self.execution=None;self.active_job=None

    @contextmanager
    def write(self):
        try:
            with Session(self.engine) as s:
                # The first statement writes before any reads. SQLite serializes
                # creation, control, claiming and lease takeover across processes.
                s.execute(insert(ResearchWorkerLease).values(id=1,epoch=0).on_conflict_do_nothing())
                s.execute(update(ResearchWorkerLease).where(ResearchWorkerLease.id==1).values(epoch=ResearchWorkerLease.epoch))
                yield s
                s.commit()
        except SQLAlchemyError:
            self.halt()
            raise

    def halt(self):
        self.healthy=False
        execution=self.execution
        if execution and not execution.done():
            loop=execution.get_loop()
            if not loop.is_closed():loop.call_soon_threadsafe(execution.cancel)

    def require_healthy(self):
        if not self.healthy: raise HTTPException(503,'Research persistence is unavailable. Restore database access/migrations, then restart the backend. No new checks will start.')

    def create(self,payload):
        self.require_healthy()
        data=payload.plan.model_dump(mode='json');request_hash=fingerprint(payload.model_dump(mode='json'))
        with self.write() as s:
            existing=s.scalar(select(ResearchJob).where(ResearchJob.request_id==payload.request_id))
            if existing:
                if existing.request_hash!=request_hash: raise HTTPException(409,'Request ID already belongs to different task inputs.')
                identifier=existing.id
            else:
                timestamp=self.clock()
                if not timestamp<payload.plan.expires_at<=timestamp+timedelta(days=7): raise HTTPException(422,'Expiry must be in the future and within seven days.')
                previous=None
                if payload.based_on_job_id:
                    job=s.get(ResearchJob,payload.based_on_job_id)
                    if not job: raise HTTPException(404,'Previous task not found.')
                    previous=s.get(ResearchPlanRevision,job.plan_id)
                    latest=s.scalar(select(func.max(ResearchPlanRevision.revision)).where(ResearchPlanRevision.series_id==previous.series_id))
                    if latest!=previous.revision: raise HTTPException(409,'A newer plan revision exists. Open that task before revising.')
                plan=ResearchPlanRevision(series_id=previous.series_id if previous else str(uuid4()),revision=previous.revision+1 if previous else 1,
                    previous_id=previous.id if previous else None,fingerprint=fingerprint(data),data=data)
                s.add(plan);s.flush()
                job=ResearchJob(request_id=payload.request_id,request_hash=request_hash,plan_id=plan.id,status='paused')
                s.add(job);s.flush();identifier=job.id
                for position,kind in enumerate(('validate_plan','summarize_plan')):
                    s.add(ResearchStep(job_id=identifier,position=position,kind=kind,idempotency_key=fingerprint([identifier,plan.fingerprint,kind])))
                event(s,job,'created')
        return self.read(identifier)

    def read(self,identifier):
        with Session(self.engine) as s:
            job=s.get(ResearchJob,identifier)
            if not job: raise HTTPException(404,'Research task not found.')
            plan=s.get(ResearchPlanRevision,job.plan_id)
            steps=s.scalars(select(ResearchStep).where(ResearchStep.job_id==job.id).order_by(ResearchStep.position)).all()
            attempts=s.scalars(select(ResearchAttempt).join(ResearchStep).where(ResearchStep.job_id==job.id).order_by(ResearchAttempt.id)).all()
            approvals=s.scalars(select(ResearchApproval).where(ResearchApproval.job_id==job.id)).all()
            return {'id':job.id,'status':job.status,'version':job.version,'plan':plan.data,'plan_revision':plan.revision,'plan_hash':plan.fingerprint,
                'series_id':plan.series_id,'created_at':utc(job.created_at).isoformat(),'updated_at':utc(job.updated_at).isoformat(),
                'error_code':job.error_code,'message':MESSAGES.get(job.error_code,'Offline foundation only; live research is not connected.'),
                'next_retry_at':utc(job.next_retry_at).isoformat() if job.next_retry_at else None,
                'usage':{k:getattr(job,k) for k in ('attempts_used','runtime_reserved_ms','requests_used','gemini_attempts_used')},
                'progress':{'completed':sum(step.status=='succeeded' for step in steps),'total':len(steps),'businesses_researched':0},
                'steps':[{'id':step.id,'kind':step.kind,'status':step.status,'idempotency_key':step.idempotency_key,'result_ref':step.result_ref} for step in steps],
                'attempts':[{'id':a.id,'step_id':a.step_id,'number':a.number,'status':a.status,'dispatch_state':a.dispatch_state,'reserved_ms':a.reserved_ms,
                    'error_code':a.error_code,'started_at':utc(a.started_at).isoformat(),'finished_at':utc(a.finished_at).isoformat() if a.finished_at else None} for a in attempts],
                'approvals':[{'id':a.id,'step_id':a.step_id,'attempt_id':a.attempt_id,'reason':a.reason} for a in approvals]}

    def listing(self,limit,offset):
        with Session(self.engine) as s:
            ids=s.scalars(select(ResearchJob.id).order_by(ResearchJob.id.desc()).limit(limit).offset(offset)).all()
            total=s.scalar(select(func.count()).select_from(ResearchJob))
        return {'items':[self.read(i) for i in ids],'total':total,'limit':limit,'offset':offset}

    def events(self,identifier,limit,after):
        with Session(self.engine) as s:
            if not s.get(ResearchJob,identifier): raise HTTPException(404,'Research task not found.')
            rows=s.scalars(select(ResearchEvent).where(ResearchEvent.job_id==identifier,ResearchEvent.id>after).order_by(ResearchEvent.id).limit(limit)).all()
            return {'items':[{'id':r.id,'code':r.code,'message':MESSAGES[r.code],'step_id':r.step_id,'attempt_id':r.attempt_id,'created_at':utc(r.created_at).isoformat()} for r in rows],
                'next_after':rows[-1].id if rows else after,'limit':limit}

    def expired(self,s,job,plan):
        if self.clock()>=ResearchPlan.model_validate(plan.data).expires_at:
            job.status='failed';job.error_code='expired';changed(job,self.clock);event(s,job,'expired');return True
        return False

    def control(self,identifier,payload):
        self.require_healthy()
        with self.write() as s:
            job=s.get(ResearchJob,identifier)
            if not job: raise HTTPException(404,'Research task not found.')
            if job.version!=payload.version: raise HTTPException(409,'Task changed. Refresh and review its current state before trying again.')
            if job.status in TERMINAL: raise HTTPException(409,'This task is finished. Create a new plan revision instead.')
            if payload.action=='cancel':
                active=s.scalar(select(ResearchStep).where(ResearchStep.job_id==job.id,ResearchStep.status=='running'))
                job.status='cancelling' if active else 'cancelled';job.error_code=None
                if not active:
                    for step in s.scalars(select(ResearchStep).where(ResearchStep.job_id==job.id,ResearchStep.status.in_(['pending','interrupted']))):step.status='cancelled'
                changed(job,self.clock);event(s,job,job.status)
            elif payload.action=='pause':
                if job.status not in {'queued','running','waiting_for_retry'}: raise HTTPException(409,'Only queued, running or retrying tasks can be paused.')
                job.status='paused';changed(job,self.clock);event(s,job,'paused')
            else:
                if job.status not in {'paused','interrupted','waiting_for_retry'}: raise HTTPException(409,'This task cannot resume. Review its reason or create a new plan revision.')
                plan=s.get(ResearchPlanRevision,job.plan_id)
                if not self.expired(s,job,plan):
                    if s.scalar(select(ResearchStep).where(ResearchStep.job_id==job.id,ResearchStep.status=='uncertain')):
                        raise HTTPException(409,'Uncertain dispatch cannot be replayed.')
                    job.status='queued';job.error_code=None;changed(job,self.clock);event(s,job,'queued')
        return self.read(identifier)

    def owns(self,s):
        lease=s.get(ResearchWorkerLease,1)
        return lease.owner==self.owner and lease.epoch==self.epoch and lease.expires_at and utc(lease.expires_at)>self.clock()

    def acquire(self):
        self.require_healthy()
        with self.write() as s:
            lease=s.get(ResearchWorkerLease,1);timestamp=self.clock()
            if lease.owner and lease.owner!=self.owner and lease.expires_at and utc(lease.expires_at)>timestamp:return False
            takeover=lease.owner!=self.owner or self.epoch!=lease.epoch or not lease.expires_at or utc(lease.expires_at)<=timestamp
            if takeover:lease.epoch+=1
            lease.owner=self.owner;lease.expires_at=timestamp+timedelta(seconds=self.lease_seconds);self.epoch=lease.epoch
            if takeover:self.reconcile(s)
        return True

    def reconcile(self,s):
        # Only called after exclusive lease acquisition. Never disrupt a live owner.
        for step in s.scalars(select(ResearchStep).where(ResearchStep.status=='running')).all():
            job=s.get(ResearchJob,step.job_id)
            attempt=s.scalar(select(ResearchAttempt).where(ResearchAttempt.step_id==step.id).order_by(ResearchAttempt.id.desc()))
            unsafe=not step.replay_safe or step.kind=='external_reserved'
            if unsafe:
                step.status='uncertain';job.status='waiting_for_approval';job.error_code='dispatch_uncertain'
                if not s.scalar(select(ResearchApproval).where(ResearchApproval.step_id==step.id)):
                    s.add(ResearchApproval(job_id=job.id,step_id=step.id,attempt_id=attempt.id if attempt else None,reason='dispatch_uncertain'))
            else:
                step.status='interrupted';job.status='cancelled' if job.status=='cancelling' else 'paused' if job.status=='paused' else 'interrupted'
                job.error_code='interrupted'
            if attempt:
                attempt.status='uncertain' if unsafe else 'interrupted';attempt.dispatch_state='uncertain' if unsafe else 'finished';attempt.finished_at=self.clock();attempt.error_code=job.error_code
            if job.status=='cancelled':
                for pending in s.scalars(select(ResearchStep).where(ResearchStep.job_id==job.id,ResearchStep.status.in_(['pending','interrupted']))):pending.status='cancelled'
            changed(job,self.clock);event(s,job,job.error_code,step,attempt)
        # A crash between steps is also explicit, never an automatic restart.
        for job in s.scalars(select(ResearchJob).where(ResearchJob.status.in_(['running','cancelling']))).all():
            job.status='cancelled' if job.status=='cancelling' else 'interrupted';job.error_code='interrupted';changed(job,self.clock);event(s,job,'interrupted')

    def claim(self):
        self.require_healthy()
        with self.write() as s:
            if not self.healthy or not self.owns(s):return None
            if s.scalar(select(ResearchStep.id).where(ResearchStep.status=='running').limit(1)):return None
            timestamp=self.clock()
            jobs=s.scalars(select(ResearchJob).where(ResearchJob.status.in_(['queued','waiting_for_retry'])).order_by(ResearchJob.id)).all()
            for job in jobs:
                plan=s.get(ResearchPlanRevision,job.plan_id)
                if self.expired(s,job,plan):continue
                if job.next_retry_at and utc(job.next_retry_at)>timestamp:continue
                step=s.scalar(select(ResearchStep).where(ResearchStep.job_id==job.id,ResearchStep.status.in_(['pending','interrupted'])).order_by(ResearchStep.position))
                if not step:
                    if s.scalar(select(ResearchStep).where(ResearchStep.job_id==job.id,ResearchStep.status!='succeeded')):continue
                    job.status='completed';job.error_code=None;changed(job,self.clock);event(s,job,'completed');continue
                if step.kind not in {'validate_plan','summarize_plan'} or not step.replay_safe:
                    job.status='waiting_for_approval';job.error_code='unsupported_action';step.status='uncertain'
                    s.add(ResearchApproval(job_id=job.id,step_id=step.id,reason='unsupported_action'));changed(job,self.clock);event(s,job,'unsupported_action',step);continue
                if s.scalar(select(ResearchStep).where(ResearchStep.job_id==job.id,ResearchStep.position<step.position,ResearchStep.status!='succeeded')):continue
                bounds=plan.data['budgets'];remaining=bounds['max_runtime_seconds']*1000-job.runtime_reserved_ms
                if job.attempts_used>=bounds['max_attempts'] or remaining<=0:
                    job.status='waiting_for_budget';job.error_code='budget_exhausted';changed(job,self.clock);event(s,job,'budget_exhausted',step);continue
                slot=min(1000,remaining,max(0,int((ResearchPlan.model_validate(plan.data).expires_at-timestamp).total_seconds()*1000)))
                if slot<=0:continue
                count=s.scalar(select(func.count()).select_from(ResearchAttempt).where(ResearchAttempt.step_id==step.id))
                attempt=ResearchAttempt(step_id=step.id,number=count+1,owner=self.owner,epoch=self.epoch,reserved_ms=slot,dispatch_state='started',started_at=timestamp)
                s.add(attempt);s.flush();step.status='running';job.status='running';job.next_retry_at=None
                job.attempts_used+=1;job.runtime_reserved_ms+=slot;changed(job,self.clock);event(s,job,'claimed',step,attempt)
                return {'job_id':job.id,'attempt_id':attempt.id,'kind':step.kind,'hash':plan.fingerprint,'seconds':slot/1000}
        return None

    def finish(self,claim,result=None,error=False,cancelled=False,error_code='step_failed'):
        with self.write() as s:
            if not self.owns(s):return False
            attempt=s.get(ResearchAttempt,claim['attempt_id']);step=s.get(ResearchStep,attempt.step_id);job=s.get(ResearchJob,step.job_id)
            if attempt.status!='started' or attempt.owner!=self.owner or attempt.epoch!=self.epoch or step.status!='running':return False
            attempt.finished_at=self.clock();attempt.dispatch_state='finished';plan=s.get(ResearchPlanRevision,job.plan_id)
            if cancelled or job.status=='cancelling' or self.closing:
                # Persisted user cancellation takes precedence over shutdown.
                # Otherwise a simultaneous shutdown would make it resumable.
                interrupted=self.closing and job.status!='cancelling'
                attempt.status='interrupted' if interrupted else 'cancelled';step.status='interrupted' if interrupted else 'cancelled'
                job.status='paused' if interrupted and job.status=='paused' else 'interrupted' if interrupted else 'cancelled'
                job.error_code='interrupted' if interrupted else None;event(s,job,'interrupted' if interrupted else 'cancelled',step,attempt)
            elif self.expired(s,job,plan):
                attempt.status='failed';attempt.error_code='expired';step.status='failed'
            elif error:
                attempt.status='failed';attempt.error_code=error_code
                if attempt.number<2:
                    step.status='pending';job.status='paused' if job.status=='paused' else 'waiting_for_retry';job.next_retry_at=self.clock()+timedelta(seconds=2);job.error_code='retry_scheduled';event(s,job,'retry_scheduled',step,attempt)
                else:
                    step.status='failed';job.status='failed';job.error_code='step_failed';event(s,job,'step_failed',step,attempt)
            else:
                parsed=OfflineResult.model_validate(result)
                expected='plan_validated' if step.kind=='validate_plan' else 'foundation_summary'
                if parsed.kind!=expected or parsed.plan_hash!=plan.fingerprint:raise ValueError('Invalid offline result')
                attempt.status='succeeded';step.status='succeeded';step.result_ref=parsed.model_dump();job.error_code=None
                event(s,job,'step_completed',step,attempt)
                if job.status!='paused':
                    remaining=s.scalar(select(func.count()).select_from(ResearchStep).where(ResearchStep.job_id==job.id,ResearchStep.id!=step.id,ResearchStep.status!='succeeded'))
                    job.status='queued' if remaining else 'completed'
                    if not remaining:event(s,job,'completed')
            if job.status=='cancelled':
                for pending in s.scalars(select(ResearchStep).where(ResearchStep.job_id==job.id,ResearchStep.status.in_(['pending','interrupted']))):pending.status='cancelled'
            changed(job,self.clock)
        return True

    async def tick(self):
        if not self.healthy or self.closing:return
        try:
            if not self.acquire():return
            claim=self.claim()
            if not claim or not self.healthy:return
            self.active_job=claim['job_id'];self.execution=asyncio.create_task(self.runner(claim['kind'],claim['hash']))
            try:
                async with asyncio.timeout(claim['seconds']):result=await self.execution
                # Validate before the final transaction; never persist arbitrary runner output.
                parsed=OfflineResult.model_validate(result)
                if parsed.plan_hash!=claim['hash'] or parsed.kind!=('plan_validated' if claim['kind']=='validate_plan' else 'foundation_summary'):raise ValueError('Invalid local result')
                if self.healthy:self.finish(claim,result=parsed)
            except asyncio.CancelledError:
                if self.healthy:self.finish(claim,cancelled=True)
            except TimeoutError:
                if self.healthy:self.finish(claim,error=True,error_code='step_timeout')
            except ValueError:
                if self.healthy:self.finish(claim,error=True,error_code='invalid_result')
            except Exception:
                if self.healthy:self.finish(claim,error=True)
            finally:self.active_job=None;self.execution=None
        except SQLAlchemyError:self.halt()
        except Exception:self.halt()

    async def heartbeat(self):
        while not self.closing and self.healthy:
            await asyncio.sleep(max(.01,self.lease_seconds/3))
            if self.closing:break
            try:
                with self.write() as s:
                    if self.epoch is None:continue
                    if not self.owns(s):
                        if self.execution and not self.execution.done():self.execution.cancel()
                        self.epoch=None;continue
                    s.get(ResearchWorkerLease,1).expires_at=self.clock()+timedelta(seconds=self.lease_seconds)
                    if self.active_job:
                        job=s.get(ResearchJob,self.active_job)
                        if job.status=='cancelling' and self.execution and not self.execution.done():self.execution.cancel()
            except SQLAlchemyError:self.halt()

    async def loop(self):
        while not self.closing and self.healthy:
            await self.tick()
            if not self.closing:await asyncio.sleep(self.poll_seconds)

    def start(self):
        try:self.acquire()
        except SQLAlchemyError:return
        self.pump=asyncio.create_task(self.loop());self.beat=asyncio.create_task(self.heartbeat())

    async def shutdown(self):
        self.closing=True
        if self.execution and not self.execution.done():self.execution.cancel()
        if self.pump:
            if not self.execution:self.pump.cancel()
            await asyncio.gather(self.pump,return_exceptions=True)
        if self.beat:self.beat.cancel();await asyncio.gather(self.beat,return_exceptions=True)
        if self.healthy:
            try:
                with self.write() as s:
                    if self.owns(s):
                        lease=s.get(ResearchWorkerLease,1);lease.owner=None;lease.expires_at=None
            except SQLAlchemyError:self.halt()

    def status(self):
        self.require_healthy()
        with Session(self.engine) as s:
            lease=s.get(ResearchWorkerLease,1)
            active=bool(lease and lease.owner and lease.expires_at and utc(lease.expires_at)>self.clock())
        return {'mode':'offline_foundation','worker':'active' if active else 'waiting','external_dispatch_enabled':False,
            'message':'Only local plan checks are connected. Discovery, website research and Gemini are disabled for research jobs.'}
