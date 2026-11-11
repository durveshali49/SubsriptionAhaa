"""Ahaa Kitchen: owner-only prepaid credit records. No payment processing."""
import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from psycopg.errors import UniqueViolation

from app import whatsapp
from app.storage import connect, initialize, delete_legacy_receipts
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, StrictInt, field_validator

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DB = os.getenv('DATABASE_PATH', str(ROOT / 'data' / 'ahaa.sqlite3'))
SUPABASE_DATABASE_URL = os.getenv('SUPABASE_DATABASE_URL', '')
SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
PHONE = re.compile(r'^\+[1-9]\d{7,14}$')


def normalize_phone(value):
    # US numbers can be entered without +1, e.g. 9258582516 or (925) 858-2516.
    raw = value.strip()
    digits = re.sub(r'\D', '', raw)
    if raw.startswith('+'):
        phone = '+' + digits
    elif len(digits) == 10:
        phone = '+1' + digits
    elif len(digits) == 11 and digits.startswith('1'):
        phone = '+' + digits
    else:
        phone = ''
    if not PHONE.fullmatch(phone):
        raise ValueError('Enter a 10-digit US phone number, or start with + and the country code.')
    return phone


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def database(write=False):
    with connect(DB, SUPABASE_DATABASE_URL, write=write) as connection:
        yield connection


def init_db():
    initialize(DB, SUPABASE_DATABASE_URL)


def audit(c, action, details):
    c.execute('INSERT INTO audit(action,details,created) VALUES(?,?,?)', (action, json.dumps(details), now()))


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def owner(request: Request):
    token = request.cookies.get('ahaa_session', '')
    with database() as c:
        row = c.execute('SELECT * FROM sessions WHERE token=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    if not row:
        raise HTTPException(401, 'Please sign in to continue.')


Auth = Annotated[None, Depends(owner)]


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=200)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value.strip()):
            raise ValueError('Enter a valid email address.')
        return value.strip().lower()


class Customer(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=254)
    phone: str
    consent: bool = False
    notes: str = Field(default='', max_length=1000)

    @field_validator('phone')
    @classmethod
    def phone_valid(cls, value):
        return normalize_phone(value)

    @field_validator('name')
    @classmethod
    def name_valid(cls, value):
        if not value.strip():
            raise ValueError('Name is required.')
        return value.strip()

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        return Credentials.valid_email(value)


class Mutation(BaseModel):
    key: str = Field(min_length=16, max_length=100)
    customer_id: StrictInt = Field(gt=0)


class Payment(Mutation):
    amount: StrictInt = 20000
    method: str = Field(min_length=1, max_length=40)
    reference: str = Field(default='', max_length=100)


class Item(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    quantity: StrictInt = Field(ge=1, le=1000)
    price: StrictInt = Field(ge=0, le=1000000)

    @field_validator('name')
    @classmethod
    def item_name(cls, value):
        if not value.strip():
            raise ValueError('Food name is required.')
        return value.strip()


class Order(Mutation):
    items: list[Item] = Field(min_length=1, max_length=30)


class Refund(Mutation):
    payment_id: StrictInt = Field(gt=0)
    cash: StrictInt = Field(gt=0)
    credit: StrictInt = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)
    method: str = Field(min_length=1, max_length=40)
    reference: str = Field(default='', max_length=100)


class Deletion(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=100)


class Reversal(Mutation):
    order_id: StrictInt = Field(gt=0)
    reason: str = Field(min_length=3, max_length=500)


def balance(c, customer_id):
    return c.execute('SELECT COALESCE(SUM(remaining),0) AS total FROM grants WHERE customer_id=?', (customer_id,)).fetchone()['total']


def find_customer(c, cid):
    row = c.execute('SELECT * FROM customers WHERE id=?', (cid,)).fetchone()
    if not row:
        raise HTTPException(404, 'Customer not found.')
    return row


def fingerprint(kind, body):
    return hashlib.sha256((kind + json.dumps(body.model_dump(exclude={'key'}), sort_keys=True)).encode()).hexdigest()


def previous(c, kind, body):
    row = c.execute('SELECT * FROM requests WHERE key=?', (body.key,)).fetchone()
    if row:
        if row['fingerprint'] != fingerprint(kind, body):
            raise HTTPException(409, 'This submission key was already used for different details.')
        return dict(c.execute('SELECT * FROM events WHERE id=?', (row['event_id'],)).fetchone())


def record(c, kind, body, grant_id, delta, cash, details, original=None):
    find_customer(c, body.customer_id)
    stamp = now()
    after = balance(c, body.customer_id)
    eid = c.execute('INSERT INTO events(customer_id,grant_id,kind,cash,delta,balance,details,created,original_id) VALUES(?,?,?,?,?,?,?,?,?) RETURNING id',
        (body.customer_id, grant_id, kind, cash, delta, after, json.dumps(details), stamp, original)).fetchone()['id']
    c.execute('INSERT INTO requests VALUES(?,?,?)', (body.key, fingerprint(kind, body), eid))
    audit(c, kind, {'event_id': eid, 'customer_id': body.customer_id})
    return dict(c.execute('SELECT * FROM events WHERE id=?', (eid,)).fetchone())


@asynccontextmanager
async def lifespan(app):
    init_db()
    worker = asyncio.create_task(whatsapp.recover_pending(database)) if whatsapp.configuration() else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker


app = FastAPI(title='Ahaa Kitchen Credit Records', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(','))


@app.middleware('http')
async def protection(request, call_next):
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.url.path != '/api/webhooks/meta':
        if request.headers.get('X-Ahaa-Request') != '1' or request.headers.get('sec-fetch-site') == 'cross-site':
            return Response('Invalid request origin', status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return Response('Invalid request origin', status_code=403)
    response = await call_next(request)
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, error: RequestValidationError):
    # Validation errors can contain the submitted password in their input field.
    details = [
        {'loc': issue['loc'], 'msg': issue['msg'], 'type': issue['type']}
        for issue in error.errors()
    ]
    return JSONResponse({'detail': details}, status_code=422)


@app.get('/api/webhooks/meta')
def verify_meta(request: Request):
    expected = os.getenv('META_WHATSAPP_VERIFY_TOKEN', '')
    supplied = request.query_params.get('hub.verify_token', '')
    if (not expected or request.query_params.get('hub.mode') != 'subscribe'
            or not secrets.compare_digest(expected, supplied)):
        raise HTTPException(403, 'Verification failed')
    return Response(request.query_params.get('hub.challenge', ''), media_type='text/plain')


@app.post('/api/webhooks/meta')
async def receive_meta(request: Request):
    secret = os.getenv('META_APP_SECRET', '')
    raw = await request.body()
    signature = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not secret or not secrets.compare_digest(signature, request.headers.get('X-Hub-Signature-256', '')):
        raise HTTPException(403, 'Signature verification failed')
    try:
        payload = json.loads(raw)
        whatsapp.receive(database, payload)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(400, 'Invalid webhook payload') from None
    return {'received': True}


@app.api_route('/api/health', methods=['GET', 'HEAD'])
def health():
    # Uptime monitors and Render health checks. No database or login needed.
    return {'status': 'ok'}


@app.get('/')
def index():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/api/session')
def session(request: Request):
    with database() as c:
        exists = c.execute('SELECT email FROM owner').fetchone()
    try:
        owner(request)
        signed_in = True
    except HTTPException:
        signed_in = False
    return {'setup': not bool(exists), 'authenticated': signed_in, 'email': exists['email'] if exists and signed_in else None}


@app.post('/api/setup')
def setup(body: Credentials, request: Request):
    if (
        request.client.host not in ('127.0.0.1', '::1', 'testclient')
        or request.url.hostname not in ('localhost', '127.0.0.1', '::1', 'testserver')
    ):
        raise HTTPException(403, 'Create the owner account locally before deployment.')
    with database(True) as c:
        if c.execute('SELECT 1 FROM owner').fetchone():
            raise HTTPException(409, 'Owner account already exists.')
        salt = secrets.token_hex(16)
        c.execute('INSERT INTO owner VALUES(1,?,?,?)', (body.email, salt, password_hash(body.password, salt)))
        audit(c, 'owner_setup', {})
    return {'ok': True}


@app.post('/api/login')
def login(body: Credentials, request: Request, response: Response):
    ip = request.client.host
    with database(True) as c:
        attempt = c.execute('SELECT * FROM attempts WHERE ip=?', (ip,)).fetchone()
        if attempt and time.time() - attempt['since'] < 900 and attempt['count'] >= 8:
            raise HTTPException(429, 'Too many attempts. Try again in 15 minutes.')
        row = c.execute('SELECT * FROM owner').fetchone()
        valid = row and hmac.compare_digest(password_hash(body.password, row['salt']), row['password']) and body.email == row['email']
        if not valid:
            count = attempt['count'] + 1 if attempt and time.time() - attempt['since'] < 900 else 1
            since = attempt['since'] if count > 1 else time.time()
            c.execute('INSERT INTO attempts VALUES(?,?,?) ON CONFLICT(ip) DO UPDATE SET count=excluded.count, since=excluded.since', (ip, count, since))
        else:
            c.execute('DELETE FROM attempts WHERE ip=?', (ip,))
            c.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            token = secrets.token_urlsafe(32)
            c.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), time.time()+43200))
    if not valid:
        raise HTTPException(401, 'Email or password is incorrect.')
    response.set_cookie('ahaa_session', token, httponly=True, secure=SECURE, samesite='strict', max_age=43200)
    return {'ok': True}


@app.post('/api/logout')
def logout(request: Request, response: Response):
    with database(True) as c:
        c.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(request.cookies.get('ahaa_session', '').encode()).hexdigest(),))
    response.delete_cookie('ahaa_session')
    return {'ok': True}


@app.get('/api/data')
def data(auth: Auth):
    with database() as c:
        customers = [dict(r) | {'balance': balance(c, r['id'])} for r in c.execute('SELECT * FROM customers ORDER BY lower(name), id')]
        events = [dict(r) for r in c.execute(
            'SELECT e.*,c.name,m.state AS whatsapp_status,m.error AS whatsapp_error,l.state AS low_balance_status,l.error AS low_balance_error '
            'FROM events e JOIN customers c ON c.id=e.customer_id '
            "LEFT JOIN meta_notifications m ON m.event_id=e.id AND m.kind=e.kind LEFT JOIN meta_notifications l ON l.event_id=e.id AND l.kind='low_balance' ORDER BY e.id DESC" )]
    for e in events:
        e['details'] = json.loads(e['details'])
    return {'customers': customers, 'events': events}


@app.post('/api/customers')
def create_customer(body: Customer, auth: Auth):
    with database(True) as c:
        try:
            cid = c.execute('INSERT INTO customers(name,email,phone,consent,notes,created) VALUES(?,?,?,?,?,?) RETURNING id', (body.name, body.email, body.phone, int(body.consent), body.notes, now())).fetchone()['id']
        except (sqlite3.IntegrityError, UniqueViolation):
            raise HTTPException(409, 'A customer with this phone number already exists.')
        audit(c, 'customer_created', {'customer_id': cid, 'consent': body.consent})
    return {'id': cid}


@app.patch('/api/customers/{cid}')
def edit_customer(cid: int, body: Customer, auth: Auth):
    with database(True) as c:
        old = find_customer(c, cid)
        consent = int(body.consent) if 'consent' in body.model_fields_set else int(old['consent'] and body.phone == old['phone'])
        try:
            c.execute('UPDATE customers SET name=?,email=?,phone=?,consent=?,notes=? WHERE id=?', (body.name, body.email, body.phone, consent, body.notes, cid))
        except (sqlite3.IntegrityError, UniqueViolation):
            raise HTTPException(409, 'This phone number is already registered.')
        audit(c, 'customer_updated', {'customer_id': cid, 'before': dict(old), 'after': body.model_dump() | {'consent': bool(consent)}})
    return {'ok': True}


@app.delete('/api/customers/{cid}')
def delete_customer(cid: int, body: Deletion, auth: Auth):
    same = lambda value: ' '.join(value.split()).casefold()
    with database(True) as c:
        row = find_customer(c, cid)
        if same(body.confirm_name) != same(row['name']):
            raise HTTPException(400, 'Type the customer name exactly as shown to confirm.')
        remaining = balance(c, cid)
        if remaining:
            raise HTTPException(409, f'This customer still has ${remaining/100:.2f} in food credit. Use it or record a refund before deleting.')
        events = 'SELECT id FROM events WHERE customer_id=?'
        count = c.execute('SELECT COUNT(*) AS n FROM events WHERE customer_id=?', (cid,)).fetchone()['n']
        delete_legacy_receipts(c, cid)
        c.execute(f'DELETE FROM meta_delivery_updates WHERE provider_id IN (SELECT provider_id FROM meta_notifications WHERE event_id IN ({events}))', (cid,))
        c.execute(f'DELETE FROM meta_notifications WHERE event_id IN ({events})', (cid,))
        c.execute(f'DELETE FROM requests WHERE event_id IN ({events})', (cid,))
        # Refunds and reversals point at the customer's original records, so remove them first.
        c.execute('DELETE FROM events WHERE customer_id=? AND original_id IS NOT NULL', (cid,))
        c.execute('DELETE FROM events WHERE customer_id=?', (cid,))
        c.execute('DELETE FROM grants WHERE customer_id=?', (cid,))
        # Audit entries for this customer can hold their old contact details.
        for entry in c.execute('SELECT id,details FROM audit').fetchall():
            try:
                details = json.loads(entry['details'])
            except ValueError:
                continue
            if isinstance(details, dict) and details.get('customer_id') == cid:
                c.execute('DELETE FROM audit WHERE id=?', (entry['id'],))
        # A WhatsApp STOP choice is kept so a re-added number is never messaged against it.
        c.execute('DELETE FROM customers WHERE id=?', (cid,))
        audit(c, 'customer_deleted', {'records_deleted': count})
    return {'ok': True, 'records_deleted': count}


@app.post('/api/enrollments')
def enroll(body: Payment, auth: Auth, background: BackgroundTasks):
    with database(True) as c:
        prior = previous(c, 'payment', body)
        if prior:
            return prior
        customer = find_customer(c, body.customer_id)
        if body.amount != 20000:
            raise HTTPException(400, 'This plan requires a recorded payment of exactly $200.00.')
        if balance(c, body.customer_id) != 0:
            raise HTTPException(409, 'Renewal is available after the existing balance reaches zero.')
        gid = c.execute('INSERT INTO grants(customer_id,remaining,created) VALUES(?,24000,?) RETURNING id', (body.customer_id, now())).fetchone()['id']
        event = record(c, 'payment', body, gid, 24000, 20000, {'method': body.method, 'reference': body.reference, 'bonus': 4000})
        queued = whatsapp.enqueue(c, event, customer, 'payment')
    if queued:
        background.add_task(whatsapp.process_event, database, event['id'])
    return event


@app.post('/api/orders')
def order(body: Order, auth: Auth, background: BackgroundTasks):
    with database(True) as c:
        prior = previous(c, 'order', body)
        if prior:
            return prior
        customer = find_customer(c, body.customer_id)
        total = sum(i.price * i.quantity for i in body.items)
        available = balance(c, body.customer_id)
        if total <= 0:
            raise HTTPException(400, 'Order total must be greater than zero.')
        if total > available:
            raise HTTPException(400, f'Not sufficient balance. Available: ${available/100:.2f}. Order: ${total/100:.2f}.')
        remaining, allocations = total, []
        for grant in c.execute('SELECT * FROM grants WHERE customer_id=? AND remaining>0 ORDER BY id', (body.customer_id,)).fetchall():
            used = min(remaining, grant['remaining'])
            c.execute('UPDATE grants SET remaining=remaining-? WHERE id=?', (used, grant['id']))
            allocations.append({'grant_id': grant['id'], 'amount': used})
            remaining -= used
            if not remaining:
                break
        event = record(c, 'order', body, None, -total, 0, {'items': [i.model_dump() for i in body.items], 'allocations': allocations})
        queued = whatsapp.enqueue(c, event, customer, 'order')
        if available > 2000 and event['balance'] <= 2000:
            whatsapp.enqueue(c, event, customer, 'low_balance')
    if queued:
        background.add_task(whatsapp.process_event, database, event['id'])
    return event


@app.post('/api/refunds')
def refund(body: Refund, auth: Auth):
    with database(True) as c:
        prior = previous(c, 'refund', body)
        if prior:
            return prior
        pay = c.execute("SELECT * FROM events WHERE id=? AND customer_id=? AND kind='payment'", (body.payment_id, body.customer_id)).fetchone()
        if not pay:
            raise HTTPException(404, 'Original payment not found.')
        refunded = c.execute("SELECT COALESCE(SUM(-cash),0) AS total FROM events WHERE original_id=? AND kind='refund'", (pay['id'],)).fetchone()['total']
        grant = c.execute('SELECT * FROM grants WHERE id=?', (pay['grant_id'],)).fetchone()
        if body.cash > pay['cash'] - refunded:
            raise HTTPException(400, 'Refund exceeds the unrefunded original payment.')
        if body.credit > grant['remaining']:
            raise HTTPException(400, 'Credit removal exceeds unspent credit from this payment.')
        c.execute('UPDATE grants SET remaining=remaining-? WHERE id=?', (body.credit, grant['id']))
        return record(c, 'refund', body, grant['id'], -body.credit, -body.cash, {'reason': body.reason, 'method': body.method, 'reference': body.reference}, pay['id'])


@app.post('/api/reversals')
def reverse(body: Reversal, auth: Auth):
    with database(True) as c:
        prior = previous(c, 'reversal', body)
        if prior:
            return prior
        event = c.execute("SELECT * FROM events WHERE id=? AND customer_id=? AND kind='order'", (body.order_id, body.customer_id)).fetchone()
        if not event:
            raise HTTPException(404, 'Order not found.')
        if c.execute("SELECT 1 FROM events WHERE original_id=? AND kind='reversal'", (event['id'],)).fetchone():
            raise HTTPException(409, 'This order has already been reversed.')
        for alloc in json.loads(event['details'])['allocations']:
            c.execute('UPDATE grants SET remaining=remaining+? WHERE id=?', (alloc['amount'], alloc['grant_id']))
        return record(c, 'reversal', body, None, -event['delta'], 0, {'reason': body.reason}, event['id'])


@app.get('/api/export')
def export(auth: Auth):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Reference', 'Customer', 'Type', 'Cash USD', 'Credit movement USD', 'Balance USD', 'UTC date'])
    with database() as c:
        for r in c.execute('SELECT e.*,c.name FROM events e JOIN customers c ON c.id=e.customer_id ORDER BY e.id'):
            safe = "'" + r['name'] if r['name'].startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else r['name']
            writer.writerow([f"AK-{r['id']:06}", safe, r['kind'], f"{r['cash']/100:.2f}", f"{r['delta']/100:.2f}", f"{r['balance']/100:.2f}", r['created']])
    return Response(out.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename=ahaa-records.csv'})


app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
