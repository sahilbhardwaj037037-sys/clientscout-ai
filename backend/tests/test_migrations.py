from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from app.database.session import make_engine


def test_migrations_upgrade_downgrade_reopen(tmp_path):
    path = tmp_path / 'migration.db'
    engine = make_engine(path)
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    assert 'leads' in inspect(engine).get_table_names()
    engine.dispose()
    reopened = make_engine(path)
    with reopened.begin() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0002_audits'
        config.attributes['connection'] = connection
        command.downgrade(config, 'base')
    assert 'leads' not in inspect(reopened).get_table_names()
    with reopened.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    assert 'leads' in inspect(reopened).get_table_names()
    reopened.dispose()


def test_audit_upgrade_preserves_existing_lead_data(tmp_path):
    from sqlalchemy.orm import Session
    from app.models.lead import Lead
    engine = make_engine(tmp_path / 'existing-leads.db')
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, '0001_leads')
    with Session(engine) as session:
        lead = Lead(business_name='Preserved fixture', website_url='https://example.com/', normalized_key='example.com', source='manual', original_url='example.com', notes='Keep notes', status='contacted')
        session.add(lead); session.commit(); lead_id = lead.id
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    with Session(engine) as session:
        lead = session.get(Lead, lead_id)
        assert lead.business_name == 'Preserved fixture' and lead.notes == 'Keep notes' and lead.status == 'contacted'
        assert lead.original_url == 'example.com'
    assert 'audits' in inspect(engine).get_table_names()
    engine.dispose()
