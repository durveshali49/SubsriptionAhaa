"""Disposable browser QA data, never production. Run with server stopped."""
import getpass
import secrets
import uuid
from app import main

main.SUPABASE_DATABASE_URL = ''
main.DB = str(main.ROOT / 'data' / 'preview.sqlite3')
main.init_db()
with main.database(True) as c:
    if c.execute('SELECT 1 FROM owner').fetchone():
        raise SystemExit('Preview already exists; refusing to replace data.')
    password = getpass.getpass('Choose a temporary preview password (12+ characters): ')
    if len(password) < 12:
        raise SystemExit('Use at least 12 characters.')
    salt=secrets.token_hex(16)
    c.execute('INSERT INTO owner VALUES(1,?,?,?)', ('preview@example.com',salt,main.password_hash(password,salt)))
for i,(name,email,number) in enumerate([
    ('Ravi Kumar','ravi@example.com','+12025550101'),
    ('Priya Reddy','priya@example.com','+12025550102'),
    ('Anil Sharma','anil@example.com','+12025550103'),
    ('Sneha Rao','sneha@example.com','+12025550104'),
]):
    cid=main.create_customer(main.Customer(name=name,email=email,phone=number,consent=True),None)['id']
    main.enroll(main.Payment(key=str(uuid.uuid4()),customer_id=cid,method='Cash'),None)
    if i<3:
        main.order(main.Order(key=str(uuid.uuid4()),customer_id=cid,items=[main.Item(name='Chicken Biryani',quantity=1,price=1800),main.Item(name='Paneer Curry',quantity=1,price=1400),main.Item(name='Naan',quantity=2,price=400)]),None)
print('Created disposable preview database. Real application database unchanged.')
