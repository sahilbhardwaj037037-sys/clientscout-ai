"""Local, user-confirmed public profile. No fetching, secrets or schema migration."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from fastapi import HTTPException
from app.schemas.intelligence import FreelancerProfile

MAX_PROFILE_BYTES=32768

def path_for(engine):
    return Path(engine.url.database).with_name('freelancer-profile.json')

def read_profile(engine):
    path=path_for(engine)
    if not path.exists():return FreelancerProfile()
    try:
        if path.stat().st_size>MAX_PROFILE_BYTES:raise ValueError
        return FreelancerProfile.model_validate_json(path.read_text())
    except (OSError,ValueError):raise HTTPException(503,'Freelancer profile unavailable. Review and save it locally before AI writing.') from None

def save_profile(engine,profile):
    if len({p.id for p in profile.projects})!=len(profile.projects):raise HTTPException(422,'Use unique project IDs.')
    if any(not set(p.service_ids)<=set(profile.service_ids) for p in profile.projects):raise HTTPException(422,'Project services must be among your confirmed offered services.')
    serialized=json.dumps(profile.model_dump(),ensure_ascii=False).encode('utf-8')
    if len(serialized)>MAX_PROFILE_BYTES:raise HTTPException(422,'Public profile exceeds the local storage limit. Shorten project details or URLs.')
    path=path_for(engine);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with NamedTemporaryFile(mode='wb',dir=path.parent,prefix='.profile-',delete=False) as f:
            temporary=Path(f.name);f.write(serialized);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    except OSError:raise HTTPException(503,'Unable to save the freelancer profile locally.') from None
    finally:
        if temporary and temporary.exists():temporary.unlink()
    return profile
