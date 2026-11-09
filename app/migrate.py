"""Copy the owner and financial records from a local database to empty Supabase tables."""
from pathlib import Path

from app.storage import IDENTITY_TABLES, connect, initialize

IMPORT_COLUMNS = {
    'owner': ('id', 'email', 'salt', 'password'),
    'customers': ('id', 'name', 'email', 'phone', 'consent', 'notes', 'created'),
    'grants': ('id', 'customer_id', 'remaining', 'created'),
    'events': ('id', 'customer_id', 'grant_id', 'kind', 'cash', 'delta', 'balance',
               'details', 'created', 'original_id'),
    'requests': ('key', 'fingerprint', 'event_id'),
    'audit': ('id', 'action', 'details', 'created'),
}


def migrate(source_path, url):
    if not url:
        raise ValueError('Set SUPABASE_DATABASE_URL in .env first.')
    source = Path(source_path).resolve(strict=True)
    if not source.is_file():
        raise ValueError('Select a SQLite database file.')

    initialize(source, url)
    counts = {}
    with connect(source.as_uri() + '?mode=ro', write=False, uri=True) as local:
        with connect(source, url, write=True) as remote:
            for table in IMPORT_COLUMNS:
                if remote.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
                    raise ValueError('The destination already has app records. Import requires empty tables.')

            for table, fields in IMPORT_COLUMNS.items():
                sort_column = 'key' if table == 'requests' else 'id'
                columns = ', '.join(fields)
                rows = local.execute(f'SELECT {columns} FROM {table} ORDER BY {sort_column}').fetchall()
                if rows:
                    placeholders = ', '.join('?' for _ in fields)
                    for row in rows:
                        remote.execute(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})', tuple(row))
                    if table in IDENTITY_TABLES:
                        next_id = rows[-1]['id'] + 1
                        remote.execute(f'ALTER TABLE {table} ALTER COLUMN id RESTART WITH {next_id}')
                counts[table] = len(rows)
    return counts
