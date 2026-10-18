"""Offline-only research contracts. No implicit authorization or free-form commands."""
import re
from datetime import datetime
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from app.schemas.intelligence import public_text

JobState = Literal['queued','running','waiting_for_approval','waiting_for_budget','waiting_for_retry','paused','cancelling','cancelled','interrupted','failed','completed']
StepState = Literal['pending','running','succeeded','cancelled','interrupted','failed','uncertain']

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Geography(StrictModel):
    label: str = Field(min_length=2,max_length=120,strict=True)
    latitude: float = Field(ge=-90,le=90,strict=True)
    longitude: float = Field(ge=-180,le=180,strict=True)
    radius_metres: Literal[500,1000,2000] = 500
    @field_validator('label')
    @classmethod
    def safe_label(cls,value): return safe_text(value)
    @field_validator('radius_metres',mode='before')
    @classmethod
    def exact_radius(cls,value):
        if type(value) is not int: raise ValueError('Use an integer radius.')
        return value

def safe_text(value):
    from app.core import settings
    value=public_text(value)
    if not value or re.search(r'[<>\[\]`]|\bsk-[\w-]{12,}',value,re.I): raise ValueError('Use public descriptive text.')
    if any(secret and secret in value for secret in (settings.GEMINI_API_KEY,settings.PAGESPEED_API_KEY)): raise ValueError('Protected information is not allowed.')
    return value

class Scopes(StrictModel):
    discovery: Literal[False] = False
    website_access: Literal[False] = False
    gemini: Literal[False] = False
    profile_sharing: Literal[False] = False
    @field_validator('*',mode='before')
    @classmethod
    def disabled(cls,value):
        if value is not False: raise ValueError('External scopes are disabled in this foundation.')
        return value

class Budgets(StrictModel):
    max_attempts: int = Field(default=4,ge=0,le=10,strict=True)
    max_runtime_seconds: int = Field(default=30,ge=1,le=600,strict=True)
    max_requests: Literal[0] = 0
    max_gemini_attempts: Literal[0] = 0
    @field_validator('max_requests','max_gemini_attempts',mode='before')
    @classmethod
    def zero_only(cls,value):
        if type(value) is not int or value!=0: raise ValueError('No external requests are permitted.')
        return value

class ResearchPlan(StrictModel):
    category: str = Field(min_length=2,max_length=80,strict=True)
    geography: Geography
    lead_count: int = Field(default=20,ge=1,le=50,strict=True)
    scopes: Scopes = Field(default_factory=Scopes)
    budgets: Budgets = Field(default_factory=Budgets)
    expires_at: AwareDatetime
    _category=field_validator('category')(safe_text)

class JobCreate(StrictModel):
    request_id: str = Field(pattern=r'^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$',strict=True)
    plan: ResearchPlan
    based_on_job_id: int|None = Field(default=None,gt=0,le=9007199254740991,strict=True)

class JobControl(StrictModel):
    action: Literal['pause','resume','cancel']
    version: int = Field(ge=1,le=9007199254740991,strict=True)

class OfflineResult(StrictModel):
    kind: Literal['plan_validated','foundation_summary']
    plan_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    live_requests: Literal[0] = 0
    businesses_researched: Literal[0] = 0
