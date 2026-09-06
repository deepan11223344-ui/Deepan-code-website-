import sqlite3, os
db_path = os.path.expanduser("~/.deepans-code/web.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t[0] for t in tables])
try:
    users = conn.execute("SELECT id, email, is_admin, totp_enabled FROM users").fetchall()
    print("Users:", [dict(u) for u in users])
except Exception as e:
    print("Users error:", e)
try:
    sessions = conn.execute("SELECT COUNT(*) as cnt FROM sessions").fetchone()
    print("Sessions:", sessions[0])
except Exception as e:
    print("Sessions error:", e)
conn.close()
