from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel,ConfigDict,Field,field_validator
from app.services.urls import normalize_url

class Target(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target_type: Literal['lead','discovery']
    target_id: int=Field(gt=0,strict=True)

class EnrichCreate(Target):
    permission_confirmed: Literal[True]
    official_confirmed: bool=False
    website_url: str|None=Field(default=None,max_length=2048)
    use_directory: bool=False
    refresh: bool=False
    @field_validator('website_url')
    @classmethod
    def safe_url(cls,value):
        if value is None:return value
        value,_=normalize_url(value)
        if urlsplit(value).query:raise ValueError('Use a public website URL without query parameters for enrichment.')
        return value

class AIRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    public_data_consent: Literal[True]

class DraftCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    assessment_id: int=Field(gt=0,strict=True)
    channel: Literal['email','whatsapp','contact_form','linkedin_dm','instagram_dm']='email'
    generator: Literal['template','gemini']='template'
    review_confirmed: Literal[True]
    public_data_consent: bool=False

class DraftEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    subject: str=Field(max_length=200)
    body: str=Field(min_length=1,max_length=6000)
    saved: bool=True

class AISelection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    opening: Literal['direct','brief','courteous']
    finding_ids: list[str]=Field(max_length=3)
    service_ids: list[Literal['wordpress','shopify','frontend','react','python']]=Field(min_length=1,max_length=3)
    closing: Literal['outline','chat','permission']
