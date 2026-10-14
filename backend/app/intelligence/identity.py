import math
import re
from app.services.urls import normalize_url


def words(value):return set(re.findall(r'[a-z0-9]+',str(value).casefold()))-{'the','and','ltd','limited','www','com'}
def name_matches(expected,actual):
    a,b=words(expected),words(actual)
    return bool(a and b) and (a<=b or len(a&b)/len(a|b)>=.6)

def verify_identity(snapshot,page,url,official_confirmed):
    name=snapshot.get('name') or ''
    matching=[item for item in page.organizations if name_matches(name,item.get('name',''))]
    reasons=[];mismatch=False
    if page.organizations and not matching:mismatch=True;reasons.append('Published organization names do not match the selected business; contact records were not combined.')
    if snapshot.get('website_url') and normalize_url(snapshot['website_url'])[1]!=normalize_url(url)[1]:mismatch=True;reasons.append('Official-domain association differs from the selected source.')
    for org in matching:
        address=org.get('address')
        if isinstance(address,dict):
            city=address.get('addressLocality');expected=(snapshot.get('business_tags') or {}).get('addr:city')
            if city and expected and not name_matches(expected,city):mismatch=True;reasons.append('Source city and published locality disagree; possible same-name/branch mismatch.')
        geo=org.get('geo')
        if isinstance(geo,dict) and snapshot.get('latitude') is not None:
            try:
                latitude,longitude=float(geo['latitude']),float(geo['longitude'])
                if not -90<=latitude<=90 or not -180<=longitude<=180:raise ValueError
                distance=6371000*2*math.asin(min(1,math.sqrt(math.sin(math.radians(latitude-snapshot['latitude'])/2)**2+math.cos(math.radians(latitude))*math.cos(math.radians(snapshot['latitude']))*math.sin(math.radians(longitude-snapshot['longitude'])/2)**2)))
                if distance>10000:mismatch=True;reasons.append('Published/source coordinates differ by over 10 km; branch identity needs review.')
            except (ValueError,TypeError,KeyError):reasons.append('Published coordinates were invalid; no geographic match claimed.')
    matched=bool(matching or name_matches(name,page.title))
    if mismatch:return {'status':'mismatch','confidence':0,'reasons':reasons,'official':False},[]
    if matched and official_confirmed:
        return {'status':'matched','confidence':85,'reasons':['Business name matches published title/organization and the supplied domain; user confirmed official-source association.']+reasons,'official':True},matching
    return {'status':'needs_review','confidence':50 if matched else 20,'reasons':(['Name/domain signals match, but official-source association is not confirmed.'] if matched else ['Business name could not be established from permitted page evidence.'])+reasons,'official':False},matching
