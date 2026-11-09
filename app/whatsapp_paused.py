"""Paused WhatsApp implementation. Reference only."""

# @app.post('/api/notifications/{nid}/retry')
# def retry(nid: int, auth: Auth):
#     with database(True) as c:
#         n = c.execute('SELECT n.*,c.phone AS current_phone,c.consent FROM notifications n JOIN events e ON e.id=n.event_id JOIN customers c ON c.id=e.customer_id WHERE n.id=?', (nid,)).fetchone()
#         if not n:
#             raise HTTPException(404, 'Message not found.')
#         if n['state'] != 'failed':
#             raise HTTPException(409, 'Only confirmed failed messages can be retried. Review ambiguous sends with the provider.')
#         if not n['consent'] or n['phone'] != n['current_phone']:
#             raise HTTPException(400, 'Verify the recipient and notification permission first.')
#         c.execute("UPDATE notifications SET state='queued',error=NULL,provider_id=NULL,updated=? WHERE id=?", (now(), nid))
#         audit(c, 'message_retry', {'notification_id': nid})
#     return {'ok': True}
#
#
# def live_ready():
#     return os.getenv('WHATSAPP_MODE') == 'live' and all(os.getenv(k) for k in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_WHATSAPP_FROM', 'TWILIO_STATUS_CALLBACK_URL', 'TWILIO_PAYMENT_CONTENT_SID', 'TWILIO_ORDER_CONTENT_SID', 'TWILIO_REFUND_CONTENT_SID', 'TWILIO_CORRECTION_CONTENT_SID'))
#
#
# def submit(n):
#     from twilio.rest import Client
#     from zoneinfo import ZoneInfo
#     p = json.loads(n['payload'])
#     details = p['details']
#     stamp = datetime.fromisoformat(p['created']).astimezone(ZoneInfo('America/Chicago')).strftime('%b %d, %Y %I:%M %p %Z')
#     money = lambda x: f'${x/100:.2f}'
#     if p['kind'] == 'order':
#         summary = '; '.join(f"{i['name']} x{i['quantity']} {money(i['price']*i['quantity'])}" for i in details['items'])
#         if len(summary) > 700 or '\n' in summary or '\t' in summary:
#             raise ValueError('Item summary exceeds supported text template format. Send an approved itemized document before retrying.')
#         template = 'ORDER'
#         variables = [p['name'], p['reference'], summary, money(-p['delta']), money(p['balance']), stamp]
#     elif p['kind'] == 'payment':
#         template = 'PAYMENT'
#         variables = [p['name'], p['reference'], money(p['cash']), '$40.00', money(p['delta']), money(p['balance']), stamp]
#     elif p['kind'] == 'refund':
#         template = 'REFUND'
#         variables = [p['name'], p['reference'], money(-p['cash']), money(-p['delta']), money(p['balance']), stamp, p.get('original_reference', '')]
#     else:
#         template = 'CORRECTION'
#         variables = [p['name'], p['reference'], money(p['delta']), money(p['balance']), stamp, p.get('original_reference', '')]
#     client = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])
#     return client.messages.create(from_=os.environ['TWILIO_WHATSAPP_FROM'], to='whatsapp:'+n['phone'], content_sid=os.environ[f'TWILIO_{template}_CONTENT_SID'], content_variables=json.dumps({str(i+1): v for i, v in enumerate(variables)}), status_callback=os.environ['TWILIO_STATUS_CALLBACK_URL']).sid
#
#
# async def worker():
#     while True:
#         try:
#             if live_ready():
#                 await asyncio.to_thread(process_one)
#         except Exception:
#             # Preserve the job and keep the worker alive; never log customer payloads.
#             pass
#         await asyncio.sleep(3)
#
#
# def process_one():
#     with database(True) as c:
#         n = c.execute("SELECT n.*,c.phone AS current_phone,c.consent FROM notifications n JOIN events e ON e.id=n.event_id JOIN customers c ON c.id=e.customer_id WHERE n.state='queued' ORDER BY n.id LIMIT 1").fetchone()
#         if not n:
#             return
#         n = dict(n)
#         if not n['consent'] or n['phone'] != n['current_phone']:
#             c.execute("UPDATE notifications SET state='skipped',error='Recipient or consent changed.',updated=? WHERE id=?", (now(), n['id']))
#             return
#         c.execute("UPDATE notifications SET state='sending',attempts=attempts+1,updated=? WHERE id=?", (now(), n['id']))
#     try:
#         sid = submit(n)
#         with database(True) as c:
#             c.execute("UPDATE notifications SET provider_id=?,state='sent',error=NULL,updated=? WHERE id=?", (sid, now(), n['id']))
#             for callback in c.execute('SELECT * FROM delivery_callbacks WHERE provider_id=? ORDER BY id', (sid,)).fetchall():
#                 update_delivery(c, n['id'], callback['state'], callback['error'])
#     except Exception as exc:
#         from twilio.base.exceptions import TwilioRestException
#         state = 'failed' if isinstance(exc, (ValueError, TwilioRestException)) else 'review'
#         error = str(exc) if isinstance(exc, ValueError) else ('Provider rejected message. Review sender/template/billing configuration.' if state == 'failed' else 'Delivery outcome unknown. Check provider before resending.')
#         with database(True) as c:
#             c.execute('UPDATE notifications SET state=?,error=?,updated=? WHERE id=?', (state, error, now(), n['id']))
#
#
# def update_delivery(c, notification_id, state, error):
#     ranks = {'queued': 0, 'sending': 1, 'sent': 2, 'delivered': 3, 'read': 4}
#     n = c.execute('SELECT * FROM notifications WHERE id=?', (notification_id,)).fetchone()
#     if state in ('failed', 'undelivered') and n['state'] not in ('delivered', 'read'):
#         c.execute("UPDATE notifications SET state='failed',error=?,updated=? WHERE id=?", ('Provider delivery error '+(error or ''), now(), n['id']))
#     elif state in ranks and ranks[state] > ranks.get(n['state'], -1):
#         c.execute('UPDATE notifications SET state=?,error=NULL,updated=? WHERE id=?', (state, now(), n['id']))
#
#
# @app.post('/api/webhooks/twilio/status')
# async def callback(request: Request):
#     from urllib.parse import parse_qsl
#     from twilio.request_validator import RequestValidator
#     params = dict(parse_qsl((await request.body()).decode()))
#     url = os.getenv('TWILIO_STATUS_CALLBACK_URL', '')
#     token = os.getenv('TWILIO_AUTH_TOKEN', '')
#     if not token or not url or not RequestValidator(token).validate(url, params, request.headers.get('X-Twilio-Signature', '')):
#         raise HTTPException(403, 'Invalid signature.')
#     state = params.get('MessageStatus')
#     sid = params.get('MessageSid', '')
#     if not sid or state not in ('queued', 'sending', 'sent', 'delivered', 'read', 'failed', 'undelivered'):
#         raise HTTPException(400, 'Invalid delivery update.')
#     with database(True) as c:
#         c.execute('INSERT INTO delivery_callbacks(provider_id,state,error,created) VALUES(?,?,?,?)', (sid, state, params.get('ErrorCode'), now()))
#         n = c.execute('SELECT id FROM notifications WHERE provider_id=?', (sid,)).fetchone()
#         if n:
#             update_delivery(c, n['id'], state, params.get('ErrorCode'))
#     return Response(status_code=204)
#
#
