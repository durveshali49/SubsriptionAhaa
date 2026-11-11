import json
import uuid
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi.testclient import TestClient
from app import main

H = {'X-Ahaa-Request': '1'}

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('META_WHATSAPP_ENABLED', 'false')
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setattr(main, 'SUPABASE_DATABASE_URL', '')
    with TestClient(main.app) as c:
        credentials = {'email': 'owner@example.com', 'password': 'Secure-kitchen-2026'}
        assert c.post('/api/setup', json=credentials, headers=H).status_code == 200
        assert c.post('/api/login', json=credentials, headers=H).status_code == 200
        yield c


def create(c, consent=True):
    r=c.post('/api/customers', headers=H, json={'name':'Test Customer', 'email':'test@example.com', 'phone':'+12025550123', 'consent':consent})
    assert r.status_code == 200, r.text
    return r.json()['id']


def pay(c, cid, **kwargs):
    payload={'key':str(uuid.uuid4()), 'customer_id':cid, 'method':'Cash', **kwargs}
    return c.post('/api/enrollments', headers=H, json=payload), payload


def order(c, cid, total, **kwargs):
    payload={'key':str(uuid.uuid4()), 'customer_id':cid, 'items':[{'name':'Biryani', 'quantity':1, 'price':total}], **kwargs}
    return c.post('/api/orders', headers=H, json=payload), payload


def test_owner_access_and_csrf(client):
    with TestClient(main.app) as outsider:
        assert outsider.get('/api/data').status_code == 401
        assert outsider.post('/api/customers', json={}).status_code == 403
    assert client.post('/api/logout', headers={**H,'origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/setup', headers=H,json={'email':'x@example.com','password':'another-password'}).status_code == 409


def test_payment_order_renew_and_idempotency(client):
    cid=create(client)
    r,payload=pay(client,cid)
    assert r.json()['balance']==24000
    assert client.post('/api/enrollments',headers=H,json=payload).json()['id']==r.json()['id']
    assert pay(client,cid)[0].status_code==409
    r,payload=order(client,cid,4000)
    assert r.json()['balance']==20000
    assert client.post('/api/orders',headers=H,json=payload).json()['id']==r.json()['id']
    payload['items'][0]['price']=5000
    assert client.post('/api/orders',headers=H,json=payload).status_code==409
    assert order(client,cid,20001)[0].status_code==400
    assert order(client,cid,20000)[0].json()['balance']==0
    assert pay(client,cid)[0].json()['balance']==24000
    data=client.get('/api/data').json()
    assert len(data['events'])==4
    assert set(data)=={'customers','events'}


def test_fixed_amount_and_validation(client):
    cid=create(client)
    assert pay(client,cid,amount=10000)[0].status_code==400
    pay(client,cid)
    assert order(client,cid,0)[0].status_code==400
    assert order(client,cid,-1)[0].status_code==422
    assert order(client,cid,100,items=[{'name':' ', 'quantity':1,'price':100}])[0].status_code==422
    assert order(client,cid,100,items=[{'name':'Food', 'quantity':1.5,'price':100}])[0].status_code==422


def test_order_whatsapp_submission_is_once_per_order_and_respects_consent(client, monkeypatch):
    monkeypatch.setenv('META_WHATSAPP_ENABLED', 'true')
    monkeypatch.setenv('META_GRAPH_API_VERSION', 'v25.0')
    monkeypatch.setenv('META_WHATSAPP_PHONE_NUMBER_ID', '123')
    monkeypatch.setenv('META_WHATSAPP_ACCESS_TOKEN', 'test-token')
    monkeypatch.setenv('META_WHATSAPP_TEMPLATE_LANGUAGE', 'en')
    submitted = []

    def send(url, *, headers, json, timeout):
        assert url == 'https://graph.facebook.com/v25.0/123/messages'
        assert headers == {'Authorization': 'Bearer test-token'}
        submitted.append(json)
        return httpx.Response(200, request=httpx.Request('POST', url), json={'messages': [{'id': 'wamid.test'}]})

    monkeypatch.setattr(main.whatsapp.httpx, 'post', send)
    cid = create(client)
    assert pay(client, cid)[0].status_code == 200
    response, payload = order(client, cid, 4000)
    assert response.status_code == 200
    assert client.post('/api/orders', headers=H, json=payload).json()['id'] == response.json()['id']
    assert len(submitted) == 2
    assert submitted[1]['to'] == '12025550123'
    assert submitted[1]['template']['name'] == 'ahaa_order_update'
    parameters = submitted[1]['template']['components'][0]['parameters']
    assert [item['text'] for item in parameters] == ['Test Customer', 'Biryani x 1', '$40.00', '$200.00']
    assert client.get('/api/data').json()['events'][0]['whatsapp_status'] == 'submitted'
    assert client.patch(f'/api/customers/{cid}', headers=H, json={
        'name': 'Test Customer', 'email': 'test@example.com', 'phone': '+12025550123', 'consent': False,
    }).status_code == 200
    assert order(client, cid, 1000)[0].status_code == 200
    assert len(submitted) == 2


def test_refunds_are_manual_bounded_and_idempotent(client):
    cid=create(client)
    payment=pay(client,cid)[0].json()
    order(client,cid,4000)
    body={'key':str(uuid.uuid4()),'customer_id':cid,'payment_id':payment['id'],'cash':10000,'credit':12000,'reason':'Customer request','method':'Cash'}
    r=client.post('/api/refunds',headers=H,json=body)
    assert r.status_code==200,r.text
    assert r.json()['balance']==8000 and r.json()['cash']==-10000
    assert client.post('/api/refunds',headers=H,json=body).json()['id']==r.json()['id']
    body['key']=str(uuid.uuid4());body['cash']=10001
    assert client.post('/api/refunds',headers=H,json=body).status_code==400
    body['cash']=5000;body['credit']=8001
    assert client.post('/api/refunds',headers=H,json=body).status_code==400
    body['credit']=5000
    assert client.post('/api/refunds',headers=H,json=body).json()['balance']==3000


def test_reversal_once_and_zero_reactivation(client):
    cid=create(client)
    pay(client,cid)
    event=order(client,cid,24000)[0].json()
    body={'key':str(uuid.uuid4()),'customer_id':cid,'order_id':event['id'],'reason':'Wrong order'}
    assert client.post('/api/reversals',headers=H,json=body).json()['balance']==24000
    assert client.post('/api/reversals',headers=H,json=body).json()['balance']==24000
    body['key']=str(uuid.uuid4())
    assert client.post('/api/reversals',headers=H,json=body).status_code==409


def test_concurrent_orders_cannot_overspend(client):
    cid=create(client)
    pay(client,cid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:order(client,cid,20000)[0].status_code,range(2)))
    assert sorted(results)==[200,400]
    assert client.get('/api/data').json()['customers'][0]['balance']==4000


def test_snapshot_and_csv(client):
    cid=create(client)
    pay(client,cid)
    order(client,cid,4000)
    order(client,cid,2500)
    data=client.get('/api/data').json()
    assert data['events'][1]['balance']==20000
    csv=client.get('/api/export')
    assert csv.status_code==200 and '200.00' in csv.text


def test_receipts_stay_in_app_even_with_legacy_live_setting(client, monkeypatch):
    monkeypatch.setenv('WHATSAPP_MODE', 'live')
    cid = create(client)
    pay(client, cid)
    data = client.get('/api/data').json()
    assert data['events'][0]['balance'] == 24000
    assert 'notifications' not in data
    assert client.post('/api/notifications/1/retry', headers=H).status_code == 404


def test_validation_never_echoes_password(client):
    response = client.post('/api/login', headers=H, json={
        'email': 'owner@example.com', 'password': 'shortsecret',
    })
    assert response.status_code == 422
    assert 'shortsecret' not in response.text


def test_login_rate_limit(client):
    for _ in range(8):
        assert client.post('/api/login',headers=H,json={'email':'owner@example.com','password':'wrong-password-long'}).status_code==401
    assert client.post('/api/login',headers=H,json={'email':'owner@example.com','password':'Secure-kitchen-2026'}).status_code==429
