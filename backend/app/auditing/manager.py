import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.auditing.runner import run_audit
from app.core.settings import PAGESPEED_API_KEY, PAGESPEED_DAILY_LIMIT, PAGESPEED_ENABLED
from app.models.audit import Audit
from app.models.lead import Lead, now
from app.schemas.audit import AuditRead
from app.services.urls import normalize_url

ACTIVE = {'queued', 'running'}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class AuditManager:
    def __init__(self, engine, runner=run_audit):
        self.engine = engine
        self.runner = runner
        self.tasks = {}
        self.lock = asyncio.Lock()
        self.closing = False

    def recover(self):
        try:
            with Session(self.engine) as session:
                session.execute(update(Audit).where(Audit.status.in_(ACTIVE)).values(
                    status='interrupted', progress='Interrupted by backend restart', finished_at=now(),
                    error_code='interrupted', error='Backend restarted before completion. Retry manually after the cooldown.'))
                session.commit()
        except SQLAlchemyError:
            # Missing schema stays explicitly unavailable through /api/health; startup does not bypass migrations.
            pass

    def read(self, audit_id):
        with Session(self.engine) as session:
            audit = session.get(Audit, audit_id)
            if audit is None: raise HTTPException(404, 'Audit not found.')
            return AuditRead.model_validate(audit)

    def change(self, audit_id, **fields):
        with Session(self.engine) as session:
            audit = session.get(Audit, audit_id)
            if audit is not None:
                for key, value in fields.items(): setattr(audit, key, value)
                session.commit()

    async def start(self, payload):
        url, hostname = normalize_url(payload.website_url)
        if payload.use_pagespeed and not PAGESPEED_ENABLED:
            raise HTTPException(422, 'PageSpeed is not enabled in the backend. The HTML audit works without it.')
        async with self.lock:
            if sum(not task.done() for task in self.tasks.values()) >= 2:
                raise HTTPException(429, 'Two audits are already active. Wait or cancel one before starting another.', headers={'Retry-After': '10'})
            with Session(self.engine) as session:
                timestamp = now()
                latest = session.scalar(select(Audit).where(Audit.hostname == hostname).order_by(Audit.created_at.desc()).limit(1))
                if latest and utc(latest.next_allowed_at) > timestamp:
                    seconds = max(1, int((utc(latest.next_allowed_at) - timestamp).total_seconds()) + 1)
                    raise HTTPException(429, f'Website cooldown: wait {seconds} seconds before retrying this hostname.', headers={'Retry-After': str(seconds)})
                global_latest = session.scalar(select(Audit).order_by(Audit.created_at.desc()).limit(1))
                if global_latest and timestamp - utc(global_latest.created_at) < timedelta(seconds=10):
                    raise HTTPException(429, 'Local audit rate limit: wait 10 seconds between starts.', headers={'Retry-After': '10'})
                if payload.lead_id is not None:
                    lead = session.get(Lead, payload.lead_id)
                    if lead is None: raise HTTPException(404, 'Lead not found.')
                    if normalize_url(lead.website_url)[1] != hostname:
                        raise HTTPException(422, 'The audit hostname must match the linked lead.')
                audit = Audit(lead_id=payload.lead_id, requested_url=url, hostname=hostname,
                              pagespeed_requested=payload.use_pagespeed, next_allowed_at=timestamp + timedelta(seconds=60))
                session.add(audit); session.commit(); session.refresh(audit)
                result = AuditRead.model_validate(audit)
            task = asyncio.create_task(self.work(result))
            self.tasks[result.id] = task
            task.add_done_callback(lambda _task, audit_id=result.id: self.tasks.pop(audit_id, None))
            return result

    async def reserve_pagespeed(self, audit_id):
        async with self.lock:
            with Session(self.engine) as session:
                provider_block = session.scalar(select(func.count()).select_from(Audit).where(Audit.report['pagespeed']['cooldown_until'].as_string() > now().isoformat()))
                if provider_block: return False
                attempts = session.scalar(select(func.count()).select_from(Audit).where(Audit.pagespeed_attempted_at >= now() - timedelta(hours=24)))
                if attempts >= PAGESPEED_DAILY_LIMIT: return False
                audit = session.get(Audit, audit_id)
                audit.pagespeed_attempted_at = now()
                session.commit()
                return True

    async def work(self, audit):
        try:
            self.change(audit.id, status='running', progress='Validating public network access')
            async def progress(message): self.change(audit.id, progress=message)
            async def reserve(): return await self.reserve_pagespeed(audit.id)
            async with asyncio.timeout(100):
                status, report, error = await self.runner(audit.requested_url, audit.pagespeed_requested, progress, reserve, key=PAGESPEED_API_KEY)
            fields = {'status': status, 'report': report, 'progress': 'Audit finished' if not error else 'Audit stopped',
                      'finished_at': now(), 'error': str(error) if error else None, 'error_code': error.code if error else None}
            psi_retry = report.get('pagespeed', {}).get('retry_after')
            if psi_retry:
                try:
                    timestamp = now()
                    if str(psi_retry).isdigit():
                        seconds = int(psi_retry)
                        maximum = (datetime.max.replace(tzinfo=timezone.utc) - timestamp).total_seconds()
                        target = datetime.max.replace(tzinfo=timezone.utc) if seconds >= maximum else timestamp + timedelta(seconds=seconds)
                    else:
                        target = utc(parsedate_to_datetime(psi_retry))
                    report['pagespeed']['cooldown_until'] = max(timestamp + timedelta(seconds=60), target).isoformat()
                except (ValueError, TypeError, OverflowError):
                    report['pagespeed']['cooldown_until'] = (now() + timedelta(hours=24)).isoformat()
            retry_after = report.get('retry_after')
            if retry_after:
                try:
                    timestamp = now()
                    if str(retry_after).isdigit():
                        seconds = int(retry_after)
                        maximum = (datetime.max.replace(tzinfo=timezone.utc) - timestamp).total_seconds()
                        target = datetime.max.replace(tzinfo=timezone.utc) if seconds >= maximum else timestamp + timedelta(seconds=seconds)
                    else:
                        target = utc(parsedate_to_datetime(retry_after))
                    fields['next_allowed_at'] = max(timestamp + timedelta(seconds=60), target)
                except (ValueError, TypeError, OverflowError):
                    fields['next_allowed_at'] = now() + timedelta(hours=24)
            self.change(audit.id, **fields)
        except asyncio.CancelledError:
            interrupted = self.closing
            self.change(audit.id, status='interrupted' if interrupted else 'cancelled', progress='Interrupted' if interrupted else 'Cancelled',
                        finished_at=now(), error_code='interrupted' if interrupted else None,
                        error='Backend stopped before completion. Retry manually.' if interrupted else None)
        except TimeoutError:
            self.change(audit.id, status='error', progress='Timed out', finished_at=now(), error_code='timeout', error='The total 100-second audit budget expired. No results were invented.')
        except Exception:
            # Do not persist/log exception bodies or provider API keys.
            try: self.change(audit.id, status='error', progress='Stopped', finished_at=now(), error_code='internal_error', error='Audit failed unexpectedly. No results were substituted; retry manually.')
            except SQLAlchemyError: pass

    async def cancel(self, audit_id):
        audit = self.read(audit_id)
        task = self.tasks.get(audit_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # A task cancelled before its coroutine starts cannot persist its final state itself.
            if self.read(audit_id).status in ACTIVE:
                self.change(audit_id, status='cancelled', progress='Cancelled', finished_at=now())
        elif audit.status in ACTIVE:
            self.change(audit_id, status='interrupted', progress='Interrupted', finished_at=now(), error_code='interrupted', error='No active worker remains; retry manually.')
        return self.read(audit_id)

    async def shutdown(self):
        self.closing = True
        tasks = list(self.tasks.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
