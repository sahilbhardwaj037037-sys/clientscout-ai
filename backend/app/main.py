"""Local leads, permitted source research and explicitly requested AI assistance."""
from typing import Literal
import sqlite3
from contextlib import asynccontextmanager
from app.api.intelligence import router as intelligence_router
from app.intelligence.enrichment import enrich
from app.providers.gemini import select_context,write_proposal
from app.intelligence.manager import EnrichmentManager
from app.intelligence.ai_manager import AIManager
from app.providers.diagnostics import configure_logging
from app.discovery.manager import DiscoveryManager
from app.api.discovery import router as discovery_router
from app.auditing.manager import AuditManager
from app.auditing.runner import run_audit
from app.api.audits import router as audits_router
from app.database.session import engine
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.api.leads import router
from app.core.settings import API_PORT, FRONTEND_PORT
from app.database.session import get_session

@asynccontextmanager
async def lifespan(application):
    configure_logging()
    worker = AuditManager(getattr(application.state, 'audit_engine', engine), runner=getattr(application.state, 'audit_runner', run_audit))
    application.state.audit_manager = worker
    worker.recover()
    discovery = DiscoveryManager(getattr(application.state, 'audit_engine', engine), provider=getattr(application.state, 'discovery_provider', None))
    application.state.discovery_manager = discovery
    discovery.recover()
    enrichment=EnrichmentManager(getattr(application.state,'audit_engine',engine),runner=getattr(application.state,'enrichment_runner',enrich))
    application.state.enrichment_manager=enrichment;enrichment.recover()
    ai=AIManager(getattr(application.state,'audit_engine',engine),provider=getattr(application.state,'gemini_provider',select_context),writer_provider=getattr(application.state,'gemini_writer_provider',write_proposal))
    application.state.ai_manager=ai;ai.recover()
    try:
        yield
    finally:
        await ai.shutdown()
        await enrichment.shutdown()
        await discovery.shutdown()
        await worker.shutdown()


app = FastAPI(title='ClientScout AI', version='0.4.0', lifespan=lifespan)
LOCAL_ORIGINS = [f'http://{host}:{port}' for host in ['127.0.0.1', 'localhost'] for port in [FRONTEND_PORT, FRONTEND_PORT + 1, API_PORT]]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]'])
app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_ORIGINS,
    allow_methods=['GET', 'POST', 'PATCH', 'DELETE'],
    allow_headers=['Content-Type', 'X-Import-Filename'],
)


@app.middleware('http')
async def protect_local_writes(request, call_next):
    if request.method in {'POST', 'PATCH', 'DELETE'} and request.headers.get('origin') is not None and request.headers['origin'] not in LOCAL_ORIGINS:
        return JSONResponse(status_code=403, content={'detail': 'Writes from this origin are not allowed.'})
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(_request, error):
    original=getattr(error,'orig',None)
    code=getattr(original,'sqlite_errorcode',None)
    base_code=(code & 0xff) if isinstance(original,sqlite3.Error) and type(code) is int else None
    if base_code in {sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED}:
        return JSONResponse(status_code=503,headers={'Retry-After':'2'},content={
            'code':'database_busy',
            'detail':'Database busy: another transaction is holding a lock. Refresh job status before trying again.'})
    if base_code in {sqlite3.SQLITE_READONLY,sqlite3.SQLITE_CANTOPEN,sqlite3.SQLITE_PERM}:
        return JSONResponse(status_code=503,content={
            'code':'database_access_error',
            'detail':'Database file cannot be opened or written. Check the local database path and filesystem permissions.'})
    # Inspect only the native error locally; never return SQL, parameters, paths,
    # exception strings or credential values in an API response.
    if base_code==sqlite3.SQLITE_ERROR and str(original).lower().startswith(('no such table:','no such column:')):
        return JSONResponse(status_code=503,content={
            'code':'database_schema_error',
            'detail':'Database schema does not match this application. Run alembic upgrade head from backend.'})
    return JSONResponse(status_code=503,content={
        'code':'database_unavailable',
        'detail':'Database unavailable. Check backend status and local database access.'})


class HealthResponse(BaseModel):
    status: Literal['ok']
    service: Literal['clientscout-api']
    version: str
    checkpoint: int
    database: Literal['ready']


@app.get('/api/health', response_model=HealthResponse)
def health(session: Session = Depends(get_session)):
    revision = session.scalar(text('SELECT version_num FROM alembic_version'))
    if revision != '0006_ai_jobs':
        raise HTTPException(503, 'Database migration required. Run alembic upgrade head from backend.')
    session.execute(text('SELECT id FROM leads LIMIT 1'))
    session.execute(text('SELECT id FROM audits LIMIT 1'))
    session.execute(text('SELECT id FROM discovered_businesses LIMIT 1'))
    session.execute(text('SELECT id FROM discovery_searches LIMIT 1'))
    session.execute(text('SELECT key FROM discovery_cache LIMIT 1'))
    session.execute(text('SELECT id FROM business_identities LIMIT 1'))
    session.execute(text('SELECT id FROM ai_usage LIMIT 1'))
    return HealthResponse(status='ok', service='clientscout-api', version='0.4.0', checkpoint=4, database='ready')


app.include_router(router)

app.include_router(audits_router)

app.include_router(discovery_router)

app.include_router(intelligence_router)
