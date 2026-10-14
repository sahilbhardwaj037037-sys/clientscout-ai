from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base
from app.models.lead import now


class Audit(Base):
    __tablename__ = 'audits'
    __table_args__ = (CheckConstraint("status IN ('queued','running','complete','partial','error','blocked','cancelled','interrupted')", name='audit_status'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey('leads.id', ondelete='SET NULL'), nullable=True)
    requested_url: Mapped[str] = mapped_column(String(2048))
    hostname: Mapped[str] = mapped_column(String(300), index=True)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    progress: Mapped[str] = mapped_column(String(200), default='Queued')
    pagespeed_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    pagespeed_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_allowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
