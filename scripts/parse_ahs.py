"""
parse_ahs.py — American Horticultural Society (AHS) Reciprocal Garden List PDF parser.

Handles the single-column layout of the AHS Garden Network PDF.
Returns a list of venue dicts ready for DB insertion.
"""

import re
import pdfplumber
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# City, State ZIP / Postal code (US, Canada, and Territories)
# Captures: Group 1 = City, Group 2 = State/Province, Group 3 = Zip/Postal
ZIP_PATTERN = re.compile(
    r"^(.+),\s+([a-zA-Z\s>.,'-]+)\s+(\d{5}(?:-\d{4})?|[A-Z]\d[A-Z]\s?\d[A-Z]\d|KY\d-\d{4}(?:\s+[a-zA-Z\s]+)?)$",
    re.IGNORECASE
)

# Phone number pattern (matches standard numbers, no-separator formats, and truncated 9-digit lines)
PHONE_PATTERN = re.compile(
    r"^(?:1[\s\-\.]?)?\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{3,4}",
    re.IGNORECASE
)

# Website URL pattern (matches http/https/hbp, subdomains, and typical domain endings)
URL_PATTERN = re.compile(
    r"^(https?://|hbps?://|www\.)?([a-z0-9\-]+\.)+[a-z]{2,6}\b",
    re.IGNORECASE
)

# Email pattern
EMAIL_PATTERN = re.compile(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
)

# ---------------------------------------------------------------------------
# State normalization maps
# ---------------------------------------------------------------------------

STATE_MAP = {
    # US States
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN",
    "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "DISTRICT OF COLUMBIA": "DC", "PUERTO RICO": "PR", "VIRGIN ISLANDS": "VI", "U.S. VIRGIN ISLANDS": "VI",
    # Canadian Provinces
    "ALBERTA": "AB", "BRITISH COLUMBIA": "BC", "MANITOBA": "MB", "NEW BRUNSWICK": "NB",
    "NEWFOUNDLAND AND LABRADOR": "NL", "NOVA SCOTIA": "NS", "ONTARIO": "ON",
    "PRINCE EDWARD ISLAND": "PE", "QUEBEC": "QC", "SASKATCHEWAN": "SK",
    "NORTHWEST TERRITORIES": "NT", "NUNAVUT": "NU", "YUKON": "YT",
}

KNOWN_AHS_HEADERS = {
    # Categories / Countries
    "UNITED STATES", "U.S. TERRITORIES", "CANADA", "MEXICO", "INTERNATIONAL", "NEW GARDENS",
    # US States / Territories
    "ALABAMA", "ALASKA", "ARIZONA", "ARKANSAS", "CALIFORNIA", "COLORADO",
    "CONNECTICUT", "DELAWARE", "FLORIDA", "GEORGIA", "HAWAII", "IDAHO",
    "ILLINOIS", "INDIANA", "IOWA", "KANSAS", "KENTUCKY", "LOUISIANA",
    "MAINE", "MARYLAND", "MASSACHUSETTS", "MICHIGAN", "MINNESOTA",
    "MISSISSIPPI", "MISSOURI", "MONTANA", "NEBRASKA", "NEVADA",
    "NEW HAMPSHIRE", "NEW JERSEY", "NEW MEXICO", "NEW YORK",
    "NORTH CAROLINA", "NORTH DAKOTA", "OHIO", "OKLAHOMA", "OREGON",
    "PENNSYLVANIA", "RHODE ISLAND", "SOUTH CAROLINA", "SOUTH DAKOTA",
    "TENNESSEE", "TEXAS", "UTAH", "VERMONT", "VIRGINIA", "WASHINGTON",
    "WEST VIRGINIA", "WISCONSIN", "WYOMING", "DISTRICT OF COLUMBIA",
    "PUERTO RICO", "U.S. VIRGIN ISLANDS", "VIRGIN ISLANDS", "GUAM",
    # Canada Provinces
    "ALBERTA", "BRITISH COLUMBIA", "MANITOBA", "NEW BRUNSWICK",
    "NEWFOUNDLAND AND LABRADOR", "NOVA SCOTIA", "ONTARIO",
    "PRINCE EDWARD ISLAND", "QUEBEC", "SASKATCHEWAN",
    "NORTHWEST TERRITORIES", "NUNAVUT", "YUKON", "CAYMAN ISLANDS"
}

def normalize_state(name: str) -> str:
    cleaned = name.upper().strip().replace(".", "")
    
    # Custom ligature/OCR error fixes
    if "COLUMBIA" in cleaned:
        if "BRI" in cleaned or "BRT" in cleaned:
            return "BC"
    if "NEWFOUNDLAND" in cleaned:
        return "NL"
    if "VIRGIN ISLANDS" in cleaned or "ST CROIX" in cleaned:
        return "VI"
    if "PEI" in cleaned or "PRINCE EDWARD" in cleaned:
        return "PE"
    
    return STATE_MAP.get(cleaned, name)

def is_ahs_category_or_state_header(line: str) -> bool:
    cleaned = line.upper().strip()
    if cleaned in KNOWN_AHS_HEADERS:
        return True
    # Handle ligature cases for state/province headers
    if "COLUMBIA" in cleaned and ("BRI" in cleaned or "BRT" in cleaned or "BR>" in cleaned):
        return True
    if "NEWFOUNDLAND" in cleaned:
        return True
    return False

# ---------------------------------------------------------------------------
# State machine parser
# ---------------------------------------------------------------------------

class AHSVenueStateMachine:
    def __init__(self):
        self.venues = []
        self._reset()
        self.started = False  # Track if we passed the first header (ignoring intro text)

    def _reset(self):
        self.name = ""
        self.address_lines = []
        self.city = ""
        self.state = ""
        self.zip = ""
        self.phone = ""
        self.website = ""
        self.has_zip_line = False

    def _flush(self):
        if self.name:
            # Combine address lines into a full address
            addr = ", ".join(self.address_lines).strip()
            if not addr:
                addr = f"{self.city}, {self.state} {self.zip}".strip()

            self.venues.append({
                "name": self.name.strip(),
                "address": addr,
                "city": self.city.strip(),
                "state": self.state.strip(),
                "zip": self.zip.strip(),
                "phone": self.phone.strip(),
                "email": "",
                "website": self.website.strip(),
                "individual_memberships": "Free admission and/or discounts to AHS Reciprocal Garden members.",
                "group_memberships": "",
                "proof_of_residence": 0,
            })
        self._reset()

    def process_line(self, line: str):
        stripped = line.strip()
        if not stripped:
            return

        # Check for section or state headers to trigger a reset/flush
        if is_ahs_category_or_state_header(stripped):
            self.started = True
            self._flush()
            return

        if not self.started:
            # Ignore intro text before the first section header
            return

        # ZIP/Postal Line (City, State ZIP)
        zip_match = ZIP_PATTERN.match(stripped)
        if zip_match:
            self.city = zip_match.group(1).strip()
            self.state = normalize_state(zip_match.group(2).strip())
            self.zip = zip_match.group(3).strip()
            self.address_lines.append(stripped)
            self.has_zip_line = True
            return

        # Phone Line
        if PHONE_PATTERN.match(stripped):
            # Clean up OCR issues (sometimes (s) or weird character at end)
            self.phone = stripped
            return

        # Website Line
        if URL_PATTERN.match(stripped):
            # Clean up OCR errors in URL (e.g. hbp:// -> http://, hbps:// -> https://)
            url = stripped
            if url.startswith("hbp://"):
                url = "http://" + url[6:]
            elif url.startswith("hbps://"):
                url = "https://" + url[7:]
            self.website = url
            return

        # Email Line
        if EMAIL_PATTERN.match(stripped):
            return

        # General Line (either a Name or a Street Address line)
        if self.has_zip_line:
            # We already have a ZIP line, which means this line is the start of a new venue!
            self._flush()
            self.name = stripped
        else:
            # We are building the current venue
            if not self.name:
                self.name = stripped
            else:
                self.address_lines.append(stripped)

    def finalize(self) -> list[dict]:
        self._flush()
        return self.venues

# ---------------------------------------------------------------------------
# Main parser orchestrator
# ---------------------------------------------------------------------------

def clean_ocr_text(s: str) -> str:
    """Clean up typical OCR ligature errors and spelling mistakes in the PDF text stream."""
    # Smart quotes and general characters
    s = s.replace("’", "'").replace("‘", "'")
    
    # State-specific spelling / ligature fixes
    s = s.replace("MassachuseGs", "Massachusetts").replace("Massachusebs", "Massachusetts")
    s = s.replace("ConnecAcut", "Connecticut").replace("Connec>cut", "Connecticut").replace("ConnecaCut", "Connecticut")
    s = s.replace("BriAsh", "British").replace("Bri>sh", "British")
    
    # General word spelling corrections
    s = s.replace("Fayebeville", "Fayetteville")
    s = s.replace("Libleton", "Littleton")
    s = s.replace("Bable Creek", "Battle Creek").replace("Bable", "Battle")
    s = s.replace("Mabhaei", "Matthaei")
    s = s.replace("Bartleb", "Bartlett")
    s = s.replace("Bancrom", "Bancroft")
    s = s.replace("Charlobe", "Charlotte")
    s = s.replace("Howleb", "Howlett")
    s = s.replace("Jeweb", "Jewett")
    s = s.replace("Plunkeb", "Plunkett")
    s = s.replace("Martuck", "Mattituck")
    s = s.replace("Landcram", "Landcraft")
    s = s.replace("Seable", "Seattle")
    s = s.replace("CincinnaA", "Cincinnati")
    s = s.replace("Grand JuncAon", "Grand Junction")
    s = s.replace("ConvenAon", "Convention")
    s = s.replace("AssociaAon", "Association")
    s = s.replace("PenitenAary", "Penitentiary")
    s = s.replace("PresidenAal", "Presidential")
    s = s.replace("NaAonal", "National")
    s = s.replace("HorAcultural", "Horticultural").replace("horAcultural", "horticultural")
    s = s.replace("ParAcipaAng", "Participating").replace("parAcipaAng", "participating")
    s = s.replace("sApulaAons", "stipulations")
    s = s.replace("FoundaAon", "Foundation")
    
    # Additional OCR corrections
    s = s.replace("MeeAnghouse", "Meetinghouse")
    s = s.replace("Corpus ChrisA", "Corpus Christi")
    s = s.replace("InternaAonal", "International")
    s = s.replace("ReflecAon", "Reflection")
    s = s.replace("CanAgny", "Cantigny")
    s = s.replace("Paberson", "Patterson")
    s = s.replace("Pibsburgh", "Pittsburgh")
    s = s.replace("Chabanooga", "Chattanooga")
    s = s.replace("Buberfly", "Butterfly")
    s = s.replace("Nebleton", "Nettleton")
    
    # Parenthetical/outlier cleanup
    if "actually gets you to the site" in s:
        return ""

    return s

def is_valid_venue(v: dict) -> bool:
    if not v["name"] or not v["address"]:
        return False
    # Check if name looks like a URL/email or is too short
    name_lower = v["name"].lower()
    if any(x in name_lower for x in ["http://", "https://", "hbp://", "hbps://", "www.", ".org", ".com", ".net", "@"]):
        return False
    if len(v["name"].strip()) < 4:
        return False
    # Check if address has letters or digits
    clean_addr = v["address"].replace(",", "").strip()
    if not clean_addr or len(clean_addr) < 5:
        return False
    return True

def parse_ahs_pdf(pdf_path: str | Path) -> list[dict]:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print(f"Parsing AHS PDF: {pdf_path}")
    all_lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                all_lines.extend(text.split("\n"))

    print(f"  Extracted {len(all_lines)} raw lines")

    sm = AHSVenueStateMachine()
    for line in all_lines:
        cleaned = clean_ocr_text(line)
        if cleaned:
            sm.process_line(cleaned)

    venues = sm.finalize()
    
    # Filter: Must be a valid venue
    valid = [v for v in venues if is_valid_venue(v)]
    skipped = len(venues) - len(valid)

    print(f"  Parsed {len(valid)} venues with addresses ({skipped} skipped)")
    return valid

if __name__ == "__main__":
    import json
    import sys

    pdf_file = sys.argv[1] if len(sys.argv) > 1 else "data/pdfs/ahs_temp.pdf"
    venues = parse_ahs_pdf(pdf_file)
    print(json.dumps(venues[:5], indent=2))
    print(f"\nTotal valid venues: {len(venues)}")
