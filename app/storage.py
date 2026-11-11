"""Server-side SQLite and Supabase Postgres storage."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SCHEMA = Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
TABLES = ('owner', 'sessions', 'attempts', 'customers', 'grants', 'events', 'requests', 'audit', 'meta_notifications', 'whatsapp_preferences', 'meta_delivery_updates')
IDENTITY_TABLES = ('customers', 'grants', 'events', 'audit')
WRITE_LOCK = 21731860721
# Columns added after the first release. Existing databases receive them at startup.
ADDED_COLUMNS = (('meta_notifications', 'error'), ('meta_delivery_updates', 'error'))


def connection_failure_reason(error):
    # Driver errors can contain connection details. Log only fixed messages.
    message = str(error).lower()
    if 'certificate' in message or 'sslrootcert' in message:
        return 'TLS certificate verification failed. Check the Render secret file and SUPABASE_SSL_ROOT_CERT.'
    if error.sqlstate == '28P01' or 'password authentication failed' in message:
        return 'Postgres rejected the password in SUPABASE_DATABASE_URL.'
    if 'tenant or user not found' in message:
        return 'The pooler rejected the tenant or username. Check the Session pooler URL in Supabase.'
    if isinstance(error, psycopg.ProgrammingError):
        return 'The database connection string or a connection option is invalid.'
    if any(hint in message for hint in ('could not translate host', 'failed to resolve host', 'getaddrinfo')):
        return 'The database hostname did not resolve. Check the Session pooler hostname in Supabase.'
    if any(hint in message for hint in ('timeout', 'timed out', 'connection refused', 'unreachable')):
        return 'The database host could not be reached. Check the pooler host, port and network access.'
    return 'The driver did not identify a known cause. Check the pooler URL and Supabase database logs.'


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        # All SQL is authored by the application. Values stay parameterized.
        return self.connection.execute(statement.replace('?', '%s'), parameters)


def delete_legacy_receipts(connection, customer_id):
    """Remove old receipt references when deleting a customer's transactions."""
    if isinstance(connection, PostgresConnection):
        exists = connection.execute(
            "SELECT to_regclass('ahaa_private.whatsapp_receipts') AS name"
        ).fetchone()['name']
    else:
        exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='whatsapp_receipts'"
        ).fetchone()
    if exists:
        connection.execute(
            'DELETE FROM whatsapp_receipts WHERE event_id IN '
            '(SELECT id FROM events WHERE customer_id=?)', (customer_id,),
        )


@contextmanager
def connect(path, url='', *, write=False, initialize_schema=False, uri=False):
    if url:
        try:
            connection = psycopg.connect(
                url, row_factory=dict_row, connect_timeout=10,
                sslmode='verify-full', sslrootcert=os.getenv('SUPABASE_SSL_ROOT_CERT') or 'system',
            )
        except ValueError:
            raise RuntimeError('Supabase connection failed. The database connection string is invalid.') from None
        except psycopg.Error as error:
            raise RuntimeError(f'Supabase connection failed. {connection_failure_reason(error)}') from None
        with connection:
            if write:
                # Same serialization guarantee as SQLite BEGIN IMMEDIATE.
                connection.execute('SELECT pg_advisory_xact_lock(%s)', (WRITE_LOCK,))
            else:
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            if initialize_schema:
                connection.execute('CREATE SCHEMA IF NOT EXISTS ahaa_private')
            connection.execute('SET LOCAL search_path TO ahaa_private, pg_catalog')
            yield PostgresConnection(connection)
        return

    connection = sqlite3.connect(path, timeout=20, uri=uri)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(path, url):
    if not url:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with connect(path) as connection:
            connection.executescript('PRAGMA journal_mode=WAL;\n' + SCHEMA)
            for table, column in ADDED_COLUMNS:
                existing = {row['name'] for row in connection.execute(f'PRAGMA table_info({table})')}
                if column not in existing:
                    connection.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT')
        return

    # Only the authenticated server connects to this schema.
    with connect(path, url, write=True, initialize_schema=True) as connection:
        for statement in SCHEMA.split(';'):
            statement = statement.strip()
            if not statement:
                continue
            if any(statement.startswith(f'CREATE TABLE IF NOT EXISTS {table}(') for table in IDENTITY_TABLES):
                statement = statement.replace('id INTEGER PRIMARY KEY', 'id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY', 1)
            statement = statement.replace(' REAL ', ' DOUBLE PRECISION ')
            connection.execute(statement)
        for table, column in ADDED_COLUMNS:
            connection.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} TEXT')
        connection.execute('REVOKE ALL ON SCHEMA ahaa_private FROM PUBLIC, anon, authenticated, service_role')
        for table in TABLES:
            connection.execute(f'REVOKE ALL ON TABLE {table} FROM PUBLIC, anon, authenticated, service_role')
            connection.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
