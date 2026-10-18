"""Durable worker regressions: isolated databases, fake clock, zero network."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func,text,update
from sqlalchemy.exc import OperationalError,IntegrityError
from sqlalchemy.orm import Session
from app.models.lead import now
from app.models.research import (ResearchJob,ResearchStep,ResearchAttempt,ResearchPlanRevision,
    ResearchWorkerLease,ResearchEvent,ResearchApproval)
from app.research.manager import ResearchManager,offline_step,MESSAGES
from app.schemas.research import JobCreate,JobControl

class Clock:
    def __init__(self):self.value=now()
    def __call__(self):return self.value
    def advance(self,seconds):self.value+=timedelta(seconds=seconds)

def payload(clock=now,**overrides):
    data={'request_id':str(uuid4()),'plan':{'category':'restaurants','geography':{'label':'London nearby sample','latitude':51.5074,'longitude':-.1278,'radius_metres':500},
        'lead_count':20,'expires_at':(clock()+timedelta(hours=24)).isoformat()}}
    data.update(overrides);return data

def create(manager,**kwargs):return manager.create(JobCreate.model_validate(payload(manager.clock,**kwargs)))
def control(manager,job,action):return manager.control(job['id'],JobControl(action=action,version=job['version']))

@pytest.mark.anyio
async def test_create_resume_complete_idempotency_events_and_zero_network(database,monkeypatch):
    import socket
    monkeypatch.setattr(socket,'create_connection',lambda *a,**k:pytest.fail('No sockets allowed'))
    m=ResearchManager(database);p=JobCreate.model_validate(payload())
    job=m.create(p);assert m.create(p)['id']==job['id'] and job['status']=='paused'
    changed=p.model_copy(update={'plan':p.plan.model_copy(update={'lead_count':2})})
    with pytest.raises(HTTPException) as error:m.create(changed)
    assert error.value.status_code==409
    m.acquire();job=control(m,job,'resume')
    await m.tick();await m.tick()
    result=m.read(job['id']);assert result['status']=='completed' and result['progress']=={'completed':2,'total':2,'businesses_researched':0}
    assert result['usage']['requests_used']==result['usage']['gemini_attempts_used']==0
    assert result['usage']['attempts_used']==2 and result['usage']['runtime_reserved_ms']==2000
    assert all(s['result_ref']['live_requests']==0 for s in result['steps'])
    await m.tick();assert m.read(job['id'])['usage']==result['usage']
    events=m.events(job['id'],2,0);assert len(events['items'])==2
    rest=m.events(job['id'],100,events['next_after']);assert all(e['id']>events['next_after'] for e in rest['items'])
    assert rest['items'][-1]['code']=='completed'
    assert all(e['message'] in MESSAGES.values() for e in rest['items'])
    await m.shutdown()

@pytest.mark.anyio
async def test_pause_active_preserves_result_and_resume_does_not_reset_usage(database):
    started=asyncio.Event();release=asyncio.Event()
    async def runner(kind,digest):started.set();await release.wait();return await offline_step(kind,digest)
    m=ResearchManager(database,runner=runner);job=control(m,create(m),'resume');task=asyncio.create_task(m.tick());await started.wait()
    current=m.read(job['id']);paused=control(m,current,'pause');release.set();await task
    result=m.read(job['id']);assert result['status']=='paused' and result['steps'][0]['status']=='succeeded'
    assert result['usage']['attempts_used']==1
    resumed=control(m,result,'resume');assert resumed['usage']==result['usage']
    await m.tick();assert m.read(job['id'])['status']=='completed'
    await m.shutdown()

@pytest.mark.anyio
async def test_cancel_active_does_not_commit_late_result(database):
    started=asyncio.Event();release=asyncio.Event()
    async def runner(kind,digest):started.set();await release.wait();return await offline_step(kind,digest)
    m=ResearchManager(database,runner=runner);job=control(m,create(m),'resume')
    task=asyncio.create_task(m.tick());await started.wait()
    assert control(m,m.read(job['id']),'cancel')['status']=='cancelling'
    release.set();await task
    result=m.read(job['id']);assert result['status']=='cancelled' and not result['steps'][0]['result_ref']
    await m.shutdown()

def test_stale_controls_terminal_invalid_transition_and_revision_immutability(database):
    m=ResearchManager(database);job=create(m)
    resumed=control(m,job,'resume')
    with pytest.raises(HTTPException) as error:control(m,job,'cancel')
    assert error.value.status_code==409
    cancelled=control(m,resumed,'cancel');assert cancelled['status']=='cancelled'
    with pytest.raises(HTTPException):control(m,cancelled,'resume')
    revised=create(m,based_on_job_id=job['id']);assert revised['plan_revision']==2 and revised['series_id']==job['series_id']
    with pytest.raises(HTTPException):create(m,based_on_job_id=job['id'])
    with Session(database) as s:
        plan=s.scalar(select(ResearchPlanRevision).where(ResearchPlanRevision.revision==1));plan.data={'tampered':True}
        with pytest.raises(IntegrityError):s.commit()
    assert m.read(job['id'])['plan']==job['plan']

@pytest.mark.anyio
@pytest.mark.parametrize('kind',['attempts','runtime'])
async def test_budget_exhaustion_cannot_be_reset_by_pause_resume(database,kind):
    m=ResearchManager(database);p=payload();p['plan']['budgets']={'max_attempts':0 if kind=='attempts' else 4,'max_runtime_seconds':1 if kind=='runtime' else 30}
    job=m.create(JobCreate.model_validate(p));job=control(m,job,'resume')
    await m.tick();await m.tick()
    result=m.read(job['id']);assert result['status']=='waiting_for_budget' and result['error_code']=='budget_exhausted'
    with pytest.raises(HTTPException):control(m,result,'resume')
    assert m.read(job['id'])['usage']==result['usage']
    await m.shutdown()

@pytest.mark.anyio
async def test_expiry_after_pause_and_before_result_commit(database):
    clock=Clock();m=ResearchManager(database,clock=clock);job=create(m)
    clock.advance(86401);assert control(m,job,'resume')['error_code']=='expired'
    async def runner(kind,digest):clock.advance(86401);return await offline_step(kind,digest)
    m.runner=runner;job=control(m,create(m),'resume');await m.tick()
    # The lease also expired: stale output cannot be committed. Recovery is explicit.
    assert not m.read(job['id'])['steps'][0]['result_ref']
    m.acquire();result=m.read(job['id']);assert result['status']=='interrupted'
    assert control(m,result,'resume')['error_code']=='expired'
    await m.shutdown()

@pytest.mark.anyio
async def test_retry_is_bounded_backoff_and_errors_are_static(database,caplog):
    clock=Clock()
    async def fail(*args):raise RuntimeError('PRIVATE_EXCEPTION personal@example.com API_KEY=TOPSECRET')
    m=ResearchManager(database,runner=fail,clock=clock);job=control(m,create(m),'resume')
    await m.tick();one=m.read(job['id']);assert one['status']=='waiting_for_retry'
    await m.tick();assert m.read(job['id'])['usage']['attempts_used']==1
    clock.advance(2);await m.tick();result=m.read(job['id']);assert result['status']=='failed' and result['usage']['attempts_used']==2
    assert 'PRIVATE_EXCEPTION' not in str(result)+str(m.events(job['id'],100,0))+caplog.text
    await m.shutdown()

@pytest.mark.anyio
async def test_single_owner_competition_claim_race_and_stale_fencing(database):
    clock=Clock();a=ResearchManager(database,clock=clock);b=ResearchManager(database,clock=clock)
    job=control(a,create(a),'resume')
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda m:m.acquire(),[a,b]))
    assert sum(results)==1
    owner=a if results[0] else b;other=b if results[0] else a
    with ThreadPoolExecutor(2) as pool:claims=list(pool.map(lambda _:owner.claim(),range(2)))
    assert sum(c is not None for c in claims)==1
    first=next(c for c in claims if c)
    assert other.claim() is None
    clock.advance(16);assert other.acquire()
    assert not owner.finish(first,result=await offline_step(first['kind'],first['hash']))
    recovered=other.read(job['id']);assert recovered['status']=='interrupted' and recovered['usage']['attempts_used']==1
    control(other,recovered,'resume');await other.tick();await other.tick()
    result=other.read(job['id']);assert result['status']=='completed' and result['usage']['attempts_used']==3
    assert len({s['idempotency_key'] for s in result['steps']})==2
    await a.shutdown();await b.shutdown()

@pytest.mark.anyio
async def test_restart_preserves_completed_results_and_never_replays_unsafe_dispatch(database):
    clock=Clock();first=ResearchManager(database,clock=clock);job=control(first,create(first),'resume')
    await first.tick();claim=first.claim();assert claim
    with Session(database) as s:
        attempt=s.get(ResearchAttempt,claim['attempt_id']);step=s.get(ResearchStep,attempt.step_id);step.replay_safe=False;s.commit()
    clock.advance(16);second=ResearchManager(database,clock=clock);assert second.acquire()
    result=second.read(job['id']);assert result['status']=='waiting_for_approval'
    assert result['steps'][0]['result_ref'] and result['steps'][1]['status']=='uncertain'
    assert len(result['approvals'])==1 and result['attempts'][-1]['dispatch_state']=='uncertain'
    with pytest.raises(HTTPException):control(second,result,'resume')
    await second.tick();assert second.read(job['id'])['usage']==result['usage']
    assert control(second,result,'cancel')['status']=='cancelled'
    await second.shutdown()

@pytest.mark.anyio
async def test_persistence_failure_halts_worker_and_blocks_new_actions(database,monkeypatch):
    m=ResearchManager(database);job=control(m,create(m),'resume');calls=[]
    async def runner(*args):calls.append(True);return await offline_step(*args)
    m.runner=runner
    from contextlib import contextmanager
    @contextmanager
    def broken():raise OperationalError('PRIVATE_SQL',{},Exception('PRIVATE_DETAIL'));yield
    monkeypatch.setattr(m,'write',broken)
    await m.tick();assert not m.healthy and calls==[]
    with pytest.raises(HTTPException) as error:m.create(JobCreate.model_validate(payload()))
    assert error.value.status_code==503 and 'PRIVATE' not in str(error.value)
    assert m.read(job['id'])['usage']['attempts_used']==0

@pytest.mark.anyio
async def test_shutdown_interrupts_local_attempt_preserves_budget_and_releases_lease(database):
    started=asyncio.Event()
    async def runner(*args):started.set();await asyncio.Event().wait()
    m=ResearchManager(database,runner=runner,poll_seconds=.01);job=control(m,create(m),'resume');m.start();await started.wait();await m.shutdown()
    result=m.read(job['id']);assert result['status']=='interrupted' and result['usage']['attempts_used']==1
    second=ResearchManager(database);assert second.acquire()
    await second.shutdown()

@pytest.mark.parametrize('patch',[
    {'scopes':{'gemini':True}},{'scopes':{'website_access':1}},{'budgets':{'max_requests':1}},
    {'lead_count':True},{'category':'API_KEY=SECRET'},{'category':'personal@example.com'},
    {'geography':{'label':'London','latitude':91,'longitude':0}},{'expires_at':'2026-10-18T12:00:00'},
])
def test_api_validation_never_echoes_rejected_data(client,patch):
    p=payload();p['plan'].update(patch);response=client.post('/api/research/jobs',json=p)
    assert response.status_code==422 and 'SECRET' not in response.text and 'personal@example.com' not in response.text

def test_api_lists_controls_events_origin_and_idempotent_create(client):
    p=payload();path='/api/research/jobs';response=client.post(path,json=p);assert response.status_code==201
    job=response.json();assert client.post(path,json=p).json()['id']==job['id']
    assert client.get(path).json()['total']==1 and client.get(path+'?limit=0').status_code==422
    assert client.get(path+f'/{job["id"]}').json()['status']=='paused'
    assert client.get(path+f'/{job["id"]}/events').json()['items'][0]['code']=='created'
    assert client.get('/api/research/status').json()['external_dispatch_enabled'] is False
    assert client.post(path,json=payload(),headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post(path+f'/{job["id"]}/control',json={'action':'cancel','version':999}).status_code==409
    assert client.post(path+f'/{job["id"]}/control',json={'action':'cancel','version':job['version']}).json()['status']=='cancelled'
    assert client.get(path+'/9999').status_code==404
    assert client.get(path).headers['cache-control']=='no-store'

@pytest.mark.anyio
async def test_failed_event_persistence_rolls_back_claim_and_halts_before_dispatch(database):
    from sqlalchemy import event as sa_event
    m=ResearchManager(database);job=control(m,create(m),'resume');m.acquire();calls=[]
    async def runner(*args):calls.append(True);return await offline_step(*args)
    m.runner=runner
    def reject_event(connection,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO research_events'):raise OperationalError('PRIVATE_SQL',{},Exception('PRIVATE_CONTACT'))
    sa_event.listen(database,'before_cursor_execute',reject_event)
    try:await m.tick()
    finally:sa_event.remove(database,'before_cursor_execute',reject_event)
    assert not m.healthy and calls==[]
    result=m.read(job['id']);assert result['status']=='queued' and result['usage']['attempts_used']==0 and result['attempts']==[]
    with pytest.raises(HTTPException):m.status()

@pytest.mark.anyio
async def test_bad_runner_result_is_not_persisted_or_logged(database,caplog):
    async def runner(*args):return {'kind':'PRIVATE_SENTINEL','raw_html':'<html>secret@example.com</html>'}
    m=ResearchManager(database,runner=runner);job=control(m,create(m),'resume');await m.tick()
    result=m.read(job['id']);assert result['status']=='waiting_for_retry' and not result['steps'][0]['result_ref']
    assert 'PRIVATE_SENTINEL' not in str(result)+str(m.events(job['id'],100,0))+caplog.text
    await m.shutdown()

@pytest.mark.anyio
async def test_retry_backoff_cannot_be_bypassed_by_pause_resume(database):
    clock=Clock()
    async def runner(*args):raise RuntimeError('failure')
    m=ResearchManager(database,clock=clock,runner=runner);job=control(m,create(m),'resume');await m.tick()
    job=control(m,m.read(job['id']),'pause');job=control(m,job,'resume');await m.tick()
    assert m.read(job['id'])['usage']['attempts_used']==1
    clock.advance(2);await m.tick();assert m.read(job['id'])['usage']['attempts_used']==2
    await m.shutdown()

def test_claim_serializes_across_different_jobs_and_unsupported_action_is_blocked(database):
    m=ResearchManager(database);first=control(m,create(m),'resume');second=control(m,create(m),'resume');m.acquire()
    with ThreadPoolExecutor(2) as pool:claims=list(pool.map(lambda _:m.claim(),range(2)))
    assert sum(c is not None for c in claims)==1
    with Session(database) as s:
        step=s.scalar(select(ResearchStep).where(ResearchStep.job_id==second['id']).order_by(ResearchStep.position));step.kind='external_reserved';step.replay_safe=False
        active=s.scalar(select(ResearchStep).where(ResearchStep.status=='running'));active.status='succeeded';s.commit()
    # Remaining step of the first task may be claimed before the second task.
    claim=m.claim()
    if claim:
        with Session(database) as s:
            step=s.get(ResearchStep,s.get(ResearchAttempt,claim['attempt_id']).step_id);step.status='succeeded';s.commit()
    m.claim()
    assert m.read(second['id'])['status']=='waiting_for_approval'
    assert m.read(second['id'])['usage']['attempts_used']==0

def test_concurrent_create_is_idempotent_and_controls_use_compare_and_swap(database):
    m=ResearchManager(database);p=JobCreate.model_validate(payload())
    with ThreadPoolExecutor(2) as pool:created=list(pool.map(lambda _:m.create(p),range(2)))
    assert created[0]['id']==created[1]['id']
    job=control(m,created[0],'resume')
    def action(name):
        try:return control(m,job,name)['status']
        except HTTPException as e:return e.status_code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(action,['pause','cancel']))
    assert results.count(409)==1
    assert len(m.events(job['id'],100,0)['items'])==3

@pytest.mark.anyio
async def test_timeout_consumes_runtime_slot_and_cannot_restart_without_budget(database):
    async def runner(*args):await asyncio.Event().wait()
    clock=Clock();m=ResearchManager(database,clock=clock,runner=runner)
    p=payload(clock);p['plan']['budgets']={'max_runtime_seconds':1}
    job=control(m,m.create(JobCreate.model_validate(p)),'resume');await m.tick()
    assert m.read(job['id'])['status']=='waiting_for_retry'
    clock.advance(2);await m.tick();result=m.read(job['id'])
    assert result['status']=='waiting_for_budget' and result['usage']['runtime_reserved_ms']==1000
    await m.shutdown()

@pytest.mark.anyio
async def test_restart_after_cancellation_finishes_pending_steps_without_replaying(database):
    clock=Clock();m=ResearchManager(database,clock=clock);job=control(m,create(m),'resume');m.acquire();m.claim()
    control(m,m.read(job['id']),'cancel');clock.advance(16)
    recovered=ResearchManager(database,clock=clock);recovered.acquire();result=recovered.read(job['id'])
    assert result['status']=='cancelled'
    assert all(step['status']=='cancelled' for step in result['steps'])
    assert result['usage']['attempts_used']==1
    await recovered.shutdown()

@pytest.mark.anyio
async def test_heartbeat_renews_lease_and_cancellation_stops_active_local_step(database):
    started=asyncio.Event();stopped=asyncio.Event()
    async def runner(*args):
        started.set()
        try:await asyncio.Event().wait()
        finally:stopped.set()
    m=ResearchManager(database,runner=runner,poll_seconds=.01,lease_seconds=.15)
    job=control(m,create(m),'resume');m.start();await asyncio.wait_for(started.wait(),1)
    # A different owner cannot recover/cancel this live worker's attempt.
    other=ResearchManager(database);assert not other.acquire()
    control(m,m.read(job['id']),'cancel')
    await asyncio.wait_for(stopped.wait(),1)
    for _ in range(20):
        if m.read(job['id'])['status']=='cancelled':break
        await asyncio.sleep(.01)
    assert m.read(job['id'])['status']=='cancelled'
    await m.shutdown()

def test_research_bounds_and_missing_schema_are_safe(client,tmp_path):
    from app.main import app
    from app.database.session import make_engine
    assert client.get('/api/research/jobs/999999999999999999999999').status_code==422
    assert client.get('/api/research/jobs/-1').status_code==422
    assert client.get('/api/research/jobs?offset=999999999999999999999999').status_code==422
    empty=make_engine(tmp_path/'empty-research.db');m=ResearchManager(empty);m.start()
    original=app.state.research_manager;app.state.research_manager=m
    try:
        response=client.get('/api/research/status')
        assert response.status_code==503 and 'restart' in response.json()['detail']
        response=client.post('/api/research/jobs',json=payload())
        assert response.status_code==503 and 'SQL' not in response.text
    finally:app.state.research_manager=original;empty.dispose()

@pytest.mark.anyio
@pytest.mark.parametrize('completed_steps',[0,1])
async def test_cancel_intent_survives_simultaneous_graceful_shutdown(database,completed_steps):
    started=asyncio.Event()
    async def blocked(*args):started.set();await asyncio.Event().wait()
    m=ResearchManager(database,poll_seconds=.01)
    job=control(m,create(m),'resume')
    if completed_steps:await m.tick()
    m.runner=blocked;m.start();await asyncio.wait_for(started.wait(),1)
    cancellation=control(m,m.read(job['id']),'cancel')
    assert cancellation['status']=='cancelling'
    await m.shutdown()
    result=m.read(job['id'])
    assert result['status']=='cancelled'
    assert result['progress']['completed']==completed_steps
    assert result['attempts'][-1]['status']=='cancelled'
    assert all(s['status'] in {'succeeded','cancelled'} for s in result['steps'])
    recovered=ResearchManager(database);assert recovered.acquire()
    assert recovered.read(job['id'])['status']=='cancelled'
    with pytest.raises(HTTPException):control(recovered,result,'resume')
    await recovered.shutdown()
