import sys; sys.path.insert(0, '.')
from apps.api.crypto import hash_password
import sqlite3

conn = sqlite3.connect(r'C:\Users\devil\.deepans-code\web.db')

# Reset admin password to a known good one
pwd_hash, salt = hash_password('Admin@12345678')
conn.execute('UPDATE users SET pwd_hash=?, pwd_salt=?, failed_attempts=0, locked_until=0 WHERE email=?',
             (pwd_hash, salt, 'admin@deepancode.local'))

# Unlock devilrolex07@gmail.com and reset password
pwd_hash2, salt2 = hash_password('Admin@12345678')
conn.execute('UPDATE users SET pwd_hash=?, pwd_salt=?, failed_attempts=0, locked_until=0 WHERE email=?',
             (pwd_hash2, salt2, 'devilrolex07@gmail.com'))

# Reset test@example.com
pwd_hash3, salt3 = hash_password('Admin@12345678')
conn.execute('UPDATE users SET pwd_hash=?, pwd_salt=?, failed_attempts=0, locked_until=0 WHERE email=?',
             (pwd_hash3, salt3, 'test@example.com'))

conn.commit()

# Verify
conn.row_factory = sqlite3.Row
for row in conn.execute('SELECT email, failed_attempts, locked_until FROM users'):
    print(dict(row))
conn.close()
print("\nAll accounts reset to password: Admin@12345678")
