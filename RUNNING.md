# Run Ahaa Kitchen Food Credit

Install Python 3.12 or later. From the project folder in PowerShell:

```powershell
python -m venv .venv-app
.\.venv-app\Scripts\python.exe -m pip install -r requirements.lock.txt
.\run.ps1
```

Open http://127.0.0.1:8000. A fresh database asks you to create the owner login. Existing records use the existing owner login.

## Everyday use

1. **Add customer** and enter their contact details.
2. **Record payment** after receiving $200 to add $240 in food credit.
3. **Record food** with the food names and final bill, including tax. The app shows the deduction and remaining balance before saving.

The home screen includes customer search, recent receipts, and business-day totals in Frisco time. Open **History → Details** to see a payment, food bill, refund, or correction. Use **Customer details & refunds** for refunds.

## Enable Meta WhatsApp notifications

Use Meta Cloud API directly. Set these private server variables in the ignored local .env or Render Environment:

- META_WHATSAPP_ENABLED=false (enable after templates and test recipient are ready)
- META_GRAPH_API_VERSION=v25.0
- META_WHATSAPP_PHONE_NUMBER_ID (production sender ID)
- META_WHATSAPP_TEMPLATE_LANGUAGE=en
- META_WHATSAPP_ACCESS_TOKEN
- META_APP_SECRET (for webhook signatures)
- META_WHATSAPP_VERIFY_TOKEN (random private verification token)

The HTTPS callback is /api/webhooks/meta. Configure verification, subscribe to messages, and publish the Meta app as required for production callbacks.

Approved templates in the production account must match these body parameters:

| Template | Parameters in order |
| --- | --- |
| ahaa_payment_confirmation | customer name, payment amount, credit added, available credit |
| ahaa_order_update | customer name, full food item list, order total, remaining credit |
| ahaa_low_balance | customer name, remaining credit |

Messages queue within the payment/order transaction. Repeated identical saves do not duplicate notifications. Low balance alerts occur when an order takes credit from above $20 to $20 or below. Credit above $20 enables the next crossing.

Owner consent changes are recorded in the audit trail. Signed inbound STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT, REVOKE, and OPT OUT disable notifications by phone and cancel queued messages. Resubscription after STOP requires operational review. START is not supported. An already in-flight message may complete after STOP.

Record details displays payment/order message state. Low balance state is stored separately in meta_notifications. Webhooks record sent, delivered, read and failed. Submitted means accepted by Meta, not delivered.

Ambiguous requests are marked for review rather than automatically resent. Item lists exceeding the conservative 700-character limit are also marked for review and retained in full in the application. Automatic long receipts require an approved document/media approach.

Test payment, order, threshold alert, signed webhooks, and STOP with an owner-controlled opted-in phone before enabling production sending. No retention purge or customer deletion automation is implemented.

## Connect Supabase

This FastAPI app connects to Postgres on the server. The Supabase project URL and publishable key are Data API settings. This app requires a private Postgres connection string.

1. In the Supabase project dashboard, choose **Connect → Session pooler**.
2. Copy the connection URI and replace the password placeholder with the URL-encoded database password. The [Supabase connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres) explains the URI format.
3. Copy `.env.example` to `.env` if a local `.env` does not already exist. Set `SUPABASE_DATABASE_URL` in that file. Enter the credential directly in your editor or hosting provider's secret settings. Use TLS. The app verifies the hostname and certificate against the system trust store. Set `SUPABASE_SSL_ROOT_CERT` to the downloaded Supabase CA certificate path if your project requires it.
4. Stop the existing server. To carry over the local owner and records, run the migration below before starting the app. For a fresh database, start the app and create the owner account on localhost.
5. Run `.\run.ps1`, sign in, and verify the balances and receipts.

Tables live in the private `ahaa_private` schema. The browser calls the owner-only FastAPI endpoints. Server code authenticates the owner, stores password hashes, and uses parameterized queries and transaction locks for balance updates. The schema is unavailable to Supabase browser roles.

### Carry over existing records

With the app stopped and `SUPABASE_DATABASE_URL` configured, run:

```powershell
.\.venv-app\Scripts\python.exe tools.py migrate-supabase
```

An optional path argument selects a different SQLite source. The import requires empty app tables and copies the owner password hash, customers, balances, receipts, submission keys and audit records in one database transaction. Sign in again after importing. The source database is opened read-only. Legacy WhatsApp records and login sessions stay in the source file.

## Backups and owner access

With a blank `SUPABASE_DATABASE_URL`, the app uses `data/ahaa.sqlite3`. Use `tools.py backup` for a consistent SQLite backup, or the Supabase backup tools when connected to Postgres.

With the app stopped, run `.\.venv-app\Scripts\python.exe tools.py reset-password` if you need to reset the owner password. The prompt accepts the new password privately and invalidates existing sessions.

For deployment, create or migrate the owner locally first. Set the deployed hostname in `ALLOWED_HOSTS` and use HTTPS with `COOKIE_SECURE=true`. Keep `.env` and database backups private.
