from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base
from app.models.lead import now


class DiscoverySearch(Base):
    __tablename__ = 'discovery_searches'
    __table_args__ = (CheckConstraint("status IN ('queued','running','complete','error','cancelled','interrupted')", name='discovery_status'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    progress: Mapped[str] = mapped_column(String(200), default='Queued')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class DiscoveryCache(Base):
    __tablename__ = 'discovery_cache'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscoveredBusiness(Base):
    """Separate ODbL layer. No invented website or private lead notes copied here."""
    __tablename__ = 'discovered_businesses'
    __table_args__ = (UniqueConstraint('provider', 'source_id', name='uq_business_source'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
