def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "service": "clientscout-api", "version": "0.5.1", "checkpoint": 5, "database": "ready"
    }


def test_cors_allows_only_local_frontend(client):
    allowed = client.get("/api/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    denied = client.get("/api/health", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in denied.headers


def test_untrusted_host_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "example.com"}).status_code == 400


def test_foreign_origins_cannot_write(client):
    response = client.post('/api/leads', json={'website_url': 'example.com'}, headers={'Origin': 'https://example.net'})
    assert response.status_code == 403
    assert client.get('/api/dashboard').json()['leads_found'] == 0


def test_write_preflight_is_explicitly_allowed_for_local_frontend(client):
    response = client.options('/api/leads', headers={
        'Origin': 'http://127.0.0.1:5173', 'Access-Control-Request-Method': 'PATCH',
        'Access-Control-Request-Headers': 'content-type',
    })
    assert response.status_code == 200
    assert 'PATCH' in response.headers['access-control-allow-methods']
    assert client.get('/api/health').headers['cache-control'] == 'no-store'


def test_health_does_not_claim_success_before_migration(client, tmp_path):
    from sqlalchemy.orm import Session
    from app.database.session import get_session, make_engine
    from app.main import app
    empty = make_engine(tmp_path / 'unmigrated.db')
    def no_schema():
        with Session(empty) as session:
            yield session
    app.dependency_overrides[get_session] = no_schema
    response = client.get('/api/health')
    assert response.status_code == 503
    assert 'alembic upgrade head' in response.json()['detail']
    empty.dispose()


def test_sqlite_failures_have_safe_distinct_responses(client,monkeypatch):
    import sqlite3
    from sqlalchemy.exc import OperationalError
    from app.database.session import get_session
    from app.main import app
    cases=[
        (sqlite3.SQLITE_BUSY,'database is locked','database_busy'),
        (sqlite3.SQLITE_LOCKED,'database table is locked','database_busy'),
        (sqlite3.SQLITE_BUSY | (2 << 8),'database is locked','database_busy'),
        (sqlite3.SQLITE_READONLY,'attempt to write a readonly database','database_access_error'),
        (sqlite3.SQLITE_CANTOPEN,'unable to open database file','database_access_error'),
        (sqlite3.SQLITE_PERM,'access permission denied','database_access_error'),
        (sqlite3.SQLITE_ERROR,'no such table: PRIVATE_TABLE','database_schema_error'),
        (sqlite3.SQLITE_ERROR,'no such column: PRIVATE_COLUMN','database_schema_error'),
        (sqlite3.SQLITE_ERROR,'near PRIVATE_SQL: syntax error','database_unavailable'),
    ]
    for code,message,expected in cases:
        original=sqlite3.OperationalError(message);original.sqlite_errorcode=code
        def fail():
            raise OperationalError('PRIVATE_SQL',{'credential':'PRIVATE_PARAMETER'},original)
            yield  # Keep the same dependency shape; no query reaches SQLite.
        monkeypatch.setitem(app.dependency_overrides,get_session,fail)
        response=client.get('/api/health')
        assert response.status_code==503
        assert response.json()['code']==expected
        assert 'PRIVATE' not in response.text
        assert ('alembic upgrade head' in response.json()['detail'])==(expected=='database_schema_error')
        assert ('Retry-After' in response.headers)==(expected=='database_busy')
