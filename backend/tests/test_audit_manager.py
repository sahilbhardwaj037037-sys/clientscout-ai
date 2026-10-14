import asyncio
from datetime import timedelta
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auditing.manager import AuditManager
from app.models.audit import Audit
from app.models.lead import Lead, now
from app.schemas.audit import AuditCreate
from app.auditing.network import AuditFailure
from fastapi import HTTPException

def payload(url='https://example.com/', **kwargs):
    return AuditCreate(website_url=url, permission_confirmed=True, **kwargs)

async def completed(url, use_pagespeed, progress, reserve, **kwargs):
    await progress('Fixture measurement')
    return 'complete', {'requested_url': url, 'findings': [], 'requests': [], 'redirects': [], 'limitations': [], 'pagespeed': {'status': 'not_requested'}}, None

@pytest.mark.anyio
async def test_audit_lifecycle_persistence_and_cooldown(database):
    manager = AuditManager(database, completed)
    created = await manager.start(payload())
    await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(created.id).status == 'complete'
    reopened = AuditManager(database, completed)
    assert reopened.read(created.id).report['requested_url'] == 'https://example.com/'
    with pytest.raises(HTTPException) as error: await manager.start(payload('http://www.example.com/another'))
    assert error.value.status_code == 429
    with Session(database) as session:
        record = session.get(Audit, created.id)
        record.created_at = now() - timedelta(minutes=2); record.next_allowed_at = now() - timedelta(seconds=1); session.commit()
    second = await manager.start(payload())
    await asyncio.gather(*list(manager.tasks.values()))
    assert second.id != created.id and manager.read(second.id).status == 'complete'

@pytest.mark.anyio
async def test_cancel_stops_active_worker_without_claiming_findings(database):
    started = asyncio.Event()
    finished = asyncio.Event()
    async def slow(*args, **kwargs):
        started.set()
        try: await asyncio.sleep(100)
        finally: finished.set()
    manager = AuditManager(database, slow)
    created = await manager.start(payload())
    await started.wait()
    cancelled = await manager.cancel(created.id)
    assert cancelled.status == 'cancelled' and cancelled.report is None and finished.is_set()
    assert not manager.tasks

@pytest.mark.anyio
async def test_recover_interrupted_runs_never_restarts_network(database):
    with Session(database) as session:
        record = Audit(requested_url='https://example.com/', hostname='example.com', status='running', pagespeed_requested=False, next_allowed_at=now())
        session.add(record); session.commit(); audit_id = record.id
    manager = AuditManager(database, completed)
    manager.recover()
    assert manager.read(audit_id).status == 'interrupted' and manager.tasks == {}

@pytest.mark.anyio
async def test_capacity_and_global_rate_limits(database):
    async def slow(*args, **kwargs): await asyncio.sleep(100)
    manager = AuditManager(database, slow)
    first = await manager.start(payload())
    with pytest.raises(HTTPException) as rate: await manager.start(payload('https://other.example.org/'))
    assert rate.value.status_code == 429
    with Session(database) as session:
        session.get(Audit, first.id).created_at = now() - timedelta(seconds=11); session.commit()
    second = await manager.start(payload('https://other.example.org/'))
    with pytest.raises(HTTPException) as capacity: await manager.start(payload('https://third.example.org/'))
    assert capacity.value.status_code == 429
    await manager.cancel(first.id); await manager.cancel(second.id)

@pytest.mark.anyio
async def test_pagespeed_budget_is_persisted_before_attempt(database, monkeypatch):
    monkeypatch.setattr('app.auditing.manager.PAGESPEED_ENABLED', True)
    monkeypatch.setattr('app.auditing.manager.PAGESPEED_DAILY_LIMIT', 1)
    attempted = []
    async def runner(url, use_pagespeed, progress, reserve, **kwargs):
        attempted.append(await reserve())
        attempted.append(await reserve())
        return 'partial', {'pagespeed': {'status': 'unavailable'}}, None
    manager = AuditManager(database, runner)
    created = await manager.start(payload(use_pagespeed=True))
    await asyncio.gather(*list(manager.tasks.values()))
    assert attempted == [True, False]
    with Session(database) as session: assert session.get(Audit, created.id).pagespeed_attempted_at is not None

@pytest.mark.anyio
async def test_retry_after_limits_longer_than_day_are_honored(database):
    async def limited(*args, **kwargs): return 'blocked', {'retry_after': '604800'}, AuditFailure('HTTP 429', 'access_restricted')
    manager = AuditManager(database, limited)
    created = await manager.start(payload())
    await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(created.id).next_allowed_at > now() + timedelta(days=6)

@pytest.mark.anyio
async def test_linked_lead_must_match_audit_and_history_survives_delete(database):
    with Session(database) as session:
        lead = Lead(business_name='Fixture', website_url='https://example.com/', normalized_key='example.com', source='manual', original_url='https://example.com/')
        session.add(lead); session.commit(); lead_id = lead.id
    manager = AuditManager(database, completed)
    with pytest.raises(HTTPException): await manager.start(payload('https://other.example.org/', lead_id=lead_id))
    created = await manager.start(payload(lead_id=lead_id))
    await asyncio.gather(*list(manager.tasks.values()))
    with Session(database) as session: session.delete(session.get(Lead, lead_id)); session.commit()
    assert manager.read(created.id).lead_id is None and manager.read(created.id).status == 'complete'


def test_api_history_validation_and_foreign_origin(client):
    assert client.get('/api/audits/config').json()['max_active'] == 2
    assert client.get('/api/audits').json()['total'] == 0
    assert client.get('/api/audits/9999').status_code == 404
    assert client.post('/api/audits/9999/cancel').status_code == 404
    assert client.post('/api/audits', json={'website_url': 'https://example.com/'}).status_code == 422
    assert client.post('/api/audits', json={'website_url': 'http://127.0.0.1', 'permission_confirmed': True}).status_code == 422
    assert client.post('/api/audits', json={'website_url': 'https://example.com/', 'permission_confirmed': True}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/audits?limit=101').status_code == 422

@pytest.mark.anyio
async def test_provider_retry_after_is_persisted_and_blocks_new_calls(database, monkeypatch):
    monkeypatch.setattr('app.auditing.manager.PAGESPEED_ENABLED', True)
    async def throttled(url, use_pagespeed, progress, reserve, **kwargs):
        assert await reserve()
        return 'partial', {'pagespeed': {'status': 'unavailable', 'retry_after': '7200', 'message': 'HTTP 429'}}, None
    manager = AuditManager(database, throttled)
    created = await manager.start(payload(use_pagespeed=True))
    await asyncio.gather(*list(manager.tasks.values()))
    assert manager.read(created.id).report['pagespeed']['cooldown_until']
    assert await manager.reserve_pagespeed(created.id) is False
