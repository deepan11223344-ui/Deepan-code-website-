import sys; sys.path.insert(0, '.')
from apps.api.crypto import hash_password, verify_password
import sqlite3

# Get the stored hash for admin
conn = sqlite3.connect(r'C:\Users\devil\.deepans-code\web.db')
conn.row_factory = sqlite3.Row
admin = dict(conn.execute('SELECT * FROM users WHERE email = ?', ('admin@deepancode.local',)).fetchone())
conn.close()

print("Stored hash:", admin['pwd_hash'])
print("Stored salt:", admin['pwd_salt'])
print("Stored hash length:", len(admin['pwd_hash']))
print("Stored salt length:", len(admin['pwd_salt']))

# Generate a new hash with the same password
new_hash, new_salt = hash_password('admin12345678')
print("\nNew hash:", new_hash)
print("New salt:", new_salt)
print("New hash length:", len(new_hash))
print("New salt length:", len(new_salt))

# Verify
print("\nVerify stored hash:", verify_password('admin12345678', admin['pwd_hash'], admin['pwd_salt']))
print("Verify new hash:", verify_password('admin12345678', new_hash, new_salt))