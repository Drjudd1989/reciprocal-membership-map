# Architecture: Reciprocal Memberships Map (MVP 1)

## 1. System Overview

A self-hosted, single-container web application that displays reciprocal membership venues for four programs (ASTC, ACM, AZA, AHS) on an interactive map. Data is ingested from program PDFs via an automated Python script run manually on an as-needed basis (every 6–12 months). The app is deployed on a home NAS and accessed via LAN and a private Cloudflare Tunnel.

```
┌─────────────────────────────────────────────┐
│              Docker Container                │
│                                             │
│  ┌────────────┐       ┌──────────────────┐  │
│  │  FastAPI   │──────▶│  SQLite DB       │  │
│  │  Server   │       │  /app/data/      │  │
│  │  :8000    │       │  locations.db    │  │
│  └─────┬──────┘       └──────────────────┘  │
│        │ serves                             │
│  ┌─────▼──────┐       ┌──────────────────┐  │
│  │ Static     │       │  /app/data/      │  │
│  │ Frontend   │       │  pdfs/ (source)  │  │
│  │ HTML/CSS/JS│       └──────────────────┘  │
│  └────────────┘                             │
└─────────────────────────────────────────────┘
         ▲                        ▲
         │ LAN :8090              │ run manually
  Cloudflare Tunnel          update_database.py
```

---

## 2. Project File Structure

```
reciprocal-map/
├── app/
│   ├── main.py                  # FastAPI app entrypoint
│   ├── database.py              # SQLite connection + queries
│   └── static/
│       ├── index.html           # Single-page app
│       ├── style.css            # All styles
│       └── app.js               # Leaflet map + filter logic
│
├── scripts/
│   ├── update_database.py       # Master ingestion script (runs all parsers)
│   ├── parse_astc.py            # ASTC-specific PDF parser
│   ├── parse_acm.py             # ACM-specific PDF parser
│   ├── parse_aza.py             # AZA-specific PDF parser
│   ├── parse_ahs.py             # AHS-specific PDF parser
│   └── geocode.py               # Nominatim geocoding helper
│
├── data/                        # Volume-mounted persistent storage
│   ├── locations.db             # SQLite database
│   └── pdfs/
│       ├── astc.pdf
│       ├── acm.pdf
│       ├── aza.pdf
│       └── ahs.pdf
│
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 3. Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Backend | **Python 3.11 + FastAPI** | Lightweight, fast, async-capable; serves both API and static files |
| Database | **SQLite** | Zero-config, file-based, perfect for read-heavy, low-write workloads |
| Map Library | **Leaflet.js** | No API keys, OSM tiles, excellent mobile support |
| Map Tiles | **CartoDB Dark Matter** | Free, no API key, dark theme makes colored pins pop visually |
| PDF Parsing | **pdfplumber** | Best-in-class for text-based, multi-column PDFs |
| Geocoding | **Nominatim (OSM)** | Free, no API key, 1 req/sec rate limit (handled in code) |
| Containerization | **Docker + docker-compose** | Single container, portable, NAS-compatible |
| Access | **Cloudflare Tunnel** | Secure remote access without port forwarding or SSL cert management |
| Auth | **HTTP Basic Auth (FastAPI)** | Simple, sufficient for 2 private users; no user DB needed |

---

## 4. Database Schema

```sql
CREATE TABLE IF NOT EXISTS locations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    address         TEXT,
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    latitude        REAL,
    longitude       REAL,
    program         TEXT NOT NULL CHECK(program IN ('ASTC', 'ACM', 'AZA', 'AHS')),
    phone           TEXT,
    email           TEXT,
    website         TEXT,
    individual_memberships TEXT,   -- Comma-separated list of qualifying membership types
    group_memberships      TEXT,   -- Comma-separated list of qualifying membership types
    proof_of_residence     INTEGER DEFAULT 0,  -- Boolean: 1 = required
    source_pdf              TEXT,  -- Filename of source PDF (e.g., "astc.pdf")
    geocode_status  TEXT DEFAULT 'pending' CHECK(geocode_status IN ('pending', 'success', 'failed')),
    last_updated    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_program ON locations(program);
CREATE INDEX IF NOT EXISTS idx_state ON locations(state);
CREATE INDEX IF NOT EXISTS idx_geocode_status ON locations(geocode_status);
```

**Schema notes:**
- `city`, `state`, `zip` split out from `address` to enable future state-level filtering
- `proof_of_residence` flag extracted from PDF and surfaced in the UI popup
- `geocode_status` allows re-running failed geocodes without re-parsing PDFs
- `individual_memberships` / `group_memberships` stored as comma-separated text (simple, sufficient for display)

---

## 5. Data Ingestion Pipeline

### 5.1 PDF Structure (ASTC — confirmed from sample)

The ASTC PDF is a **text-based, two-column layout** organized by US state. Each venue block follows this consistent structure:

```
[STATE BANNER — dark background, all-caps]

Venue Name                          (bold, first line)
Street Address, City, ST ZIPCODE
(xxx) xxx-xxxx
email@domain.com
https://www.website.com/
Reciprocal Membership(s)            (bold header)
Individual Membership(s): Type A, Type B
Group Membership(s): Type C, Type D
[Proof of Residence Required]       (optional, appears in red)
```

### 5.2 Parsing Strategy (parse_astc.py)

The two-column layout requires column-aware extraction. pdfplumber supports bounding-box based text extraction:

```python
# Step 1: For each page, extract left and right columns separately
def extract_columns(page):
    w, h = page.width, page.height
    left  = page.within_bbox((0,   0, w/2, h)).extract_text()
    right = page.within_bbox((w/2, 0, w,   h)).extract_text()
    return [left, right]

# Step 2: Concatenate all column text blocks into a single stream
# Step 3: Split stream on STATE BANNER lines (all-caps, 3-25 chars, no punctuation)
# Step 4: For each state section, split on venue blocks
# Step 5: Parse each venue block field-by-field using label anchors:
#   - Line 1 = name (no label prefix)
#   - Line 2 = address (matches "City, ST ZIPCODE" pattern)
#   - Line 3 = phone (matches "(xxx) xxx-xxxx" pattern)
#   - Line containing "@" = email
#   - Line starting with "http" = website
#   - "Individual Membership(s):" prefix -> individual_memberships
#   - "Group Membership(s):" prefix -> group_memberships
#   - "Proof of Residence Required" -> proof_of_residence = 1
```

### 5.3 Parsing Strategy (parse_ahs.py)

The AHS PDF is a text-based, single-column document organized by US state/Canadian province.
- Utilizes a line-by-line state machine tracker.
- Identifies active state/province headings (e.g. `ALABAMA`, `CANADA`).
- Matches garden names, city, and state patterns.
- Maps garden-specific notes or entry caveats to `group_memberships`.

### 5.4 Parsing Strategy (parse_acm.py)

The ACM PDF features a three-column layout.
- Utilizes `page.within_bbox()` to split each page width-wise into three equal columns:
  - Column 1: `x` in `[0, 0.35 * width]`
  - Column 2: `x` in `[0.35 * width, 0.68 * width]`
  - Column 3: `x` in `[0.68 * width, width]`
- Evaluates names and city/state associations line by line.
- Features a buffer-flush heuristic to join wrapped lines (handles U.S. Virgin Islands and other multiline wraps).
- Cleans and standardizes state codes.

### 5.5 Parsing Strategy (parse_aza.py)

The AZA PDF is a landscape document with a 6-column tabular layout and a right-hand sidebar.
- Crops each page at `x0 < 605` to ignore the sidebar entirely.
- Groups words into horizontal rows by clustering their `top` coordinates (clustering threshold < 3).
- Sifts words into discrete columns based on horizontal bounds:
  - State: `15 <= x0 < 74`
  - City: `74 <= x0 < 155`
  - Name: `155 <= x0 < 358`
  - Reciprocity: `358 <= x0 < 406`
  - Contact Name: `406 <= x0 < 496`
  - Phone / Email: `496 <= x0 < 605`
- Distinguishes new venue lines from continuation lines by verifying the presence of contact info (e.g. contact name or phone/email words) in `x0 >= 406`.
- Continuation lines (like gift shop discount notes) are merged and appended to `group_memberships` of the preceding venue.
- Cleans name overflows (such as `FREE TO PUBLIC` ending up in the name column) and normalizes international entries (e.g. Canadian provinces).

### 5.6 Geocoding (geocode.py)

```python
import time, requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "ReciprocalMembershipMap/1.0 contact@yourdomain.com"}

def geocode_address(address: str) -> tuple[float, float] | None:
    params = {"q": address, "format": "json", "limit": 1, "countrycodes": "us"}
    resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
    results = resp.json()
    if results:
        return float(results[0]["lat"]), float(results[0]["lon"])
    return None
    # ALWAYS call time.sleep(1) after each geocode call (Nominatim ToS)
```

**Geocoding failure handling:**
- On failure: `geocode_status = 'failed'`, venue stored but hidden from map
- `--retry-failed` flag on update_database.py retries only failed records
- Full address string used: `"800 Museum Dr, Anniston, AL 36206"` + `countrycodes=us` for accuracy

### 5.7 update_database.py (Master Script)

```
Usage:
  python scripts/update_database.py --program astc
  python scripts/update_database.py --program all
  python scripts/update_database.py --retry-failed

Flow:
  1. Parse PDF for specified program(s) -> list of raw venue dicts
  2. For each venue:
     a. UPSERT into DB (match on name + program to avoid duplicates on re-run)
     b. Geocode address -> update lat/lon + geocode_status
     c. Sleep 1 second (Nominatim rate limit)
  3. Print summary: X inserted, Y updated, Z geocode failures
```

---

## 6. Backend API (FastAPI)

### 6.1 Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | Yes | Serves `index.html` |
| `GET` | `/static/*` | Yes | Serves CSS/JS assets |
| `GET` | `/api/locations` | Yes | Returns all geocoded locations as JSON |
| `GET` | `/api/locations?program=ASTC,ACM` | Yes | Filter by program(s) |
| `GET` | `/api/health` | No | Health check — `{"status": "ok", "count": N}` |

### 6.2 /api/locations Response Shape

```json
[
  {
    "id": 1,
    "name": "Anniston Museums and Gardens",
    "address": "800 Museum Dr, Anniston, AL 36206",
    "city": "Anniston",
    "state": "AL",
    "latitude": 33.6543,
    "longitude": -85.8312,
    "program": "ASTC",
    "phone": "(256) 237-6766",
    "website": "https://www.exploream.org/",
    "individual_memberships": "Individual Level Membership",
    "group_memberships": "Family Level Membership, Family + Guest Level Membership",
    "proof_of_residence": false,
    "source_pdf": "astc.pdf"
  }
]
```

### 6.3 Authentication

HTTP Basic Auth via FastAPI's built-in `HTTPBasic` dependency applied to all routes except `/api/health`. Credentials injected as environment variables via docker-compose `.env` file — never hardcoded.

```
# .env (gitignored)
APP_USERNAME=yourname
APP_PASSWORD=a_strong_password_here
```

---

## 7. Frontend Design System

### 7.1 Design Philosophy

> **"Map to see the things."** — Primary user is non-technical and impatient.

- Zero learning curve: map fills the screen, one control panel, done
- Dark map tiles make pins visually pop with no visual noise
- Large, tap-friendly controls (works on phone/tablet out of the box)
- Instant visual differentiation between programs via distinct colors

### 7.2 Program Color Palette

| Program | Color | Hex | Rationale |
|---|---|---|---|
| ASTC | Blue | `#4A9EFF` | Science/technology = blue (intuitive association) |
| ACM | Purple | `#B66DFF` | Creative/cultural/children = purple |
| AZA | Amber | `#FF8C42` | Wildlife/zoos = warm orange |
| AHS | Green | `#52D68A` | Horticulture/gardens = green |

### 7.3 UI Layout

```
┌────────────────────────────────────────────────────┐
│ ┌──────────────────────────────────────────────┐   │
│ │ 🗺 Reciprocal Memberships                    │   │
│ │  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐    │   │
│ │  │⬤ASTC │  │⬤ ACM │  │⬤ AZA │  │⬤ AHS │    │   │
│ │  │ 342  │  │  98  │  │ 241  │  │  87  │    │   │
│ │  └──────┘  └──────┘  └──────┘  └──────┘    │   │
│ └──────────────────────────────────────────────┘   │
│                                                    │
│            [DARK MAP — FULL VIEWPORT]              │
│         (CartoDB Dark Matter + colored pins)       │
│                                                    │
│              ┌────────────────────────┐            │
│              │ Anniston Museums       │            │
│              │ ⬤ ASTC  •  Anniston, AL│           │
│              │ Individual: Indiv. Level│           │
│              │ Group: Family, Family+  │           │
│              │ 🌐 exploream.org       │            │
│              │ [Verify in PDF →]      │            │
│              └────────────────────────┘            │
└────────────────────────────────────────────────────┘
```

### 7.4 Filter Panel Behavior

- Each program shown as a large colored toggle button with a live count badge
- Active state = full vibrant color; inactive = same color but dimmed/muted at 30% opacity
- All programs active on initial load
- Count badges update dynamically as programs are toggled
- Panel is a floating glass-morphism card (top-left on desktop, top on mobile)

### 7.5 Map Pin Style

- **Leaflet `L.circleMarker`** — clean, scalable, no image assets needed
- Radius: `8px` normal, `11px` on hover
- Fill: program color; stroke: `2px white`
- On click: Leaflet popup opens with venue card (styled to match dark theme)
- Venues with `proof_of_residence = true` show a `⚠ Proof of Residence Required` warning line in the popup

### 7.6 Typography & Fonts

- Font: **Inter** (Google Fonts) — clean, highly legible, modern
- Map UI feels like a polished consumer product, not a dev prototype

---

## 8. Docker Deployment

### 8.1 Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY scripts/ ./scripts/
RUN mkdir -p /app/data/pdfs
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8.2 docker-compose.yml

```yaml
version: '3.8'
services:
  reciprocal-map:
    build: .
    container_name: reciprocal-map
    ports:
      - "8090:8000"
    volumes:
      - ./data:/app/data        # Persists DB + PDFs across restarts
    env_file:
      - .env                    # APP_USERNAME, APP_PASSWORD
    restart: unless-stopped
```

### 8.3 Running the Ingestion Script

Because updates are infrequent, the script is run interactively inside the container:

```bash
# SSH to NAS, navigate to project dir, then:
docker exec -it reciprocal-map python scripts/update_database.py --program astc
```

No cron job or scheduler needed. Manual execution is intentional.

---

## 9. Cloudflare Tunnel Notes

- `cloudflared` runs as a separate daemon on the NAS (not inside this container)
- Proxies `https://your-subdomain.yourdomain.com` → `localhost:8090`
- HTTPS termination and certificate management handled entirely by Cloudflare
- HTTP Basic Auth in the app provides an additional authentication layer
- No changes required to the app code for tunnel compatibility

---

## 10. requirements.txt

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
pdfplumber==0.11.0
requests==2.32.3
python-dotenv==1.0.1
beautifulsoup4==4.12.3
```

---

## 11. Build Sequence (Tonight)

| # | Step | Output |
|---|---|---|
| 1 | Create project scaffold | Directory structure + empty files |
| 2 | Write `parse_astc.py` | Parses ASTC PDF → list of venue dicts |
| 3 | Write `geocode.py` | Nominatim wrapper with 1s rate limiting |
| 4 | Write `update_database.py` | Wires parser + geocoder → SQLite |
| 5 | Run ingestion on ASTC PDF | Populated `locations.db` |
| 6 | Write `database.py` + `main.py` | `/api/locations` endpoint + static serving + auth |
| 7 | Write `index.html` + `style.css` + `app.js` | Full working frontend |
| 8 | Write `Dockerfile` + `docker-compose.yml` | Container definition |
| 9 | Local test (Python, no Docker) | Verify map, pins, filters, popups |
| 10 | Build + run Docker container locally | Verify containerized operation |
| 11 | Deploy to NAS | `docker-compose up -d` |

---

## 12. Open Questions Before Build

> [!IMPORTANT]
> Please confirm these before we start coding:

1. **Nominatim User-Agent email**: Nominatim ToS requires a real contact email in the User-Agent string. What email should the geocoder use? (It's just sent as a header — not publicly displayed.)

2. **Auth credentials**: What username/password do you want for HTTP Basic Auth? (Or I can generate a strong random one and output it to you.)

3. **Source PDF link**: The `source_pdf_url` in the popup — should this link to the **official ASTC website PDF** (the publicly hosted one) or a local file served from the container?

4. **ASTC PDF filename**: Should I assume the file will be placed at `./data/pdfs/astc.pdf` when running the ingestion script?

---

## 13. Future (MVP 2+) Considerations

| Feature | Notes |
|---|---|
| ASTC 90-mile rule | Requires user geolocation + haversine distance per pin |
| Public access | Replace HTTP Basic with proper user accounts |
| Search bar | Filter pins by venue name or city |
| "Near me" button | Geolocate user, zoom map to their location |
| State filter | Dropdown to show only venues in a selected state |
| Mobile PWA | Add manifest + service worker for installable app |
