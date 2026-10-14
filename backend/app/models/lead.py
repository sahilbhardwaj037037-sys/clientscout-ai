from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


def now():
    return datetime.now(timezone.utc)


class Lead(Base):
    __tablename__ = 'leads'
    __table_args__ = (
        CheckConstraint("status IN ('new', 'shortlisted', 'contacted', 'won', 'archived')", name='lead_status'),
        CheckConstraint("source IN ('manual', 'csv')", name='lead_source'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_name: Mapped[str] = mapped_column(String(200))
    website_url: Mapped[str] = mapped_column(String(2048))
    normalized_key: Mapped[str] = mapped_column(String(300), unique=True)
    category: Mapped[str] = mapped_column(String(100), default='')
    location: Mapped[str] = mapped_column(String(200), default='')
    status: Mapped[str] = mapped_column(String(20), default='new')
    notes: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(String(20))
    source_filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    original_url: Mapped[str] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
