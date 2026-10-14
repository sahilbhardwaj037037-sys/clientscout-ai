"""Isolated QA server with labelled fixture sources; never a live-provider proof.

Run with backend/.venv/bin/python, PYTHONPATH=backend and the QA environment.
Production source fetching, security settings and the user's database are untouched.
"""
import os
from pathlib import Path

database=Path(os.environ.get('CLIENTSCOUT_DB_PATH','')).resolve()
if os.environ.get('CLIENTSCOUT_QA_FIXTURE_SOURCES')!='true' or not database.is_relative_to(Path('/private/tmp/clientscout-qa')):
    raise RuntimeError('Explicit fixture opt-in and isolated /private/tmp/clientscout-qa database required.')
os.environ['GEMINI_API_KEY']=''
os.environ['DISCOVERY_ENABLED']='false'
os.environ['PAGESPEED_ENABLED']='false'

from alembic import command
from alembic.config import Config
from app.auditing.network import Fetched
from app.intelligence.enrichment import enrich
from app.main import app
from app.models.lead import now
import uvicorn

ROOT=Path(__file__).resolve().parents[1]
config=Config(str(ROOT/'backend/alembic.ini'))
config.set_main_option('script_location',str(ROOT/'backend/migrations'))
command.upgrade(config,'head')

HOME=b'''<html><title>Checkpoint 4 QA Cafe</title><script type="application/ld+json">{"@type":"Restaurant","name":"Checkpoint 4 QA Cafe","email":"info@example.com","telephone":"+44 1234 567890","sameAs":["https://www.instagram.com/qa_cafe/"]}</script><body><p>We are a small independent business.</p><a href="/contact">Contact</a><a href="mailto:john.smith@example.com">Staff address</a></body></html>'''
CONTACT=b'<title>Checkpoint 4 QA Cafe Contact</title><form action="/contact/send"></form><a href="mailto:hello@example.com">Business contact</a>'

class FixtureFetcher:
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def get(self,url,**kwargs):
        pages={'https://example.com/':HOME,'https://example.com/contact':CONTACT}
        body=pages.get(url,b'');status=200 if url in pages else 404
        return Fetched(url,status,{'content-type':'text/html'},body,1,now().isoformat(),[])

async def fixture_runner(snapshot,url,official,directory,progress):
    return await enrich(snapshot,url,official,directory,progress,FixtureFetcher)

app.state.enrichment_runner=fixture_runner
if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ['CLIENTSCOUT_API_PORT']))
