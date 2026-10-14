"""Extract bounded, explicitly published business contacts; never guess addresses."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,unquote
from app.services.urls import normalize_url

KINDS=('email','phone','whatsapp','contact_page','contact_form','facebook','instagram','linkedin')
ROLE_EMAIL=re.compile(r'^(info|hello|contact|office|sales|support|enquiries|inquiries|bookings|booking|reservations|admin|help|business|customer[._-]?service)([._+-].*)?$',re.I)
ORG_TYPES={'Organization','LocalBusiness','Restaurant','Store','ProfessionalService','Dentist','Hotel','CafeOrCoffeeShop','Bakery'}

class ContactPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.links=[];self.forms=[];self.title='';self.text=[];self.organizations=[];self._title=False;self._script=None;self._hidden=0;self._a=None;self._business_context=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in {'footer','header','address'}:self._business_context+=1
        if tag=='title':self._title=True
        if tag in {'script','style'}:
            self._hidden+=1
            if tag=='script' and a.get('type','').lower()=='application/ld+json':self._script=''
        if tag=='a' and len(self.links)<100:self._a={'href':a.get('href','')[:2048],'label':(a.get('aria-label') or '')[:200],'business_context':bool(self._business_context)}
        if tag=='form' and len(self.forms)<5:self.forms.append(a.get('action','')[:2048])
    def handle_data(self,data):
        if self._script is not None and len(self._script)<262144:self._script+=data[:262144-len(self._script)]
        if self._title:self.title=(self.title+data)[:1000]
        if not self._hidden:
            if len(self.text)<1500:self.text.append(data[:500])
            if self._a:self._a['label']=(self._a['label']+data)[:200]
    def handle_endtag(self,tag):
        if tag in {'footer','header','address'}:self._business_context=max(0,self._business_context-1)
        if tag=='title':self._title=False
        if tag=='a' and self._a:self.links.append(self._a);self._a=None
        if tag in {'script','style'}:
            if tag=='script' and self._script is not None:
                try:
                    document=json.loads(self._script)
                    nodes=document if isinstance(document,list) else document.get('@graph',[document]) if isinstance(document,dict) else []
                    if not isinstance(nodes,list):nodes=[]
                    for item in nodes[:100]:
                        if isinstance(item,dict) and any(t in ORG_TYPES for t in (item.get('@type',[]) if isinstance(item.get('@type'),list) else [item.get('@type')])):self.organizations.append(item)
                except (ValueError,TypeError):pass
            self._script=None;self._hidden=max(0,self._hidden-1)

def safe_link(base,raw):
    try:return normalize_url(urljoin(base,raw))[0]
    except (ValueError,TypeError):return None

def role_email(raw,business_name):
    raw=unquote(raw.removeprefix('mailto:')).split('?')[0].strip().lower()
    if not re.fullmatch(r'[a-z0-9.!#$%&\'*+/=?^_`{|}~-]{1,64}@[a-z0-9.-]{1,190}\.[a-z]{2,24}',raw) or '..' in raw:return None
    local=raw.split('@')[0];name=re.sub('[^a-z0-9]','',business_name.casefold())
    # Personal staff/name addresses are deliberately excluded, even when public.
    return raw if ROLE_EMAIL.fullmatch(local) or len(name)>=5 and re.sub('[^a-z0-9]','',local)==name else None

def phone(raw):
    raw=unquote(raw.removeprefix('tel:')).strip()
    return raw[:40] if re.fullmatch(r'\+?[0-9 ()-]{7,35}',raw) and 7<=len(re.sub(r'\D','',raw))<=15 else None

def public_url(kind,raw,base):
    value=safe_link(base,raw)
    if not value:return None
    host=(urlsplit(value).hostname or '').removeprefix('www.');path=urlsplit(value).path
    rules={'whatsapp':host=='wa.me' and bool(re.fullmatch(r'/[0-9]{7,15}',path)) or host=='api.whatsapp.com' and path=='/send',
        'facebook':host in {'facebook.com','m.facebook.com'} and path not in {'','/'},'instagram':host=='instagram.com' and bool(re.fullmatch(r'/[A-Za-z0-9._]+/?',path)),
        'linkedin':host in {'linkedin.com','uk.linkedin.com'} and path.startswith('/company/')}
    if kind in rules and not rules[kind]:return None
    if kind in {'contact_page','contact_form'} and normalize_url(value)[1]!=normalize_url(base)[1]:return None
    return value

def extract_contacts(page,url,name):
    values=[]
    def add(kind,value,evidence):
        if value and (kind,value) not in [(v['kind'],v['value']) for v in values] and sum(v['kind']==kind for v in values)<3:
            values.append({'kind':kind,'value':value,'evidence':evidence[:300]})
    for item in page.links:
        raw=item['href'];label=item['label'].lower()
        if raw.startswith('mailto:'):add('email',role_email(raw,name),'Role/business-address mailto link')
        elif raw.startswith('tel:') and bool(re.fullmatch(r'(call( us| now)?|phone|telephone|tel|contact( us)?|business phone|[+0-9 ()-]+)',label.strip())):add('phone',phone(raw),'Explicitly labelled business telephone link')
        else:
            for kind in ('whatsapp','facebook','instagram','linkedin'):
                if item.get('business_context'):add(kind,public_url(kind,raw,url),'Public business header/footer link; profile itself was not fetched and profile ownership needs review')
            if re.search(r'(^|/)(contact|contact-us)(/|$)',urlsplit(safe_link(url,raw) or '').path,re.I):add('contact_page',public_url('contact_page',raw,url),'Observed same-domain contact link')
    for org in page.organizations:
        # Caller verifies organization identity before storing these observations.
        for raw in (org.get('sameAs') if isinstance(org.get('sameAs'),list) else []):
            if isinstance(raw,str):
                for kind in ('whatsapp','facebook','instagram','linkedin'):add(kind,public_url(kind,raw,url),'Organization JSON-LD public profile association; profile was not fetched')
        if isinstance(org.get('email'),str):add('email',role_email(org['email'],name),'Organization JSON-LD role/business email')
        if isinstance(org.get('telephone'),str):add('phone',phone(org['telephone']),'Organization JSON-LD telephone')
    if re.search(r'(^|/)(contact|contact-us)(/|$)',urlsplit(url).path,re.I):
        add('contact_page',url,'Permitted contact page visited')
        for action in page.forms:add('contact_form',public_url('contact_form',action,url),'Observed same-domain form action; never submitted')
    return values

def osm_contacts(snapshot):
    tags=snapshot.get('business_tags') or {};name=snapshot.get('name') or '';values=[]
    mapping={'email':['email','contact:email'],'phone':['phone','contact:phone'],'whatsapp':['contact:whatsapp'],'facebook':['contact:facebook'],'instagram':['contact:instagram'],'linkedin':['contact:linkedin']}
    for kind,keys in mapping.items():
        for key in keys:
            raw=tags.get(key)
            if not isinstance(raw,str):continue
            value=role_email(raw,name) if kind=='email' else phone(raw) if kind=='phone' else public_url(kind,raw,snapshot.get('website_url') or 'https://www.openstreetmap.org/')
            if value:values.append({'kind':kind,'value':value,'status':'public_unverified','source_url':snapshot['source_url'],'source_kind':'osm','licence':'ODbL-1.0','attribution':'© OpenStreetMap contributors','fetched_at':snapshot.get('fetched_at'),'evidence':f'Existing business tag {key}; not independently verified'})
    return values
