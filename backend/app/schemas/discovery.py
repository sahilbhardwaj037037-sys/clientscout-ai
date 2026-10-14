from app.providers.locations import parse_location
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    location: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=80)
    limit: int = Field(default=10, ge=1, le=50, strict=True)
    provider: Literal['osm_overpass'] = 'osm_overpass'
    website_filter: Literal['any', 'with', 'without'] = 'any'
    radius_metres: Literal[500, 1000, 2000] = 2000
    search_scope: Literal['auto', 'nearby', 'boundary'] = 'auto'

    @field_validator('location', 'category')
    @classmethod
    def public_text(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value) or '://' in value or len(value.strip()) < 2:
            raise ValueError('Use a public place name/coordinates and a category or business-name keyword, not a URL or control characters.')
        return value

    @field_validator('location')
    @classmethod
    def coordinates(cls, value):
        parse_location(value)
        return value


class SaveSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_ids: list[Annotated[str, Field(max_length=80, pattern=r'^(node|way|relation)/[1-9][0-9]*$')]] = Field(min_length=1, max_length=50)
    licence_confirmed: Literal[True]

from datetime import datetime, timezone


class SearchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    query: dict
    status: Literal['queued', 'running', 'complete', 'error', 'cancelled', 'interrupted']
    progress: str
    created_at: datetime
    finished_at: datetime | None
    cooldown_until: datetime
    result: dict | None
    error: str | None
    diagnostics: list[dict] = Field(default_factory=list)

    @field_validator('diagnostics', mode='before')
    @classmethod
    def legacy_diagnostics(cls,value): return value or []

    @field_validator('created_at', 'finished_at', 'cooldown_until')
    @classmethod
    def utc_timestamp(cls, value):
        return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value
