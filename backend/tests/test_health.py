def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "service": "clientscout-api", "version": "0.4.0", "checkpoint": 4, "database": "ready"
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
