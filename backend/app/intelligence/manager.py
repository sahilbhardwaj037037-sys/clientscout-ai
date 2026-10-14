import asyncio
from datetime import timedelta
from email.utils import parsedate_to_datetime
from fastapi import HTTPException
from sqlalchemy import select,func,update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.discovery.manager import utc
from app.models.intelligence import BusinessIdentity,Enrichment,ContactMethod
from app.models.audit import Audit
from app.models.lead import now
from app.intelligence.targets import ensure_identity
from app.intelligence.enrichment import enrich
from app.services.urls import normalize_url

class EnrichmentManager:
    def __init__(self,engine,runner=enrich):self.engine=engine;self.runner=runner;self.tasks={};self.lock=asyncio.Lock();self.closing=False
    def recover(self):
        try:
            with Session(self.engine) as s:s.execute(update(Enrichment).where(Enrichment.status.in_(['queued','running'])).values(status='interrupted',progress='Interrupted',finished_at=now(),error='Backend restarted; no automatic source retry.'));s.commit()
        except SQLAlchemyError:pass
    def read(self,identifier):
        with Session(self.engine) as s:
            row=s.get(Enrichment,identifier)
            if row is None:raise HTTPException(404,'Enrichment not found.')
            return {k:(utc(v).isoformat() if hasattr(v,'tzinfo') else v) for k,v in row.__dict__.items() if not k.startswith('_')}
    def change(self,identifier,**fields):
        with Session(self.engine) as s:
            row=s.get(Enrichment,identifier)
            if row:
                for key,value in fields.items():setattr(row,key,value)
                s.commit()
    async def start(self,payload):
        async with self.lock:
            with Session(self.engine) as s:
                identity=ensure_identity(s,payload);snapshot=identity.snapshot.copy();url=payload.website_url or snapshot.get('website_url')
                if url:
                    from app.schemas.intelligence import EnrichCreate
                    url=EnrichCreate.safe_url(url)
                hostname=normalize_url(url)[1] if url else None
                prior=s.scalar(select(Enrichment).where(Enrichment.identity_id==identity.id,Enrichment.requested_url==url,Enrichment.official_confirmed==payload.official_confirmed,Enrichment.directory_requested==payload.use_directory,Enrichment.status=='complete',Enrichment.created_at>=now()-timedelta(hours=24)).order_by(Enrichment.id.desc()))
                if prior and prior.report and prior.report.get('business_snapshot')==snapshot and not payload.refresh:s.commit();return dict(self.read(prior.id),reused=True)
                if any(not task.done() for task in self.tasks.values()):raise HTTPException(429,'One enrichment is active. Wait or cancel it first.')
                latest=s.scalar(select(Enrichment).order_by(Enrichment.id.desc()))
                if latest and now()-utc(latest.created_at)<timedelta(seconds=10):raise HTTPException(429,'Wait 10 seconds between enrichment starts.')
                if s.scalar(select(func.count()).select_from(Enrichment).where(Enrichment.created_at>=now()-timedelta(hours=24)))>=10:raise HTTPException(429,'Local limit: 10 enrichment starts per rolling 24 hours.')
                if hostname:
                    for model in (Enrichment,Audit):
                        row=s.scalar(select(model).where(model.hostname==hostname).order_by(model.created_at.desc()))
                        if row and utc(row.next_allowed_at)>now():raise HTTPException(429,'This website has an active audit/enrichment cooldown; try after '+utc(row.next_allowed_at).isoformat())
                row=Enrichment(identity_id=identity.id,requested_url=url,hostname=hostname,official_confirmed=payload.official_confirmed,directory_requested=payload.use_directory,next_allowed_at=now()+timedelta(seconds=60))
                s.add(row);s.commit();s.refresh(row);identifier=row.id
            task=asyncio.create_task(self.work(identifier,snapshot,url,payload));self.tasks[identifier]=task;task.add_done_callback(lambda _,i=identifier:self.tasks.pop(i,None));return self.read(identifier)
    async def work(self,identifier,snapshot,url,payload):
        try:
            self.change(identifier,status='running',progress='Preparing public business sources')
            async def progress(message):self.change(identifier,progress=message)
            async with asyncio.timeout(75):status,report,error=await self.runner(snapshot,url,payload.official_confirmed,payload.use_directory,progress)
            cooldown=now()+timedelta(seconds=60)
            if report.get('retry_after'):
                try:
                    raw=report['retry_after']
                    if str(raw).isdigit():
                        from datetime import datetime,timezone
                        maximum=datetime.max.replace(tzinfo=timezone.utc)
                        cooldown=max(cooldown,maximum if int(raw)>=(maximum-now()).total_seconds() else now()+timedelta(seconds=int(raw)))
                    else:cooldown=max(cooldown,utc(parsedate_to_datetime(raw)))
                except (ValueError,TypeError,OverflowError):cooldown=now()+timedelta(hours=24)
            with Session(self.engine) as s:
                row=s.get(Enrichment,identifier)
                if row is None:return
                row.status=status;row.report=report;row.error=error;row.progress='Source checks finished' if not error else 'Source checks stopped';row.finished_at=now();row.next_allowed_at=cooldown
                for c in report['contacts']:s.add(ContactMethod(enrichment_id=identifier,kind=c['kind'],value=c['value'],status=c['status'],provenance={k:v for k,v in c.items() if k not in {'kind','value','status'}}))
                s.commit()
        except asyncio.CancelledError:self.change(identifier,status='interrupted' if self.closing else 'cancelled',progress='Interrupted' if self.closing else 'Cancelled',finished_at=now())
        except TimeoutError:self.change(identifier,status='error',progress='Timed out',finished_at=now(),error='75-second enrichment budget expired; no absence or contact data inferred.')
        except Exception:
            try:self.change(identifier,status='error',progress='Stopped',finished_at=now(),error='Source enrichment failed. No contact methods were invented.')
            except SQLAlchemyError:pass
    async def cancel(self,identifier):
        self.read(identifier);task=self.tasks.get(identifier)
        if task and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
        if self.read(identifier)['status'] in {'queued','running'}:self.change(identifier,status='cancelled',progress='Cancelled',finished_at=now())
        return self.read(identifier)
    async def shutdown(self):
        self.closing=True;tasks=list(self.tasks.values())
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
