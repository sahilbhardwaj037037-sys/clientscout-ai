"""Upgrade/rollback and preservation exercised only on temporary databases."""
import hashlib,json
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect,text
from sqlalchemy.orm import Session
from app.database.session import make_engine
from app.models.lead import Lead
from app.models.intelligence import BusinessIdentity,OutreachDraft
from app.research.manager import ResearchManager
from app.schemas.research import JobCreate
from test_research import payload

def contents(engine):
    with engine.connect() as c:
        result={}
        for table in inspect(c).get_table_names():
            if table.startswith('research_') or table=='alembic_version':continue
            rows=c.exec_driver_sql('SELECT * FROM "'+table+'" ORDER BY rowid').fetchall()
            result[table]=hashlib.sha256(json.dumps([tuple(r) for r in rows],default=str).encode()).hexdigest()
        return result

def test_foundation_upgrade_check_rollback_preserves_legacy_records_and_drafts(tmp_path):
    engine=make_engine(tmp_path/'legacy.db');cfg=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    with engine.begin() as c:
        cfg.attributes['connection']=c;command.upgrade(cfg,'0006_ai_jobs')
    with Session(engine) as s:
        lead=Lead(business_name='Legacy fixture',website_url='https://example.com/',normalized_key='example.com',source='manual',original_url='example.com',notes='Private legacy notes',status='contacted')
        s.add(lead);s.flush();identity=BusinessIdentity(lead_id=lead.id,snapshot={'name':'Legacy fixture'});s.add(identity);s.flush()
        draft=OutreachDraft(identity_id=identity.id,channel='email',generator='gemini',subject='Keep this subject',body='Keep paragraphs.\n\nKind regards,\nSam',evidence={'writer_version':'human-reviewed-v1','review':{'state':'ready','factual_status':'unverified'}},saved=True)
        s.add(draft);s.commit()
    before=contents(engine)
    with engine.begin() as c:
        cfg.attributes['connection']=c;command.upgrade(cfg,'head');command.check(cfg)
    assert contents(engine)==before
    ResearchManager(engine).create(JobCreate.model_validate(payload()))
    with engine.begin() as c:
        cfg.attributes['connection']=c;command.downgrade(cfg,'0006_ai_jobs')
    assert not any(t.startswith('research_') for t in inspect(engine).get_table_names())
    assert contents(engine)==before
    with engine.begin() as c:
        cfg.attributes['connection']=c;command.upgrade(cfg,'head');command.check(cfg)
        assert c.scalar(text('SELECT version_num FROM alembic_version'))=='0007_research_foundation'
    assert contents(engine)==before
    engine.dispose()
