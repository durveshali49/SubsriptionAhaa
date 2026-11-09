"""Owner maintenance and database migration commands."""
import getpass
import secrets
import sys
from pathlib import Path
from app import main

if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv)>1 else ''
    if command == 'migrate-supabase':
        from app.migrate import migrate
        source = sys.argv[2] if len(sys.argv) > 2 else main.DB
        try:
            counts = migrate(source, main.SUPABASE_DATABASE_URL)
        except (ValueError, RuntimeError, FileNotFoundError) as error:
            raise SystemExit(str(error)) from None
        for table, count in counts.items():
            print(f'{table}: {count} records copied')
    elif command == 'backup':
        if main.SUPABASE_DATABASE_URL:
            raise SystemExit('Use the Supabase database backup tools for the hosted database.')
        main.init_db()
        folder = Path(main.DB).parent / 'backups'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ('ahaa-' + main.datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3')
        with main.database() as source, main.sqlite3.connect(target) as dest:
            source.backup(dest)
        print(f'Backup saved: {target.resolve()}')
    elif command == 'reset-password':
        password = getpass.getpass('New password (12+ characters): ')
        if len(password)<12 or password != getpass.getpass('Confirm password: '):
            raise SystemExit('Passwords must match and contain at least 12 characters.')
        with main.database(True) as c:
            if not c.execute('SELECT 1 FROM owner').fetchone():
                raise SystemExit('No owner account exists. Use initial local setup.')
            salt = secrets.token_hex(16)
            c.execute('UPDATE owner SET salt=?,password=? WHERE id=1', (salt, main.password_hash(password,salt)))
            c.execute('DELETE FROM sessions')
            main.audit(c,'local_password_reset',{})
        print('Password reset; all sessions invalidated.')
    else:
        raise SystemExit('Usage: python tools.py backup | reset-password | migrate-supabase [source.sqlite3]')
