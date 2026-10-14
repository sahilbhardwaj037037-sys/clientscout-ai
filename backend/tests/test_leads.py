import pytest
from sqlalchemy.orm import Session
from app.models.lead import Lead


def create(client, url='https://example.com', **fields):
    return client.post('/api/leads', json={'website_url': url, **fields})


def test_crud_status_notes_metrics_and_persistence(client, database):
    empty = client.get('/api/dashboard').json()
    assert empty['leads_found'] == 0 and empty['recent'] == []
    assert empty['high_priority'] is None and empty['drafts_ready'] is None
    response = create(client, business_name='User supplied', category='Café', location='Delhi')
    assert response.status_code == 201
    lead = response.json()
    assert lead['website_url'] == 'https://example.com/' and lead['source'] == 'manual'
    assert lead['created_at'].endswith('Z')
    lead_id = lead['id']
    assert client.get(f'/api/leads/{lead_id}').json()['business_name'] == 'User supplied'
    response = client.patch(f'/api/leads/{lead_id}', json={'notes': 'Review manually', 'status': 'shortlisted'})
    assert response.status_code == 200
    with Session(database) as fresh:
        persisted = fresh.get(Lead, lead_id)
        assert persisted.notes == 'Review manually' and persisted.status == 'shortlisted'
    metrics = client.get('/api/dashboard').json()
    assert metrics['leads_found'] == 1 and metrics['by_status']['shortlisted'] == 1
    assert metrics['recent'][0]['id'] == lead_id
    assert client.delete(f'/api/leads/{lead_id}').status_code == 204
    assert client.get(f'/api/leads/{lead_id}').status_code == 404
    assert client.get('/api/dashboard').json()['leads_found'] == 0


@pytest.mark.parametrize('url', ['http://www.EXAMPLE.com/contact?utm_source=one#about', 'example.com', 'https://example.com:443/another'])
def test_duplicates_do_not_overwrite(client, url):
    lead = create(client, business_name='Original', notes='Keep this').json()
    duplicate = create(client, url, business_name='Replacement')
    assert duplicate.status_code == 409
    assert duplicate.json()['detail']['existing_id'] == lead['id']
    assert client.get('/api/leads').json()['total'] == 1
    assert client.get(f"/api/leads/{lead['id']}").json()['notes'] == 'Keep this'


def test_update_conflict_rolls_back(client):
    first = create(client).json()
    second = create(client, 'https://another.example.org').json()
    conflict = client.patch(f"/api/leads/{second['id']}", json={'website_url': 'http://www.example.com/path', 'notes': 'Do not save'})
    assert conflict.status_code == 409 and conflict.json()['detail']['existing_id'] == first['id']
    unchanged = client.get(f"/api/leads/{second['id']}").json()
    assert unchanged['website_url'] == 'https://another.example.org/' and unchanged['notes'] == ''


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'javascript:alert(1)', 'https://user:secret@example.com',
    'http://localhost', 'http://127.0.0.1', 'http://10.0.0.1', 'http://169.254.169.254', 'http://[::1]',
    'http://2130706433', 'http://127.1', 'http://0x7f000001', 'https://bad..example.com', 'https://example.com:9000',
    'https://example.com\\@localhost', 'ftp://example.com'])
def test_reject_invalid_or_nonpublic_url(client, url):
    assert create(client, url).status_code == 422
    assert client.get('/api/dashboard').json()['leads_found'] == 0


def test_validation_and_missing_leads(client):
    assert create(client, notes='x' * 10001).status_code == 422
    assert create(client, status='high_priority').status_code == 422
    lead = create(client).json()
    for payload in [{}, {'notes': None}, {'source': 'provider'}, {'business_name': ' '}]:
        assert client.patch(f"/api/leads/{lead['id']}", json=payload).status_code == 422
    assert client.patch('/api/leads/9999', json={'notes': 'Missing'}).status_code == 404
    assert client.delete('/api/leads/9999').status_code == 404


def test_search_status_pagination_wildcards(client):
    create(client, 'a.example.org', business_name='Alpha 100%', status='contacted')
    create(client, 'b.example.org', business_name='Beta', location='Delhi')
    result = client.get('/api/leads', params={'q': 'Delhi'}).json()
    assert result['total'] == 1 and result['items'][0]['business_name'] == 'Beta'
    assert client.get('/api/leads', params={'q': '%'}).json()['total'] == 1
    assert client.get('/api/leads', params={'status': 'contacted'}).json()['total'] == 1
    page = client.get('/api/leads', params={'limit': 1, 'offset': 1}).json()
    assert page['total'] == 2 and page['items'][0]['business_name'] == 'Alpha 100%'
    assert client.get('/api/leads?limit=101').status_code == 422
    assert client.get('/api/leads?status=invalid').status_code == 422


def test_csv_partial_results_provenance_duplicates(client):
    original = create(client, notes='Keep original').json()
    csv = '\ufeffwebsite_url,business_name,status,notes\r\nhttps://example.com,Overwrite,new,Overwrite\r\nhttps://csv.example.org,CSV entry,shortlisted,"A comma, and\na newline"\r\nhttp://localhost,Invalid,new,\r\nhttp://www.csv.example.org/contact,Duplicate,new,\r\n'
    response = client.post('/api/imports/csv', content=csv.encode(), headers={'Content-Type': 'text/csv', 'X-Import-Filename': 'my%20leads.csv'})
    assert response.status_code == 200
    report = response.json()
    assert (report['created'], report['duplicates'], report['invalid']) == (1, 2, 1)
    saved = client.get(f"/api/leads/{report['rows'][1]['lead_id']}").json()
    assert saved['source'] == 'csv' and saved['source_filename'] == 'my leads.csv'
    assert saved['notes'] == 'A comma, and\na newline'
    assert client.get(f"/api/leads/{original['id']}").json()['notes'] == 'Keep original'
    assert client.get('/api/dashboard').json()['by_status']['shortlisted'] == 1


@pytest.mark.parametrize('data', [b'', b'name\nWrong\n', b'website_url,website_url\na.example.org,b.example.org',
    b'website_url,score\na.example.org,100', b'website_url\n"unterminated', b'website_url\n\xff',
    b'website_url\n\x00', ('website_url\n' + 'a.example.org\n' * 501).encode()])
def test_malformed_csv_is_not_partially_saved(client, data):
    response = client.post('/api/imports/csv', content=data, headers={'Content-Type': 'text/csv'})
    assert response.status_code == 422
    assert client.get('/api/dashboard').json()['leads_found'] == 0


def test_csv_limits_content_type_and_columns(client):
    assert client.post('/api/imports/csv', content=b'x' * (1024 * 1024 + 1), headers={'Content-Type': 'text/csv'}).status_code == 413
    assert client.post('/api/imports/csv', content=b'website_url\nexample.com', headers={'Content-Type': 'application/json'}).status_code == 415
    response = client.post('/api/imports/csv', content='website_url,status\na.example.org,\nb.example.org,new,extra\n', headers={'Content-Type': 'text/csv'})
    assert response.json()['created'] == 1 and response.json()['invalid'] == 1
    assert client.get('/api/leads').json()['items'][0]['status'] == 'new'
