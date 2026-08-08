"""
database.py — SQLite connection and query helpers for the FastAPI app.
"""

import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path("/app/data/locations.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_locations(programs: Optional[list[str]] = None) -> list[dict]:
    """
    Return all successfully geocoded locations, optionally filtered by program.
    programs: list of program codes e.g. ['ASTC', 'ACM']
    """
    conn = get_connection()
    try:
        if programs:
            placeholders = ",".join("?" * len(programs))
            query = f"""
                SELECT id, name, address, city, state, zip,
                       latitude, longitude, program,
                       phone, email, website,
                       individual_memberships, group_memberships,
                       proof_of_residence, source_pdf, source_pdf_url
                FROM locations
                WHERE geocode_status = 'success'
                  AND program IN ({placeholders})
                ORDER BY state, name
            """
            rows = conn.execute(query, programs).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, name, address, city, state, zip,
                       latitude, longitude, program,
                       phone, email, website,
                       individual_memberships, group_memberships,
                       proof_of_residence, source_pdf, source_pdf_url
                FROM locations
                WHERE geocode_status = 'success'
                ORDER BY state, name
            """).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_location_counts() -> dict[str, int]:
    """Return venue count per program for the filter panel badge counts."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT program, COUNT(*) as count
            FROM locations
            WHERE geocode_status = 'success'
            GROUP BY program
        """).fetchall()
        return {row["program"]: row["count"] for row in rows}
    finally:
        conn.close()


def get_total_count() -> int:
    """Return total geocoded location count."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as count FROM locations WHERE geocode_status = 'success'"
        ).fetchone()
        return row["count"] if row else 0
    finally:
        conn.close()
