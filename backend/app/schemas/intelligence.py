from typing import Literal
from urllib.parse import urlsplit,unquote
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
    include_profile: bool=False

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

ServiceID = Literal['wordpress','shopify','frontend','react','python']

def public_text(value):
    import re
    if re.search(r'@|https?://|\b(?:api[_ -]?key|secret|password|token)(?:\b|_)|AIza[\w-]+|\+?\d[\d ()-]{7,}\d',value,re.I):
        raise ValueError('Use public descriptive text without contacts, links or secrets.')
    if any(ord(c)<32 for c in value):raise ValueError('Use single-line public text.')
    return value.strip()

def profile_url(value):
    import re
    if not value:return ''
    normalized,_=normalize_url(value)
    parts=urlsplit(normalized)
    if parts.scheme!='https' or parts.query or urlsplit(value).fragment:
        raise ValueError('Use a public HTTPS link without credentials, query parameters or fragments.')
    path=unquote(parts.path)
    if '@' in path or re.search(r'AIza[\w-]+|(?:^|[/_-])(?:api[_-]?key|token|password|secret)(?:$|[/_-])',path,re.I):
        raise ValueError('Public profile links must not contain contacts or secrets.')
    return normalized

class PortfolioProject(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str=Field(pattern=r'^[a-z0-9-]{1,40}$')
    title: str=Field(min_length=1,max_length=100)
    url: str=Field(default='',max_length=2048)
    kind: Literal['completed_project','existing_demo']='completed_project'
    service_ids: list[ServiceID]=Field(min_length=1,max_length=5)
    _title=field_validator('title')(public_text)
    _url=field_validator('url')(profile_url)
    @field_validator('title')
    @classmethod
    def nonempty(cls,value):
        if not value:raise ValueError('A project needs a public title.')
        return value

class FreelancerProfile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    display_name: str=Field(default='',max_length=80)
    service_ids: list[ServiceID]=Field(default_factory=list,max_length=5)
    portfolio_url: str=Field(default='',max_length=2048)
    instagram_url: str=Field(default='',max_length=2048)
    projects: list[PortfolioProject]=Field(default_factory=list,max_length=5)
    public_details_confirmed: bool=False
    allow_walkthrough_offer: bool=False
    _name=field_validator('display_name')(public_text)
    _portfolio=field_validator('portfolio_url')(profile_url)
    @field_validator('instagram_url')
    @classmethod
    def instagram(cls,value):
        import re
        value=profile_url(value)
        if value and (urlsplit(value).hostname not in {'instagram.com','www.instagram.com'} or not re.fullmatch(r'/[A-Za-z0-9._]+/?',urlsplit(value).path)):
            raise ValueError('Use your public professional Instagram profile URL.')
        return value

class AIClaim(BaseModel):
    model_config=ConfigDict(extra='forbid')
    fact_id: str=Field(min_length=1,max_length=100)
    text: str=Field(min_length=1,max_length=500)

class AIWrittenDraft(BaseModel):
    model_config=ConfigDict(extra='forbid',revalidate_instances='always')
    subject: str=Field(max_length=200)
    body: str=Field(min_length=1,max_length=1800)
    finding_ids: list[str]=Field(max_length=3)
    service_ids: list[ServiceID]=Field(min_length=1,max_length=3)
    project_ids: list[str]=Field(max_length=3)
    used_links: list[str]=Field(max_length=5,description='Unique approved URLs actually present in subject or body, not all available profile links. Use [] when no links appear. At most five; copy exact approved URLs.')
    claims: list[AIClaim]=Field(min_length=2,max_length=12)
    offers_walkthrough: bool

class HumanWrittenDraft(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,revalidate_instances='always')
    subject: str=Field(max_length=200)
    body: str=Field(min_length=1,max_length=1800)

class DraftReview(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    acknowledged: Literal[True]
    content_hash: str=Field(pattern=r'^[a-f0-9]{64}$')
    @field_validator('acknowledged',mode='before')
    @classmethod
    def explicit_acknowledgement(cls,value):
        if value is not True:raise ValueError('Explicit review acknowledgement is required.')
        return value

class ManualBusinessEmail(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    email: str=Field(min_length=3,max_length=254)
    source_url: str=Field(min_length=1,max_length=2048)
    public_business_observed: Literal[True]
    @field_validator('email')
    @classmethod
    def plain_address(cls,value):
        import re
        if not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+',value) or any(ord(c)<33 for c in value):
            raise ValueError('Enter a plain business-role email address without headers or links.')
        return value
    @field_validator('source_url')
    @classmethod
    def public_page(cls,value):
        value=profile_url(value)
        if unquote(urlsplit(value).path).lower().startswith('/cdn-cgi/'):
            raise ValueError('Attribute the public source page, not a protection or reveal endpoint.')
        return value
    @field_validator('public_business_observed',mode='before')
    @classmethod
    def explicit_observation(cls,value):
        if value is not True:raise ValueError('Explicit public business-contact observation is required.')
        return value
