"""
export_static.py — Export database & static assets for GitHub Pages deployment.

Reads data/locations.db and dumps locations.json and counts.json,
then copies all static frontend files into a top-level docs/ folder.
"""

import json
import shutil
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
STATIC_DIR = ROOT_DIR / "app" / "static"
DOCS_DIR = ROOT_DIR / "docs"


def export_static_site():
    db_path = DATA_DIR / "locations.db"
    if not db_path.exists():
        print(f"Error: Database file not found at {db_path}")
        return False

    # Ensure output directory exists
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading database from {db_path}...")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Export locations.json
    rows = cursor.execute("""
        SELECT id, name, address, city, state, zip,
               latitude, longitude, program,
               phone, email, website,
               individual_memberships, group_memberships,
               proof_of_residence, source_pdf, source_pdf_url
        FROM locations
        WHERE geocode_status = 'success'
        ORDER BY state, name
    """).fetchall()

    locations = []
    for row in rows:
        d = dict(row)
        d["proof_of_residence"] = bool(d["proof_of_residence"])
        locations.append(d)

    locations_json_path = DOCS_DIR / "locations.json"
    with open(locations_json_path, "w", encoding="utf-8") as f:
        json.dump(locations, f, indent=2)
    print(f"Exported {len(locations)} locations to {locations_json_path}")

    # 2. Export counts.json
    count_rows = cursor.execute("""
        SELECT program, COUNT(*) as count
        FROM locations
        WHERE geocode_status = 'success'
        GROUP BY program
    """).fetchall()

    counts = {row["program"]: row["count"] for row in count_rows}
    counts_json_path = DOCS_DIR / "counts.json"
    with open(counts_json_path, "w", encoding="utf-8") as f:
        json.dump(counts, f, indent=2)
    print(f"Exported counts to {counts_json_path}: {counts}")

    conn.close()

    # 3. Copy static assets to docs/
    print(f"Copying static frontend assets from {STATIC_DIR} to {DOCS_DIR}...")
    for item in STATIC_DIR.iterdir():
        dest = DOCS_DIR / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    # 4. Create .nojekyll to ensure GitHub Pages doesn't ignore files starting with _
    nojekyll_path = DOCS_DIR / ".nojekyll"
    nojekyll_path.touch(exist_ok=True)

    print("\n[OK] Export complete! Docs folder is ready for GitHub Pages.")
    return True


if __name__ == "__main__":
    export_static_site()
