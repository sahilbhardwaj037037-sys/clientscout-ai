from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.services.urls import normalize_url

LeadStatus = Literal['new', 'shortlisted', 'contacted', 'won', 'archived']


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    website_url: str = Field(min_length=1, max_length=2048)
    business_name: str = Field(default='', max_length=200)
    category: str = Field(default='', max_length=100)
    location: str = Field(default='', max_length=200)
    status: LeadStatus = 'new'
    notes: str = Field(default='', max_length=10000)

    @field_validator('website_url')
    @classmethod
    def valid_url(cls, value):
        normalize_url(value)
        return value


class LeadPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    website_url: str | None = Field(default=None, min_length=1, max_length=2048)
    business_name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    status: LeadStatus | None = None
    notes: str | None = Field(default=None, max_length=10000)

    @model_validator(mode='after')
    def no_null_fields(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError('Provide at least one field; null values are not allowed.')
        if self.website_url is not None:
            normalize_url(self.website_url)
        return self


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    business_name: str
    website_url: str
    category: str
    location: str
    status: LeadStatus
    notes: str
    source: Literal['manual', 'csv']
    source_filename: str | None
    original_url: str
    created_at: datetime
    updated_at: datetime

    @field_validator('created_at', 'updated_at')
    @classmethod
    def utc_timestamp(cls, value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
