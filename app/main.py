"""
main.py — FastAPI application entrypoint.

Serves the static frontend and provides the /api/locations JSON endpoint.
Protected by HTTP Basic Auth (2-user private access).
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------

APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "changeme")
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "false").lower() in ("true", "1", "yes")

# Path adjustments: when running locally vs in Docker
# In Docker: /app/data/  |  Locally: ./data/
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
STATIC_DIR = Path(__file__).parent / "static"

# ---------------------------------------------------------------------------
# FastAPI setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Reciprocal Memberships Map",
    description="Interactive map of reciprocal membership program venues",
    version="1.0.0",
    docs_url=None,   # Disable Swagger UI (private app)
    redoc_url=None,
)

security = HTTPBasic(auto_error=False)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def verify_credentials(credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    """HTTP Basic Auth verification using constant-time comparison."""
    if not REQUIRE_AUTH:
        return "anonymous"
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    correct_username = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        APP_USERNAME.encode("utf-8")
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        APP_PASSWORD.encode("utf-8")
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ---------------------------------------------------------------------------
# Lazy import database (allows app to start even without data dir)
# ---------------------------------------------------------------------------

def get_db():
    # Import here so Docker path is set before import
    import sqlite3
    db_path = DATA_DIR / "locations.db"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health_check():
    """Public health check endpoint — no auth required."""
    db = get_db()
    count = 0
    if db:
        try:
            row = db.execute(
                "SELECT COUNT(*) as c FROM locations WHERE geocode_status = 'success'"
            ).fetchone()
            count = row["c"] if row else 0
        except Exception:
            pass
        finally:
            db.close()
    return {"status": "ok", "venues": count}


@app.get("/api/locations")
def get_locations(
    program: Optional[str] = Query(
        None,
        description="Comma-separated program filter e.g. ASTC,ACM"
    ),
    _user: str = Depends(verify_credentials),
):
    """
    Return all geocoded venue locations as JSON.
    Optionally filter by program(s) using ?program=ASTC,ACM
    """
    db = get_db()
    if not db:
        return JSONResponse(content=[], status_code=200)

    try:
        programs = [p.strip().upper() for p in program.split(",")] if program else None

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
            rows = db.execute(query, programs).fetchall()
        else:
            rows = db.execute("""
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

        return JSONResponse(content=locations)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/api/counts")
def get_counts(_user: str = Depends(verify_credentials)):
    """Return venue count per program for filter panel badges."""
    db = get_db()
    if not db:
        return {}
    try:
        rows = db.execute("""
            SELECT program, COUNT(*) as count
            FROM locations
            WHERE geocode_status = 'success'
            GROUP BY program
        """).fetchall()
        return {row["program"]: row["count"] for row in rows}
    finally:
        db.close()


@app.post("/api/admin/refresh")
async def refresh_data(
    program: str = Query("astc", description="Program to refresh: astc, acm, aza, ahs, all"),
    _user: str = Depends(verify_credentials),
):
    """
    Trigger a full data refresh for the specified program.
    Downloads the latest PDF and re-ingests the database.
    This runs synchronously and may take several minutes due to geocoding.
    """
    valid_programs = {"astc", "acm", "aza", "ahs", "all"}
    if program.lower() not in valid_programs:
        raise HTTPException(status_code=400, detail=f"Invalid program: {program}")

    script_path = Path(__file__).parent.parent / "scripts" / "update_database.py"
    if not script_path.exists():
        raise HTTPException(status_code=500, detail="Ingestion script not found")

    try:
        result = subprocess.run(
            [sys.executable, str(script_path), "--program", program.lower()],
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max (geocoding ~hundreds of venues)
            cwd=str(Path(__file__).parent.parent),
        )
        return {
            "status": "complete" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout[-5000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Refresh timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Static files — served after API routes
# ---------------------------------------------------------------------------

# Serve the SPA index for the root
@app.get("/", include_in_schema=False)
def serve_root(_user: str = Depends(verify_credentials)):
    return FileResponse(str(STATIC_DIR / "index.html"))


# Mount static files at /static
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
