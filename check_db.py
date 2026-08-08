import sqlite3

conn = sqlite3.connect('data/locations.db')
conn.row_factory = sqlite3.Row

# Overall stats
total = conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0]
pending = conn.execute("SELECT COUNT(*) FROM locations WHERE geocode_status='pending'").fetchone()[0]
success = conn.execute("SELECT COUNT(*) FROM locations WHERE geocode_status='success'").fetchone()[0]
failed = conn.execute("SELECT COUNT(*) FROM locations WHERE geocode_status='failed'").fetchone()[0]

print(f"OVERALL STATS - Total: {total}, Pending: {pending}, Success: {success}, Failed: {failed}\n")

# Breakdown by program
print("PROGRAM BREAKDOWN:")
programs = conn.execute("SELECT program, COUNT(*) as cnt, SUM(CASE WHEN geocode_status='success' THEN 1 ELSE 0 END) as succ, SUM(CASE WHEN geocode_status='failed' THEN 1 ELSE 0 END) as fail, SUM(CASE WHEN geocode_status='pending' THEN 1 ELSE 0 END) as pend FROM locations GROUP BY program").fetchall()
for p in programs:
    print(f"  {p['program']}: Total={p['cnt']}, Success={p['succ']}, Failed={p['fail']}, Pending={p['pend']}")

conn.close()
