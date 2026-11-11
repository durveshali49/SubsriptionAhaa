"""Submit saved order receipts through Meta's WhatsApp Cloud API."""
import asyncio
import json
import logging
import os
import re
import time

import httpx


def configuration():
    version = os.getenv('META_GRAPH_API_VERSION', '')
    sender = os.getenv('META_WHATSAPP_PHONE_NUMBER_ID', '')
    token = os.getenv('META_WHATSAPP_ACCESS_TOKEN', '')
    if (os.getenv('META_WHATSAPP_ENABLED', 'false').lower() == 'true'
            and re.fullmatch(r'v\d+\.\d+', version)
            and sender.isascii() and sender.isdigit() and token):
        return version, sender, token
    return None


def failure_reason(error):
    # Meta error objects carry a code, a short title or message and optional details.
    if not isinstance(error, dict):
        return None
    code = error.get('code')
    text = error.get('message') or error.get('title') or ''
    details = (error.get('error_data') or {}).get('details') or ''
    if details and details not in text:
        text = f'{text} ({details})' if text else details
    reason = f'{code}: {text}' if code and text else str(code or text)
    reason = ' '.join(reason.split())
    return reason[:300] or None


def enqueue(db, event, customer, kind):
    preference = db.execute('SELECT opted_out FROM whatsapp_preferences WHERE phone=?', (customer['phone'],)).fetchone()
    if not customer['consent'] or (preference and preference['opted_out']) or not configuration():
        return False
    db.execute(
        "INSERT INTO meta_notifications(event_id,kind,phone,state) VALUES(?,?,?,'queued')",
        (event['id'], kind, customer['phone']),
    )
    return True


def submit(job, config):
    version, sender, token = config
    name = ' '.join(job['customer_name'].split())
    money = lambda value: f"${value / 100:.2f}"
    if job['kind'] == 'payment':
        template = 'ahaa_payment_confirmation'
        values = [name, money(job['cash']), money(job['delta']), money(job['balance'])]
    elif job['kind'] == 'low_balance':
        template = 'ahaa_low_balance'
        values = [name, money(job['balance'])]
    else:
        template = 'ahaa_order_update'
        items = json.loads(job['details'])['items']
        summary = ', '.join(f"{' '.join(item['name'].split())} x {item['quantity']}" for item in items)
        values = [name, summary, money(-job['delta']), money(job['balance'])]
        # Never truncate the customer's itemized receipt to fit a template.
        if len(summary) > 700:
            return 'review', None, 'Food list is too long for one WhatsApp message. Nothing was sent.'
    payload = {
        'messaging_product': 'whatsapp',
        'to': job['phone'].lstrip('+'),
        'type': 'template',
        'template': {
            'name': template,
            'language': {'code': os.getenv('META_WHATSAPP_TEMPLATE_LANGUAGE', 'en')},
            'components': [{'type': 'body', 'parameters': [
                {'type': 'text', 'text': value} for value in values
            ]}],
        },
    }
    try:
        response = httpx.post(
            f'https://graph.facebook.com/{version}/{sender}/messages',
            headers={'Authorization': f'Bearer {token}'}, json=payload, timeout=10,
        )
        if 400 <= response.status_code < 500:
            try:
                reason = failure_reason(response.json().get('error'))
            except (ValueError, AttributeError):
                reason = None
            return 'failed', None, reason or f'Meta rejected the message (HTTP {response.status_code}).'
        response.raise_for_status()
        return 'submitted', response.json()['messages'][0]['id'], None
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        # An ambiguous result needs review before another send.
        return 'review', None, 'No confirmed answer from Meta. Check WhatsApp Manager before sending again.'


def process(database, event_id=None):
    config = configuration()
    if not config:
        return
    try:
        with database(True) as db:
            db.execute("UPDATE meta_notifications SET state='review' WHERE state='sending' AND started<?", (time.time() - 120,))
            query = """SELECT w.*, e.delta, e.cash, e.balance, e.details, c.name AS customer_name,
                              c.consent, c.phone AS current_phone
                       FROM meta_notifications w JOIN events e ON e.id=w.event_id
                       JOIN customers c ON c.id=e.customer_id WHERE w.state='queued'"""
            parameters = ()
            if event_id is not None:
                query += ' AND w.event_id=?'
                parameters = (event_id,)
            job = db.execute(query + " ORDER BY w.event_id,CASE WHEN w.kind='low_balance' THEN 1 ELSE 0 END LIMIT 1", parameters).fetchone()
            if not job:
                return
            preference = db.execute('SELECT opted_out FROM whatsapp_preferences WHERE phone=?', (job['phone'],)).fetchone()
            if not job['consent'] or job['phone'] != job['current_phone'] or (preference and preference['opted_out']):
                db.execute("UPDATE meta_notifications SET state='skipped' WHERE event_id=? AND kind=?", (job['event_id'], job['kind']))
                return
            db.execute("UPDATE meta_notifications SET state='sending',started=? WHERE event_id=? AND kind=?", (time.time(), job['event_id'], job['kind']))
        state, provider_id, error = submit(job, config)
        with database(True) as db:
            if provider_id:
                update = db.execute('SELECT state,error FROM meta_delivery_updates WHERE provider_id=?', (provider_id,)).fetchone()
                if update:
                    state = update['state']
                    error = update['error'] or error
            db.execute("UPDATE meta_notifications SET state=?,provider_id=?,error=? WHERE event_id=? AND kind=? AND state IN ('sending','review')",
                       (state, provider_id, error, job['event_id'], job['kind']))
    except Exception:
        logging.getLogger(__name__).warning('WhatsApp receipt processing could not finish. Check the receipt status.')


async def recover_pending(database):
    while True:
        await asyncio.to_thread(process, database)
        await asyncio.sleep(30)


def process_event(database, event_id):
    # An order can queue both its receipt and one threshold alert.
    process(database, event_id)
    process(database, event_id)


def receive(database, payload):
    sender = os.getenv('META_WHATSAPP_PHONE_NUMBER_ID', '')
    with database(True) as db:
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                if value.get('metadata', {}).get('phone_number_id') != sender:
                    continue
                for message in value.get('messages', []):
                    command = message.get('text', {}).get('body', '').strip().upper()
                    if command not in {'STOP', 'STOPALL', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT', 'REVOKE', 'OPT OUT'}:
                        continue
                    phone = '+' + message['from'].lstrip('+')
                    db.execute(
                        'INSERT INTO whatsapp_preferences(phone,opted_out,updated) VALUES(?,1,?) '
                        'ON CONFLICT(phone) DO UPDATE SET opted_out=1,updated=excluded.updated',
                        (phone, time.time()),
                    )
                    db.execute('UPDATE customers SET consent=0 WHERE phone=?', (phone,))
                    db.execute("UPDATE meta_notifications SET state='skipped' WHERE phone=? AND state='queued'", (phone,))
                ranks = {'submitted': 0, 'sent': 1, 'failed': 2, 'delivered': 3, 'read': 4}
                for status in value.get('statuses', []):
                    state = status.get('status')
                    if state not in ranks:
                        continue
                    row = db.execute('SELECT state FROM meta_delivery_updates WHERE provider_id=?', (status['id'],)).fetchone()
                    if not row or ranks.get(row['state'], -1) < ranks[state]:
                        errors = status.get('errors') or []
                        error = failure_reason(errors[0]) if state == 'failed' and errors else None
                        db.execute(
                            'INSERT INTO meta_delivery_updates(provider_id,state,error) VALUES(?,?,?) '
                            'ON CONFLICT(provider_id) DO UPDATE SET state=excluded.state,error=excluded.error',
                            (status['id'], state, error),
                        )
                        db.execute('UPDATE meta_notifications SET state=?,error=? WHERE provider_id=?', (state, error, status['id']))
