import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.settings import DISCOVERY_ENABLED, OVERPASS_API_URL
from app.models.discovery import DiscoveryCache, DiscoverySearch
from app.models.lead import now
from app.providers.overpass import OverpassProvider, ProviderFailure
from app.schemas.discovery import SearchRead


def utc(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class DiscoveryManager:
    def __init__(self, engine, provider=None):
        self.engine = engine
        self.provider = provider or OverpassProvider(OVERPASS_API_URL)
        self.tasks = {}
        self.lock = asyncio.Lock()
        self.closing = False

    def recover(self):
        try:
            with Session(self.engine) as session:
                session.execute(update(DiscoverySearch).where(DiscoverySearch.status.in_(['queued','running'])).values(status='interrupted', progress='Interrupted', finished_at=now(), error='Backend restarted before completion. Retry manually; provider requests are never resumed automatically.'))
                session.commit()
        except SQLAlchemyError: pass

    def cache_get(self, key):
        with Session(self.engine) as session:
            record = session.get(DiscoveryCache, key)
            return record.value if record is not None and utc(record.expires_at) > now() else None

    def cache_put(self, key, value):
        with Session(self.engine) as session:
            record = session.get(DiscoveryCache, key)
            if record is None: record = DiscoveryCache(key=key); session.add(record)
            record.value = value; record.expires_at = now() + timedelta(hours=24); session.commit()

    def read(self, identifier):
        with Session(self.engine) as session:
            record = session.get(DiscoverySearch, identifier)
            if record is None: raise HTTPException(404, 'Discovery search not found.')
            return SearchRead.model_validate(record)

    def change(self, identifier, **fields):
        with Session(self.engine) as session:
            record = session.get(DiscoverySearch, identifier)
            if record is not None:
                for key, value in fields.items(): setattr(record, key, value)
                session.commit()

    async def start(self, query):
        if not DISCOVERY_ENABLED: raise HTTPException(503, 'Discovery is disabled by backend configuration. Manual URL/CSV import remains available.')
        async with self.lock:
            if any(not task.done() for task in self.tasks.values()): raise HTTPException(429, 'A discovery search is active. Wait or cancel it before starting another.')
            with Session(self.engine) as session:
                timestamp = now()
                latest = session.scalar(select(DiscoverySearch).order_by(DiscoverySearch.id.desc()).limit(1))
                if latest and utc(latest.cooldown_until) > timestamp:
                    seconds = int((utc(latest.cooldown_until) - timestamp).total_seconds()) + 1
                    raise HTTPException(429, f'Provider cooldown: wait {seconds} seconds before another search.', headers={'Retry-After': str(seconds)})
                count = session.scalar(select(func.count()).select_from(DiscoverySearch).where(DiscoverySearch.created_at >= timestamp - timedelta(hours=24)))
                if count >= 20: raise HTTPException(429, 'Local limit of 20 searches per rolling 24 hours reached. Use saved results or try later.')
                session.execute(delete(DiscoveryCache).where(DiscoveryCache.expires_at <= timestamp))
                record = DiscoverySearch(query=query.model_dump(), cooldown_until=timestamp + timedelta(seconds=30))
                session.add(record); session.commit(); session.refresh(record)
                result = SearchRead.model_validate(record)
            task = asyncio.create_task(self.work(result.id, query))
            self.tasks[result.id] = task
            task.add_done_callback(lambda _task, identifier=result.id: self.tasks.pop(identifier, None))
            return result

    async def work(self, identifier, query):
        try:
            self.change(identifier, status='running', progress='Preparing configured provider search')
            diagnostics = []
            async def progress(message, diagnostic=None):
                if diagnostic is not None:
                    diagnostics.append(diagnostic)
                    self.change(identifier, progress=message, diagnostics=diagnostics.copy())
                else: self.change(identifier, progress=message)
            async with asyncio.timeout(100):
                result = await self.provider.search(query, progress, self.cache_get, self.cache_put)
            self.change(identifier, status='complete', progress=f"Search finished: {len(result['items'])} source records", finished_at=now(), result=result)
        except asyncio.CancelledError:
            self.change(identifier, status='interrupted' if self.closing else 'cancelled', progress='Interrupted' if self.closing else 'Cancelled', finished_at=now(), error='Backend stopped before completion.' if self.closing else None)
        except ProviderFailure as error:
            timestamp = now()
            maximum = (datetime.max.replace(tzinfo=timezone.utc) - timestamp).total_seconds()
            next_allowed = datetime.max.replace(tzinfo=timezone.utc) if error.retry_seconds >= maximum else timestamp + timedelta(seconds=max(30, error.retry_seconds))
            self.change(identifier, status='error', progress='Provider search stopped', finished_at=timestamp, error=str(error), cooldown_until=next_allowed)
        except TimeoutError:
            self.change(identifier, status='error', progress='Timed out', finished_at=now(), error='The 100-second search budget expired. No records were substituted.')
        except Exception:
            try: self.change(identifier, status='error', progress='Stopped', finished_at=now(), error='Discovery failed unexpectedly. No records were substituted; check provider configuration and retry later.')
            except SQLAlchemyError: pass

    async def cancel(self, identifier):
        record = self.read(identifier)
        task = self.tasks.get(identifier)
        if task is not None and not task.done():
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
            if self.read(identifier).status in {'queued','running'}: self.change(identifier, status='cancelled', progress='Cancelled', finished_at=now())
        elif record.status in {'queued','running'}:
            self.change(identifier, status='interrupted', progress='Interrupted', finished_at=now(), error='Worker is no longer active. Retry manually.')
        return self.read(identifier)

    async def shutdown(self):
        self.closing = True
        tasks = list(self.tasks.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
