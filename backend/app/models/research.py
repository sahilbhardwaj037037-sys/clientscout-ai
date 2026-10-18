"""Durable foundation tables; existing application records are never rewritten."""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base
from app.models.lead import now

JOB_STATES=('queued','running','waiting_for_approval','waiting_for_budget','waiting_for_retry','paused','cancelling','cancelled','interrupted','failed','completed')
STEP_STATES=('pending','running','succeeded','cancelled','interrupted','failed','uncertain')
def in_states(column,values): return column+' IN ('+','.join(repr(v) for v in values)+')'

class ResearchPlanRevision(Base):
    __tablename__='research_plans'
    __table_args__=(UniqueConstraint('series_id','revision'),CheckConstraint('revision >= 1'))
    id: Mapped[int]=mapped_column(primary_key=True)
    series_id: Mapped[str]=mapped_column(String(36))
    revision: Mapped[int]=mapped_column(Integer)
    previous_id: Mapped[int|None]=mapped_column(ForeignKey('research_plans.id'),nullable=True)
    fingerprint: Mapped[str]=mapped_column(String(64))
    data: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ResearchJob(Base):
    __tablename__='research_jobs'
    __table_args__=(CheckConstraint(in_states('status',JOB_STATES)),CheckConstraint('attempts_used >= 0 AND runtime_reserved_ms >= 0 AND requests_used = 0 AND gemini_attempts_used = 0'))
    id: Mapped[int]=mapped_column(primary_key=True)
    request_id: Mapped[str]=mapped_column(String(36),unique=True)
    request_hash: Mapped[str]=mapped_column(String(64))
    plan_id: Mapped[int]=mapped_column(ForeignKey('research_plans.id'),unique=True)
    status: Mapped[str]=mapped_column(String(30),default='paused',index=True)
    version: Mapped[int]=mapped_column(Integer,default=1)
    attempts_used: Mapped[int]=mapped_column(Integer,default=0)
    runtime_reserved_ms: Mapped[int]=mapped_column(Integer,default=0)
    requests_used: Mapped[int]=mapped_column(Integer,default=0)
    gemini_attempts_used: Mapped[int]=mapped_column(Integer,default=0)
    error_code: Mapped[str|None]=mapped_column(String(40),nullable=True)
    next_retry_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ResearchStep(Base):
    __tablename__='research_steps'
    __table_args__=(UniqueConstraint('job_id','position'),CheckConstraint(in_states('status',STEP_STATES)),CheckConstraint("kind IN ('validate_plan','summarize_plan','external_reserved')"))
    id: Mapped[int]=mapped_column(primary_key=True)
    job_id: Mapped[int]=mapped_column(ForeignKey('research_jobs.id'),index=True)
    position: Mapped[int]=mapped_column(Integer)
    kind: Mapped[str]=mapped_column(String(30))
    idempotency_key: Mapped[str]=mapped_column(String(64),unique=True)
    status: Mapped[str]=mapped_column(String(20),default='pending')
    replay_safe: Mapped[bool]=mapped_column(Boolean,default=True)
    result_ref: Mapped[dict|None]=mapped_column(JSON,nullable=True)

class ResearchAttempt(Base):
    __tablename__='research_attempts'
    __table_args__=(UniqueConstraint('step_id','number'),CheckConstraint("status IN ('started','succeeded','failed','cancelled','interrupted','uncertain')"),CheckConstraint("dispatch_state IN ('reserved','started','finished','uncertain')"))
    id: Mapped[int]=mapped_column(primary_key=True)
    step_id: Mapped[int]=mapped_column(ForeignKey('research_steps.id'),index=True)
    number: Mapped[int]=mapped_column(Integer)
    owner: Mapped[str]=mapped_column(String(36))
    epoch: Mapped[int]=mapped_column(Integer)
    status: Mapped[str]=mapped_column(String(20),default='started')
    dispatch_state: Mapped[str]=mapped_column(String(20),default='reserved')
    reserved_ms: Mapped[int]=mapped_column(Integer)
    error_code: Mapped[str|None]=mapped_column(String(40),nullable=True)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    finished_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)

class ResearchApproval(Base):
    """Reconciliation reference only; no permission-granting endpoint in 5.1."""
    __tablename__='research_approvals'
    id: Mapped[int]=mapped_column(primary_key=True)
    job_id: Mapped[int]=mapped_column(ForeignKey('research_jobs.id'),index=True)
    step_id: Mapped[int]=mapped_column(ForeignKey('research_steps.id'),unique=True)
    attempt_id: Mapped[int|None]=mapped_column(ForeignKey('research_attempts.id'),nullable=True)
    reason: Mapped[str]=mapped_column(String(40))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ResearchEvent(Base):
    __tablename__='research_events'
    id: Mapped[int]=mapped_column(primary_key=True)
    job_id: Mapped[int]=mapped_column(ForeignKey('research_jobs.id'),index=True)
    code: Mapped[str]=mapped_column(String(40))
    step_id: Mapped[int|None]=mapped_column(ForeignKey('research_steps.id'),nullable=True)
    attempt_id: Mapped[int|None]=mapped_column(ForeignKey('research_attempts.id'),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ResearchWorkerLease(Base):
    __tablename__='research_worker_lease'
    __table_args__=(CheckConstraint('id = 1'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    owner: Mapped[str|None]=mapped_column(String(36),nullable=True)
    epoch: Mapped[int]=mapped_column(Integer,default=0)
    expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
