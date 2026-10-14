from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.services.urls import normalize_url


class AuditCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    website_url: str = Field(min_length=1, max_length=2048)
    lead_id: int | None = Field(default=None, gt=0)
    use_pagespeed: bool = False
    permission_confirmed: Literal[True]

    @field_validator('website_url')
    @classmethod
    def valid_url(cls, value):
        normalize_url(value)
        return value


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: int | None
    requested_url: str
    status: Literal['queued', 'running', 'complete', 'partial', 'error', 'blocked', 'cancelled', 'interrupted']
    progress: str
    pagespeed_requested: bool
    created_at: datetime
    finished_at: datetime | None
    next_allowed_at: datetime
    error_code: str | None
    error: str | None
    report: dict | None

    @field_validator('created_at', 'finished_at', 'next_allowed_at')
    @classmethod
    def utc_timestamp(cls, value):
        return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value
