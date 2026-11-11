import hashlib
import hmac
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main

H = {'X-Ahaa-Request': '1'}
SECRET = 'test-app-secret'
PHONE = '+12025550123'


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = {
        'META_WHATSAPP_ENABLED': 'true',
        'META_GRAPH_API_VERSION': 'v25.0',
        'META_WHATSAPP_PHONE_NUMBER_ID': '123',
        'META_WHATSAPP_ACCESS_TOKEN': 'test-token',
        'META_WHATSAPP_TEMPLATE_LANGUAGE': 'en',
        'META_APP_SECRET': SECRET,
        'META_WHATSAPP_VERIFY_TOKEN': 'test-verify',
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(main, 'DB', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setattr(main, 'SUPABASE_DATABASE_URL', '')
    sent = []
    replies = []

    def post(url, *, headers, json, timeout):
        sent.append(json)
        if replies:
            return replies.pop(0)(url)
        return httpx.Response(200, request=httpx.Request('POST', url), json={'messages': [{'id': f'wamid.{len(sent)}'}]})

    monkeypatch.setattr(main.whatsapp.httpx, 'post', post)
    with TestClient(main.app) as c:
        credentials = {'email': 'owner@example.com', 'password': 'Secure-kitchen-2026'}
        assert c.post('/api/setup', json=credentials, headers=H).status_code == 200
        assert c.post('/api/login', json=credentials, headers=H).status_code == 200
        c.sent, c.replies = sent, replies
        yield c


def add_customer(c, consent=True, name='Priya'):
    r = c.post('/api/customers', headers=H, json={'name': name, 'email': 'p@example.com', 'phone': PHONE, 'consent': consent})
    assert r.status_code == 200, r.text
    return r.json()['id']


def pay(c, cid):
    r = c.post('/api/enrollments', headers=H, json={'key': str(uuid.uuid4()), 'customer_id': cid, 'method': 'Cash'})
    assert r.status_code == 200, r.text
    return r.json()


def order(c, cid, total):
    r = c.post('/api/orders', headers=H, json={'key': str(uuid.uuid4()), 'customer_id': cid,
                                                'items': [{'name': 'Chicken Biryani', 'quantity': 2, 'price': total // 2}]})
    assert r.status_code == 200, r.text
    return r.json()


def templates(c):
    return [m['template']['name'] for m in c.sent]


def values(message):
    return [p['text'] for p in message['template']['components'][0]['parameters']]


def webhook(c, payload, secret=SECRET):
    raw = json.dumps(payload).encode()
    signature = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return c.post('/api/webhooks/meta', content=raw, headers={'X-Hub-Signature-256': signature, 'Content-Type': 'application/json'})


def change(value):
    return {'entry': [{'changes': [{'value': {'metadata': {'phone_number_id': '123'}, **value}}]}]}


def reply(text):
    return change({'messages': [{'from': PHONE.lstrip('+'), 'text': {'body': text}}]})


def test_payment_confirmation_uses_template_values(client):
    pay(client, add_customer(client))
    message = client.sent[0]
    assert message['template']['name'] == 'ahaa_payment_confirmation'
    assert message['template']['language'] == {'code': 'en'}
    assert values(message) == ['Priya', '$200.00', '$240.00', '$240.00']


def test_order_update_values(client):
    cid = add_customer(client)
    pay(client, cid)
    order(client, cid, 4000)
    assert templates(client)[-1] == 'ahaa_order_update'
    assert values(client.sent[-1]) == ['Priya', 'Chicken Biryani x 2', '$40.00', '$200.00']


def test_low_balance_alert_once_when_crossing_twenty_dollars(client):
    cid = add_customer(client)
    pay(client, cid)
    order(client, cid, 20000)          # $240 -> $40, no alert
    assert 'ahaa_low_balance' not in templates(client)
    order(client, cid, 2000)           # $40 -> $20, crosses
    assert templates(client)[-1] == 'ahaa_low_balance'
    assert values(client.sent[-1]) == ['Priya', '$20.00']
    order(client, cid, 1000)           # $20 -> $10, already below
    assert templates(client).count('ahaa_low_balance') == 1


def test_low_balance_alert_rearms_after_new_payment(client):
    cid = add_customer(client)
    pay(client, cid)
    order(client, cid, 22000)          # $240 -> $20
    order(client, cid, 2000)           # $20 -> $0
    pay(client, cid)                   # back to $240
    order(client, cid, 22000)          # crosses again
    assert templates(client).count('ahaa_low_balance') == 2


def test_no_messages_without_consent(client):
    cid = add_customer(client, consent=False)
    pay(client, cid)
    order(client, cid, 4000)
    assert client.sent == []


def test_webhook_verification(client):
    ok = client.get('/api/webhooks/meta', params={'hub.mode': 'subscribe', 'hub.verify_token': 'test-verify', 'hub.challenge': '42'})
    assert ok.status_code == 200 and ok.text == '42'
    bad = client.get('/api/webhooks/meta', params={'hub.mode': 'subscribe', 'hub.verify_token': 'wrong', 'hub.challenge': '42'})
    assert bad.status_code == 403


def test_webhook_rejects_bad_signature(client):
    add_customer(client)
    assert webhook(client, reply('STOP'), secret='wrong').status_code == 403
    assert client.get('/api/data').json()['customers'][0]['consent'] == 1


def test_stop_reply_blocks_further_messages(client):
    cid = add_customer(client)
    pay(client, cid)
    assert webhook(client, reply('stop')).status_code == 200
    assert client.get('/api/data').json()['customers'][0]['consent'] == 0
    count = len(client.sent)
    order(client, cid, 4000)
    assert len(client.sent) == count


def test_delivery_status_updates(client):
    pay(client, add_customer(client))
    assert webhook(client, change({'statuses': [{'id': 'wamid.1', 'status': 'delivered'}]})).status_code == 200
    event = client.get('/api/data').json()['events'][0]
    assert event['whatsapp_status'] == 'delivered' and event['whatsapp_error'] is None


def test_rejected_send_records_meta_reason(client):
    client.replies.append(lambda url: httpx.Response(400, request=httpx.Request('POST', url), json={'error': {
        'message': '(#132001) Template name does not exist in the translation', 'code': 132001,
        'error_data': {'details': 'template name (ahaa_payment_confirmation) does not exist in en'}}}))
    pay(client, add_customer(client))
    event = client.get('/api/data').json()['events'][0]
    assert event['whatsapp_status'] == 'failed'
    assert event['whatsapp_error'].startswith('132001: ')
    assert 'does not exist in en' in event['whatsapp_error']
    assert 'test-token' not in json.dumps(event)


def test_failed_delivery_webhook_records_reason(client):
    pay(client, add_customer(client))
    payload = change({'statuses': [{'id': 'wamid.1', 'status': 'failed', 'errors': [{
        'code': 131026, 'title': 'Message undeliverable', 'error_data': {'details': 'Recipient is not on WhatsApp'}}]}]})
    assert webhook(client, payload).status_code == 200
    event = client.get('/api/data').json()['events'][0]
    assert event['whatsapp_status'] == 'failed'
    assert event['whatsapp_error'] == '131026: Message undeliverable (Recipient is not on WhatsApp)'


def test_delete_customer_removes_records_and_contact_details(client):
    cid = add_customer(client)
    pay(client, cid)
    order(client, cid, 24000)          # balance $0
    client.patch(f'/api/customers/{cid}', headers=H, json={'name': 'Priya', 'email': 'new@example.com', 'phone': PHONE, 'consent': True})
    delete = lambda name: client.request('DELETE', f'/api/customers/{cid}', headers=H, json={'confirm_name': name})
    assert delete('Someone else').status_code == 400
    r = delete('priya')
    assert r.status_code == 200 and r.json()['records_deleted'] == 2
    data = client.get('/api/data').json()
    assert data['customers'] == [] and data['events'] == []
    with main.database() as db:
        for table in ('grants', 'events', 'requests', 'meta_notifications'):
            assert db.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n'] == 0
        audit = ' '.join(row['details'] for row in db.execute('SELECT details FROM audit'))
    assert 'new@example.com' not in audit and PHONE not in audit
    assert client.get('/api/export').text.count('\n') == 1


def test_delete_requires_zero_balance(client):
    cid = add_customer(client)
    pay(client, cid)
    r = client.request('DELETE', f'/api/customers/{cid}', headers=H, json={'confirm_name': 'Priya'})
    assert r.status_code == 409 and '$240.00' in r.json()['detail']
    assert len(client.get('/api/data').json()['customers']) == 1


def test_delete_customer_with_legacy_receipt(client):
    cid = add_customer(client)
    pay(client, cid)
    order(client, cid, 24000)
    with main.database(True) as db:
        db.execute('CREATE TABLE whatsapp_receipts(event_id INTEGER PRIMARY KEY REFERENCES events(id), phone TEXT)')
        event = db.execute("SELECT id FROM events WHERE customer_id=? AND kind='order'", (cid,)).fetchone()
        db.execute('INSERT INTO whatsapp_receipts(event_id,phone) VALUES(?,?)', (event['id'], PHONE))
    response = client.request('DELETE', f'/api/customers/{cid}', headers=H, json={'confirm_name': 'Priya'})
    assert response.status_code == 200
    with main.database() as db:
        assert db.execute('SELECT COUNT(*) AS n FROM whatsapp_receipts').fetchone()['n'] == 0


def test_delete_requires_owner_and_request_header(client):
    cid = add_customer(client)
    assert client.request('DELETE', f'/api/customers/{cid}', json={'confirm_name': 'Priya'}).status_code == 403
    with TestClient(main.app) as outsider:
        assert outsider.request('DELETE', f'/api/customers/{cid}', headers=H, json={'confirm_name': 'Priya'}).status_code == 401


@pytest.mark.parametrize('entered,saved', [
    ('9258582516', '+19258582516'),
    ('(925) 858-2516', '+19258582516'),
    ('925 858 2516', '+19258582516'),
    ('19258582516', '+19258582516'),
    ('+1 925-858-2516', '+19258582516'),
    ('+919923169931', '+919923169931'),
])
def test_phone_without_country_code_gets_plus_one(client, entered, saved):
    r = client.post('/api/customers', headers=H, json={'name': 'Venkat', 'email': 'v@example.com', 'phone': entered, 'consent': True})
    assert r.status_code == 200, r.text
    assert client.get('/api/data').json()['customers'][0]['phone'] == saved


@pytest.mark.parametrize('entered', ['858-2516', '0258582516123', 'abc', '29258582516'])
def test_invalid_phone_rejected(client, entered):
    r = client.post('/api/customers', headers=H, json={'name': 'Venkat', 'email': 'v@example.com', 'phone': entered, 'consent': True})
    assert r.status_code == 422


def test_same_number_with_and_without_plus_one_is_one_customer(client):
    add_customer(client)
    r = client.post('/api/customers', headers=H, json={'name': 'Again', 'email': 'a@example.com', 'phone': '2025550123', 'consent': True})
    assert r.status_code == 409


def test_order_items_show_quantity_only_above_one(client):
    cid = add_customer(client)
    pay(client, cid)
    r = client.post('/api/orders', headers=H, json={'key': str(uuid.uuid4()), 'customer_id': cid, 'items': [
        {'name': 'Chicken Biriyani - 2', 'quantity': 1, 'price': 2700},
        {'name': 'Naan', 'quantity': 3, 'price': 300}]})
    assert r.status_code == 200, r.text
    assert values(client.sent[-1])[1] == 'Chicken Biriyani - 2, Naan x 3'
