import sqlite3
conn = sqlite3.connect('data/locations.db')
conn.row_factory = sqlite3.Row

# Count per program
counts = conn.execute("SELECT program, COUNT(*) as cnt FROM locations WHERE geocode_status='failed' GROUP BY program").fetchall()
print("Failed count per program:")
for r in counts:
    print(f"  {r['program']}: {r['cnt']}")

print("\nFailed AHS examples:")
ahs_failed = conn.execute("SELECT name, address FROM locations WHERE program='AHS' AND geocode_status='failed' LIMIT 15").fetchall()
for r in ahs_failed:
    print(f"  {r['name']} -> {r['address']}")
conn.close()
