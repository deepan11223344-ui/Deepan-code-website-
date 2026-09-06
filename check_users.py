import sys; sys.path.insert(0, '.')
from apps.api.crypto import verify_password
import sqlite3

conn = sqlite3.connect(r'C:\Users\devil\.deepans-code\web.db')
conn.row_factory = sqlite3.Row

for row in conn.execute('SELECT id, email, pwd_hash, pwd_salt, failed_attempts, locked_until FROM users'):
    d = dict(row)
    for pwd in ['admin12345678', 'password', 'Password123', '12345678', 'test1234', 'devil123']:
        if verify_password(pwd, d['pwd_hash'], d['pwd_salt']):
            print(f"User {d['email']}: password is \"{pwd}\"")
            break
    else:
        print(f"User {d['email']}: no common password matches (locked_until={d['locked_until']})")
conn.close()