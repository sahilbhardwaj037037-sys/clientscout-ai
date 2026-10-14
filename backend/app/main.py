"""Local leads and permitted URL audits. No discovery, scoring or AI calls."""
from typing import Literal
from contextlib import asynccontextmanager
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
    worker = AuditManager(getattr(application.state, 'audit_engine', engine), runner=getattr(application.state, 'audit_runner', run_audit))
    application.state.audit_manager = worker
    worker.recover()
    try:
        yield
    finally:
        await worker.shutdown()


app = FastAPI(title='ClientScout AI', version='0.3.0', lifespan=lifespan)
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
async def database_error(_request, _error):
    return JSONResponse(status_code=503, content={'detail': 'Database unavailable. Check local database permissions and run alembic upgrade head from backend.'})


class HealthResponse(BaseModel):
    status: Literal['ok']
    service: Literal['clientscout-api']
    version: str
    checkpoint: int
    database: Literal['ready']


@app.get('/api/health', response_model=HealthResponse)
def health(session: Session = Depends(get_session)):
    revision = session.scalar(text('SELECT version_num FROM alembic_version'))
    if revision != '0002_audits':
        raise HTTPException(503, 'Database migration required. Run alembic upgrade head from backend.')
    session.execute(text('SELECT id FROM leads LIMIT 1'))
    session.execute(text('SELECT id FROM audits LIMIT 1'))
    return HealthResponse(status='ok', service='clientscout-api', version='0.3.0', checkpoint=3, database='ready')


app.include_router(router)

app.include_router(audits_router)
