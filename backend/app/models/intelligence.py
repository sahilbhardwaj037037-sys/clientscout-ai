from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base
from app.models.lead import now

class BusinessIdentity(Base):
    __tablename__='business_identities'
    __table_args__=(CheckConstraint('(lead_id IS NOT NULL AND discovered_business_id IS NULL) OR (lead_id IS NULL AND discovered_business_id IS NOT NULL)',name='identity_target'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int|None]=mapped_column(ForeignKey('leads.id',ondelete='CASCADE'),unique=True,nullable=True)
    discovered_business_id: Mapped[int|None]=mapped_column(ForeignKey('discovered_businesses.id',ondelete='CASCADE'),unique=True,nullable=True)
    snapshot: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Enrichment(Base):
    __tablename__='enrichments'
    __table_args__=(CheckConstraint("status IN ('queued','running','complete','partial','blocked','error','cancelled','interrupted')",name='enrichment_status'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    identity_id: Mapped[int]=mapped_column(ForeignKey('business_identities.id',ondelete='CASCADE'),index=True)
    requested_url: Mapped[str|None]=mapped_column(String(2048),nullable=True)
    hostname: Mapped[str|None]=mapped_column(String(300),nullable=True,index=True)
    official_confirmed: Mapped[bool]=mapped_column(Boolean,default=False)
    directory_requested: Mapped[bool]=mapped_column(Boolean,default=False)
    status: Mapped[str]=mapped_column(String(20),default='queued')
    progress: Mapped[str]=mapped_column(String(200),default='Queued')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,index=True)
    finished_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    next_allowed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    report: Mapped[dict|None]=mapped_column(JSON,nullable=True)
    error: Mapped[str|None]=mapped_column(String(1000),nullable=True)

class ContactMethod(Base):
    __tablename__='contact_methods'
    __table_args__=(UniqueConstraint('enrichment_id','kind','value',name='unique_contact_observation'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    enrichment_id: Mapped[int]=mapped_column(ForeignKey('enrichments.id',ondelete='CASCADE'),index=True)
    kind: Mapped[str]=mapped_column(String(30))
    value: Mapped[str]=mapped_column(String(2048),default='')
    status: Mapped[str]=mapped_column(String(40))
    provenance: Mapped[dict]=mapped_column(JSON)

class Assessment(Base):
    __tablename__='opportunity_assessments'
    id: Mapped[int]=mapped_column(primary_key=True)
    identity_id: Mapped[int]=mapped_column(ForeignKey('business_identities.id',ondelete='CASCADE'),index=True)
    enrichment_id: Mapped[int|None]=mapped_column(ForeignKey('enrichments.id',ondelete='SET NULL'),nullable=True)
    audit_id: Mapped[int|None]=mapped_column(ForeignKey('audits.id',ondelete='SET NULL'),nullable=True)
    score: Mapped[int|None]=mapped_column(Integer,nullable=True)
    confidence: Mapped[int]=mapped_column(Integer)
    segment: Mapped[str]=mapped_column(String(50),index=True)
    qualification: Mapped[str]=mapped_column(String(30))
    website_status: Mapped[str]=mapped_column(String(70))
    report: Mapped[dict]=mapped_column(JSON)
    ai_context: Mapped[dict|None]=mapped_column(JSON,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class OutreachDraft(Base):
    __tablename__='outreach_drafts'
    id: Mapped[int]=mapped_column(primary_key=True)
    identity_id: Mapped[int]=mapped_column(ForeignKey('business_identities.id',ondelete='CASCADE'),index=True)
    assessment_id: Mapped[int|None]=mapped_column(ForeignKey('opportunity_assessments.id',ondelete='SET NULL'),nullable=True)
    channel: Mapped[str]=mapped_column(String(30))
    generator: Mapped[str]=mapped_column(String(30))
    subject: Mapped[str]=mapped_column(String(200),default='')
    body: Mapped[str]=mapped_column(Text)
    evidence: Mapped[dict]=mapped_column(JSON)
    saved: Mapped[bool]=mapped_column(Boolean,default=False)
    edited: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)

class AIUsage(Base):
    __tablename__='ai_usage'
    id: Mapped[int]=mapped_column(primary_key=True)
    request: Mapped[dict|None]=mapped_column(JSON,nullable=True)
    result: Mapped[dict|None]=mapped_column(JSON,nullable=True)
    purpose: Mapped[str]=mapped_column(String(30))
    model: Mapped[str]=mapped_column(String(100))
    status: Mapped[str]=mapped_column(String(30),default='reserved')
    input_tokens: Mapped[int|None]=mapped_column(Integer,nullable=True)
    output_tokens: Mapped[int|None]=mapped_column(Integer,nullable=True)
    cooldown_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,index=True)
