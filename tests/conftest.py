"""Test-safe settings, applied before the app loads the local .env file.

load_dotenv never overrides variables that are already set, so these values
keep tests away from real hosts, databases and WhatsApp credentials.
"""
import os

os.environ.update({
    'ALLOWED_HOSTS': 'testserver',
    'SUPABASE_DATABASE_URL': '',
    'COOKIE_SECURE': 'false',
    'META_WHATSAPP_ENABLED': 'false',
    'META_GRAPH_API_VERSION': 'v25.0',
    'META_WHATSAPP_PHONE_NUMBER_ID': '',
    'META_WHATSAPP_TEMPLATE_LANGUAGE': 'en',
    'META_WHATSAPP_ACCESS_TOKEN': '',
    'META_APP_SECRET': '',
    'META_WHATSAPP_VERIFY_TOKEN': '',
})
