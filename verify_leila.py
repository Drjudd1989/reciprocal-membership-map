import sqlite3
conn = sqlite3.connect('data/locations.db')
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT * FROM locations WHERE name LIKE 'Leila%'").fetchone()
if r:
    print(dict(r))
else:
    print("Not found")
conn.close()
