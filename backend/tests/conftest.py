from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from app.database.session import get_session, make_engine
from app.main import app

@pytest.fixture(autouse=True)
def forbid_live_gemini(monkeypatch):
    from google.genai.models import AsyncModels
    async def blocked(*args,**kwargs):raise AssertionError('Tests must never make real Gemini calls.')
    monkeypatch.setattr(AsyncModels,'generate_content',blocked)

@pytest.fixture
def database(tmp_path):
    engine = make_engine(tmp_path / 'test.db')
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    yield engine
    engine.dispose()

@pytest.fixture
def client(database):
    sessions = sessionmaker(database, expire_on_commit=False)
    def override():
        with sessions() as session:
            yield session
    app.dependency_overrides[get_session] = override
    app.state.audit_engine = database
    with TestClient(app, base_url='http://127.0.0.1') as client:
        yield client
    app.dependency_overrides.clear()
    del app.state.audit_engine


@pytest.fixture
def anyio_backend():
    # The application uses asyncio; keep the test runtime consistent across modules.
    return 'asyncio'
