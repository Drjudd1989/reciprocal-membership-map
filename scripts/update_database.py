"""
update_database.py — Master data ingestion script.

Usage:
    python scripts/update_database.py --program astc
    python scripts/update_database.py --program all
    python scripts/update_database.py --retry-failed

What it does:
    1. Discovers the current PDF URL from the official ASTC passport page
    2. Downloads the PDF to data/pdfs/
    3. Parses the PDF into venue records
    4. Geocodes each address via Nominatim (1 req/sec rate limit)
    5. Upserts records into the SQLite database
"""

import argparse
import sqlite3
import sys
import os
import time
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Add scripts dir to path so we can import siblings
sys.path.insert(0, str(Path(__file__).parent))
from parse_astc import parse_astc_pdf
from parse_ahs import parse_ahs_pdf
from parse_acm import parse_acm_pdf
from parse_aza import parse_aza_pdf
from geocode import geocode_with_rate_limit

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = Path("data/locations.db")
PDF_DIR = Path("data/pdfs")

ASTC_PASSPORT_PAGE = "https://www.astc.org/membership/find-an-astc-member/passport/"
ASTC_PDF_FILENAME = "Compact-List-6pt-Font.pdf"  # Consistent filename, date in path

AHS_PASSPORT_PAGE = "https://ahsgardening.org/ahs-garden-network/"
ACM_PASSPORT_PAGE = "https://findachildrensmuseum.org/reciprocal-network/"
AZA_PASSPORT_PAGE = "https://www.aza.org/reciprocity"

NOMINATIM_EMAIL = os.getenv("NOMINATIM_EMAIL", "toolsbyjudd@gmail.com")
HEADERS = {
    "User-Agent": f"ReciprocalMembershipMap/1.0 ({NOMINATIM_EMAIL})"
}


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS locations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL,
    address                 TEXT,
    city                    TEXT,
    state                   TEXT,
    zip                     TEXT,
    latitude                REAL,
    longitude               REAL,
    program                 TEXT NOT NULL CHECK(program IN ('ASTC', 'ACM', 'AZA', 'AHS')),
    phone                   TEXT,
    email                   TEXT,
    website                 TEXT,
    individual_memberships  TEXT,
    group_memberships       TEXT,
    proof_of_residence      INTEGER DEFAULT 0,
    source_pdf              TEXT,
    source_pdf_url          TEXT,
    geocode_status          TEXT DEFAULT 'pending'
                                CHECK(geocode_status IN ('pending', 'success', 'failed')),
    last_updated            TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_program ON locations(program);
CREATE INDEX IF NOT EXISTS idx_state ON locations(state);
CREATE INDEX IF NOT EXISTS idx_geocode_status ON locations(geocode_status);
"""


def get_db_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection):
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# PDF discovery & download
# ---------------------------------------------------------------------------

def discover_astc_pdf_url() -> str:
    """
    Scrape the ASTC passport page to find the current compact list PDF URL.
    The filename is always Compact-List-6pt-Font.pdf; only the date path changes.
    """
    print(f"Discovering current ASTC PDF URL from:\n  {ASTC_PASSPORT_PAGE}")
    resp = requests.get(ASTC_PASSPORT_PAGE, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ASTC_PDF_FILENAME in href:
            print(f"  Found: {href}")
            return href

    raise RuntimeError(
        f"Could not find a link containing '{ASTC_PDF_FILENAME}' on the ASTC passport page. "
        "The page structure may have changed."
    )


def discover_ahs_pdf_url() -> str:
    """
    Scrape the AHS garden network page to find the current directory PDF URL.
    """
    print(f"Discovering current AHS PDF URL from:\n  {AHS_PASSPORT_PAGE}")
    resp = requests.get(AHS_PASSPORT_PAGE, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "AHS-Garden-Network-List" in href and href.endswith(".pdf"):
            print(f"  Found: {href}")
            return href
        if "garden-network-list" in href.lower() and href.endswith(".pdf"):
            print(f"  Found (fallback): {href}")
            return href

    raise RuntimeError(
        "Could not find a link containing 'AHS-Garden-Network-List' and ending in '.pdf' on the AHS page."
    )


def discover_acm_pdf_url() -> str:
    """
    Scrape the ACM reciprocal network page to find the Box.com sharing link.
    Converts the share link to a direct download link.
    """
    print(f"Discovering current ACM PDF URL from:\n  {ACM_PASSPORT_PAGE}")
    resp = requests.get(ACM_PASSPORT_PAGE, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "box.com/s/" in href:
            print(f"  Found Box share link: {href}")
            match = re.search(r'box\.com/s/([a-z0-9]+)', href)
            if match:
                sharing_key = match.group(1)
                subdomain_match = re.search(r'https?://([^/]+)\.box\.com', href)
                subdomain = subdomain_match.group(1) if subdomain_match else "associationofchildrensmuse"
                subdomain = subdomain.replace(".app", "")
                
                direct_url = f"https://{subdomain}.box.com/shared/static/{sharing_key}.pdf"
                print(f"  Mapped to direct download URL: {direct_url}")
                return direct_url

    raise RuntimeError(
        "Could not find a Box.com link on the ACM page."
    )


def discover_aza_pdf_url() -> str:
    """
    Scrape the AZA reciprocity page to find the current reciprocity chart PDF link.
    """
    print(f"Discovering current AZA PDF URL from:\n  {AZA_PASSPORT_PAGE}")
    resp = requests.get(AZA_PASSPORT_PAGE, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "reciprocity_chart.pdf" in href:
            print(f"  Found: {href}")
            return href
        if "reciprocity" in href.lower() and href.endswith(".pdf"):
            print(f"  Found (fallback): {href}")
            return href

    raise RuntimeError(
        "Could not find a link containing 'reciprocity_chart.pdf' or ending in '.pdf' on the AZA page."
    )


def download_pdf(url: str, dest: Path) -> Path:
    """Download a PDF from url to dest directory. Returns the local path."""
    dest.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1]
    local_path = dest / filename

    print(f"Downloading PDF...\n  {url}")
    resp = requests.get(url, headers=HEADERS, timeout=60, stream=True)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)

    size_kb = downloaded // 1024
    print(f"  Saved to: {local_path} ({size_kb} KB)")
    return local_path


# ---------------------------------------------------------------------------
# Upsert logic
# ---------------------------------------------------------------------------

def upsert_venue(conn: sqlite3.Connection, venue: dict, program: str,
                 source_pdf: str, source_pdf_url: str) -> str:
    """
    Insert or update a venue record. Matches on (name, program).
    Returns 'inserted', 'updated', or 'skipped'.
    """
    existing = conn.execute(
        "SELECT id, geocode_status FROM locations WHERE name = ? AND program = ?",
        (venue["name"], program)
    ).fetchone()

    values = {
        "name": venue["name"],
        "address": venue["address"],
        "city": venue["city"],
        "state": venue["state"],
        "zip": venue["zip"],
        "program": program,
        "phone": venue["phone"],
        "email": venue["email"],
        "website": venue["website"],
        "individual_memberships": venue["individual_memberships"],
        "group_memberships": venue["group_memberships"],
        "proof_of_residence": venue["proof_of_residence"],
        "source_pdf": source_pdf,
        "source_pdf_url": source_pdf_url,
        "last_updated": "datetime('now')",
    }

    if existing:
        # Check if the address has changed
        row = conn.execute(
            "SELECT address FROM locations WHERE id = ?", (existing["id"],)
        ).fetchone()
        old_address = row["address"] if row else None

        if existing["geocode_status"] == 'failed' or old_address != venue["address"]:
            # Address changed or previous run failed! Reset geocoding
            conn.execute("""
                UPDATE locations SET
                    address = :address, city = :city, state = :state, zip = :zip,
                    phone = :phone, email = :email, website = :website,
                    individual_memberships = :individual_memberships,
                    group_memberships = :group_memberships,
                    proof_of_residence = :proof_of_residence,
                    source_pdf = :source_pdf, source_pdf_url = :source_pdf_url,
                    geocode_status = 'pending',
                    latitude = NULL, longitude = NULL,
                    last_updated = datetime('now')
                WHERE name = :name AND program = :program
            """, values)
        else:
            # Address didn't change and wasn't failed, just update other fields
            conn.execute("""
                UPDATE locations SET
                    phone = :phone, email = :email, website = :website,
                    individual_memberships = :individual_memberships,
                    group_memberships = :group_memberships,
                    proof_of_residence = :proof_of_residence,
                    source_pdf = :source_pdf, source_pdf_url = :source_pdf_url,
                    last_updated = datetime('now')
                WHERE name = :name AND program = :program
            """, values)
        return "updated"
    else:
        conn.execute("""
            INSERT INTO locations
                (name, address, city, state, zip, program, phone, email, website,
                 individual_memberships, group_memberships, proof_of_residence,
                 source_pdf, source_pdf_url, geocode_status)
            VALUES
                (:name, :address, :city, :state, :zip, :program, :phone, :email,
                 :website, :individual_memberships, :group_memberships,
                 :proof_of_residence, :source_pdf, :source_pdf_url, 'pending')
        """, values)
        return "inserted"


def geocode_pending(conn: sqlite3.Connection, limit: int | None = None):
    """Geocode all records with geocode_status = 'pending'."""
    query = "SELECT id, name, address, city, state FROM locations WHERE geocode_status = 'pending'"
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query).fetchall()
    if not rows:
        print("No pending geocodes.")
        return

    print(f"\nGeocoding {len(rows)} addresses (1 req/sec)...")
    success = failed = 0

    for row in rows:
        result = geocode_with_rate_limit(
            row["address"], 
            name=row["name"], 
            city=row["city"], 
            state=row["state"]
        )
        if result:
            lat, lon = result
            conn.execute(
                "UPDATE locations SET latitude=?, longitude=?, geocode_status='success' WHERE id=?",
                (lat, lon, row["id"])
            )
            conn.commit()
            success += 1
            print(f"  OK  {row['name'][:50]} -> ({lat:.4f}, {lon:.4f})")
        else:
            conn.execute(
                "UPDATE locations SET geocode_status='failed' WHERE id=?",
                (row["id"],)
            )
            conn.commit()
            failed += 1
            print(f"  FAIL {row['name'][:50]} -- geocode failed")

    print(f"\nGeocoding complete: {success} success, {failed} failed")


def geocode_retry_failed(conn: sqlite3.Connection):
    """Reset failed geocodes to pending and retry them."""
    count = conn.execute(
        "UPDATE locations SET geocode_status='pending' WHERE geocode_status='failed'"
    ).rowcount
    conn.commit()
    print(f"Reset {count} failed records to pending.")
    geocode_pending(conn)


# ---------------------------------------------------------------------------
# Program ingestion orchestrators
# ---------------------------------------------------------------------------

def ingest_astc(conn: sqlite3.Connection):
    """Full ASTC ingestion: discover URL, download, parse, upsert."""
    print("\n" + "=" * 60)
    print("INGESTING: ASTC")
    print("=" * 60)

    pdf_url = discover_astc_pdf_url()
    local_pdf = download_pdf(pdf_url, PDF_DIR)

    venues = parse_astc_pdf(local_pdf)
    print(f"\nUpserting {len(venues)} venues into database...")

    inserted = updated = 0
    for venue in venues:
        action = upsert_venue(
            conn, venue,
            program="ASTC",
            source_pdf=local_pdf.name,
            source_pdf_url=pdf_url,
        )
        if action == "inserted":
            inserted += 1
        elif action == "updated":
            updated += 1

    conn.commit()
    print(f"  Inserted: {inserted}, Updated: {updated}")

    geocode_pending(conn)


def ingest_ahs(conn: sqlite3.Connection):
    """Full AHS Ingestion: discover URL, download, parse, upsert."""
    print("\n" + "=" * 60)
    print("INGESTING: AHS")
    print("=" * 60)

    pdf_url = discover_ahs_pdf_url()
    local_pdf = download_pdf(pdf_url, PDF_DIR)

    venues = parse_ahs_pdf(local_pdf)
    print(f"\nUpserting {len(venues)} venues into database...")

    inserted = updated = 0
    for venue in venues:
        action = upsert_venue(
            conn, venue,
            program="AHS",
            source_pdf=local_pdf.name,
            source_pdf_url=pdf_url,
        )
        if action == "inserted":
            inserted += 1
        elif action == "updated":
            updated += 1

    conn.commit()
    print(f"  Inserted: {inserted}, Updated: {updated}")

    geocode_pending(conn)


def ingest_acm(conn: sqlite3.Connection):
    """Full ACM Ingestion: discover URL, download, parse, upsert."""
    print("\n" + "=" * 60)
    print("INGESTING: ACM")
    print("=" * 60)

    pdf_url = discover_acm_pdf_url()
    local_pdf = download_pdf(pdf_url, PDF_DIR)

    venues = parse_acm_pdf(local_pdf)
    print(f"\nUpserting {len(venues)} venues into database...")

    inserted = updated = 0
    for venue in venues:
        action = upsert_venue(
            conn, venue,
            program="ACM",
            source_pdf=local_pdf.name,
            source_pdf_url=pdf_url,
        )
        if action == "inserted":
            inserted += 1
        elif action == "updated":
            updated += 1

    conn.commit()
    print(f"  Inserted: {inserted}, Updated: {updated}")

    geocode_pending(conn)


def ingest_aza(conn: sqlite3.Connection):
    """Full AZA Ingestion: discover URL, download, parse, upsert."""
    print("\n" + "=" * 60)
    print("INGESTING: AZA")
    print("=" * 60)

    pdf_url = discover_aza_pdf_url()
    local_pdf = download_pdf(pdf_url, PDF_DIR)

    venues = parse_aza_pdf(local_pdf)
    print(f"\nUpserting {len(venues)} venues into database...")

    inserted = updated = 0
    for venue in venues:
        action = upsert_venue(
            conn, venue,
            program="AZA",
            source_pdf=local_pdf.name,
            source_pdf_url=pdf_url,
        )
        if action == "inserted":
            inserted += 1
        elif action == "updated":
            updated += 1

    conn.commit()
    print(f"  Inserted: {inserted}, Updated: {updated}")

    geocode_pending(conn)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Reciprocal Membership Map — Database Ingestion Script"
    )
    parser.add_argument(
        "--program",
        choices=["astc", "acm", "aza", "ahs", "all"],
        default="astc",
        help="Which program to ingest (default: astc)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry previously failed geocodes instead of full ingestion",
    )
    args = parser.parse_args()

    conn = get_db_connection()
    init_db(conn)

    if args.retry_failed:
        print("Retrying failed geocodes...")
        geocode_retry_failed(conn)
        conn.close()
        return

    programs = (
        ["astc", "acm", "aza", "ahs"] if args.program == "all" else [args.program]
    )

    for program in programs:
        if program == "astc":
            ingest_astc(conn)
        elif program == "acm":
            ingest_acm(conn)
        elif program == "aza":
            ingest_aza(conn)
        elif program == "ahs":
            ingest_ahs(conn)

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
