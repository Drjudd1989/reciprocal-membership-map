"""
parse_astc.py — ASTC Passport Program PDF parser.

Handles the two-column, state-sectioned format of the ASTC Compact List PDF.
Returns a list of venue dicts ready for DB insertion.

Parsing strategy:
  - Extract each page's left and right columns separately (bounding box)
  - Identify state banners (all-caps, known state names)
  - Within each state section, use a stateful parser that tracks
    membership sections to correctly handle multi-line membership lists
"""

import re
import pdfplumber
from pathlib import Path


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

STATE_PATTERN = re.compile(r"^[A-Z][A-Z\s]{2,24}$")

# Full address: "Street, City, ST ZIPCODE"
ADDRESS_PATTERN = re.compile(
    r".+,\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?$"
)

# City + state abbreviation only (for partial addresses)
CITY_STATE_ZIP = re.compile(r"^(.+),\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$")

# Phone
PHONE_PATTERN = re.compile(r"^\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}")

# URL
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

# Email
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Membership section labels
INDIVIDUAL_PATTERN = re.compile(r"^Individual Membership\(s\):\s*(.*)", re.IGNORECASE)
GROUP_PATTERN = re.compile(r"^Group Membership\(s\):\s*(.*)", re.IGNORECASE)
RECIPROCAL_HEADER = re.compile(r"^Reciprocal Membership\(s\)$", re.IGNORECASE)
PROOF_PATTERN = re.compile(r"proof of residence required", re.IGNORECASE)

# Lines that are clearly continuation/field types (not venue names)
CONTINUATION_PATTERNS = [
    PHONE_PATTERN,
    URL_PATTERN,
    EMAIL_PATTERN,
    ADDRESS_PATTERN,
    INDIVIDUAL_PATTERN,
    GROUP_PATTERN,
    RECIPROCAL_HEADER,
    PROOF_PATTERN,
]

# Known state / territory / country names used as banners
KNOWN_BANNERS = {
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
    "PUERTO RICO", "CANADA", "UNITED KINGDOM", "AUSTRALIA", "BERMUDA",
    "CAYMAN ISLANDS", "CHILE", "MEXICO", "NEW ZEALAND", "SINGAPORE",
}

# Words that indicate a line is a membership continuation (not a venue name)
MEMBERSHIP_WORDS = re.compile(
    r"\b(membership|member|patron|benefactor|director|family|individual|"
    r"dual|couple|student|senior|young|premium|standard|basic|deluxe|"
    r"plus|elite|charter|foundation|society|circle|level|tier|annual|"
    r"lifetime|sustaining|supporting|contributing|general)\b",
    re.IGNORECASE
)


def is_state_banner(line: str) -> bool:
    return line.strip() in KNOWN_BANNERS


def is_continuation(line: str) -> bool:
    """Return True if this line is clearly a field/continuation, not a venue name."""
    return any(p.search(line) if hasattr(p, 'search') else p.match(line)
               for p in CONTINUATION_PATTERNS)


def looks_like_membership_continuation(line: str) -> bool:
    """
    Return True if this line looks like the continuation of a membership list
    (e.g., "Patron Level Membership, Benefactor Level Membership").
    These have lots of membership-related words and commas.
    """
    # Must have at least one membership keyword
    if not MEMBERSHIP_WORDS.search(line):
        return False
    # Often contains commas (list items)
    # Or starts lowercase (continuation)
    if line and line[0].islower():
        return True
    # Lines that are just a list of membership types end with "Membership"
    stripped = line.rstrip(", ")
    if MEMBERSHIP_WORDS.search(stripped.split(",")[-1].strip()):
        return True
    return False


def extract_columns(page) -> list[str]:
    """
    Extract left and right column text from a page.
    Using 53%/48% split points (with slight overlap) to avoid word truncation
    at the column boundary when words sit right on the 50% midpoint.
    """
    w = page.width
    h = page.height
    # Left column gets a little extra width to avoid clipping right-edge words
    left_text = page.within_bbox((0, 0, w * 0.53, h)).extract_text(
        x_tolerance=3, y_tolerance=3
    ) or ""
    # Right column starts slightly before center to catch any overflow
    right_text = page.within_bbox((w * 0.48, 0, w, h)).extract_text(
        x_tolerance=3, y_tolerance=3
    ) or ""
    return [left_text, right_text]


# ---------------------------------------------------------------------------
# State machine parser for a section of lines
# ---------------------------------------------------------------------------

class VenueStateMachine:
    """
    Stateful parser for a sequence of lines within a state section.
    Produces a list of venue dicts.
    """

    # Parser states
    IDLE = "idle"               # Between venues, looking for a name
    IN_VENUE_HEADER = "header"  # Got name, looking for address/phone/etc.
    IN_MEMBERSHIPS = "memberships"  # Inside Individual/Group membership block
    IN_PROOF = "proof"          # Seen Proof of Residence

    def __init__(self, state_name: str):
        self.state_name = state_name
        self.venues: list[dict] = []
        self._reset_venue()
        self.parse_state = self.IDLE
        self.membership_target: str | None = None  # 'individual' or 'group'

    def _reset_venue(self):
        self.current = {
            "name": "",
            "address": "",
            "city": "",
            "state": self.state_name,
            "zip": "",
            "phone": "",
            "email": "",
            "website": "",
            "individual_memberships": [],
            "group_memberships": [],
            "proof_of_residence": 0,
        }
        self.membership_target = None
        self.parse_state = self.IDLE

    def _flush(self):
        """Save current venue if it has a valid name."""
        if self.current["name"] and not self._is_junk_name(self.current["name"]):
            v = dict(self.current)
            v["individual_memberships"] = ", ".join(v["individual_memberships"])
            v["group_memberships"] = ", ".join(v["group_memberships"])
            self.venues.append(v)
        self._reset_venue()

    def _is_junk_name(self, name: str) -> bool:
        """Filter out false-positive venue names."""
        if len(name) < 4:
            return True
        # A name that is purely a membership type list is junk
        if looks_like_membership_continuation(name) and "," in name:
            return True
        # Pure membership words with no institution words
        institution_words = re.compile(
            r"\b(museum|center|centre|science|zoo|aquarium|garden|gardens|"
            r"park|institute|planetarium|observatory|nature|children|discovery|"
            r"exploreum|exploratoreum|exploratorium|school|college|university|"
            r"foundation|historic|history|arts|cultural|conservatory|"
            r"botanical|wildlife|refuge|reserve|sanctuary|space|rocket|"
            r"aviation|maritime|hall|house|manor|castle|estate)\b",
            re.IGNORECASE
        )
        if MEMBERSHIP_WORDS.search(name) and not institution_words.search(name):
            if name.lower().rstrip(" ,").endswith("membership"):
                return True
        return False

    def process_line(self, line: str):
        stripped = line.strip()
        if not stripped:
            return

        # --- Reciprocal Membership(s) header ---
        if RECIPROCAL_HEADER.match(stripped):
            self.parse_state = self.IN_MEMBERSHIPS
            self.membership_target = None
            return

        # --- Individual Membership(s): ... ---
        m = INDIVIDUAL_PATTERN.match(stripped)
        if m:
            self.parse_state = self.IN_MEMBERSHIPS
            self.membership_target = "individual"
            val = m.group(1).strip().rstrip(", ")
            if val:
                self.current["individual_memberships"].append(val)
            return

        # --- Group Membership(s): ... ---
        m = GROUP_PATTERN.match(stripped)
        if m:
            self.parse_state = self.IN_MEMBERSHIPS
            self.membership_target = "group"
            val = m.group(1).strip().rstrip(", ")
            if val:
                self.current["group_memberships"].append(val)
            return

        # --- Proof of residence ---
        if PROOF_PATTERN.search(stripped):
            self.current["proof_of_residence"] = 1
            self.parse_state = self.IN_VENUE_HEADER
            self.membership_target = None
            return

        # --- Inside membership section ---
        if self.parse_state == self.IN_MEMBERSHIPS and self.membership_target:
            # If this line is a known field type, it belongs to the next venue
            if (PHONE_PATTERN.match(stripped) or ADDRESS_PATTERN.match(stripped) or
                    EMAIL_PATTERN.match(stripped) or URL_PATTERN.match(stripped)):
                self._flush()
                self._process_header_line(stripped)
                self.parse_state = self.IN_VENUE_HEADER
            elif PROOF_PATTERN.search(stripped):
                self.current["proof_of_residence"] = 1
                self.parse_state = self.IN_VENUE_HEADER
                self.membership_target = None
            elif looks_like_membership_continuation(stripped):
                # Confirmed membership continuation
                if self.membership_target == "individual":
                    self.current["individual_memberships"].append(stripped.rstrip(", "))
                else:
                    self.current["group_memberships"].append(stripped.rstrip(", "))
            else:
                # Doesn't look like membership text — treat as new venue name
                self._flush()
                self.current["name"] = stripped
                self.parse_state = self.IN_VENUE_HEADER
                self.membership_target = None
            return

        # --- Normal header processing ---
        if self.parse_state in (self.IDLE, self.IN_VENUE_HEADER):
            # A field line
            if is_continuation(stripped):
                if self.parse_state == self.IDLE:
                    # Orphan field before we have a name — skip
                    return
                self._process_header_line(stripped)
                self.parse_state = self.IN_VENUE_HEADER
                return

            # Might be a venue name or a membership continuation line
            if self.parse_state == self.IN_VENUE_HEADER and self.current["address"]:
                # We already have address — this is likely a new venue name
                # But only if it doesn't look like a membership continuation
                if looks_like_membership_continuation(stripped):
                    # Orphan continuation — try to attach to last membership
                    if self.current["group_memberships"]:
                        self.current["group_memberships"].append(stripped.rstrip(", "))
                    elif self.current["individual_memberships"]:
                        self.current["individual_memberships"].append(stripped.rstrip(", "))
                    return
                # It's a new venue name
                self._flush()
                self.current["name"] = stripped
                self.parse_state = self.IN_VENUE_HEADER
            elif self.parse_state == self.IDLE or not self.current["name"]:
                self.current["name"] = stripped
                self.parse_state = self.IN_VENUE_HEADER
            else:
                # Continuation of name (some venue names span 2 lines)
                if not self.current["address"] and not self.current["phone"]:
                    self.current["name"] += " " + stripped
                else:
                    # Probably a new venue
                    self._flush()
                    self.current["name"] = stripped
                    self.parse_state = self.IN_VENUE_HEADER

    def _process_header_line(self, line: str):
        """Process a non-name, non-membership field line."""
        if ADDRESS_PATTERN.match(line):
            self.current["address"] = line
            m = CITY_STATE_ZIP.match(line)
            if m:
                self.current["zip"] = m.group(3)
                self.current["state"] = m.group(2)
                parts = m.group(1).rsplit(",", 1)
                self.current["city"] = parts[-1].strip() if len(parts) > 1 else ""
        elif PHONE_PATTERN.match(line) and not self.current["phone"]:
            self.current["phone"] = line
        elif EMAIL_PATTERN.match(line) and not self.current["email"]:
            self.current["email"] = line
        elif URL_PATTERN.match(line) and not self.current["website"]:
            self.current["website"] = line

    def finalize(self) -> list[dict]:
        self._flush()
        return self.venues


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_astc_pdf(pdf_path: str | Path) -> list[dict]:
    """
    Parse the ASTC Compact List PDF and return a list of venue dicts.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print(f"Parsing ASTC PDF: {pdf_path}")

    # Collect all lines from all pages/columns
    all_lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for col_text in extract_columns(page):
                if col_text:
                    all_lines.extend(col_text.split("\n"))

    print(f"  Extracted {len(all_lines)} raw lines")

    # Split by state banners and parse each state section
    venues: list[dict] = []
    current_state = None
    sm: VenueStateMachine | None = None

    for raw_line in all_lines:
        stripped = raw_line.strip()
        if not stripped:
            continue

        if is_state_banner(stripped):
            if sm:
                venues.extend(sm.finalize())
            current_state = stripped
            sm = VenueStateMachine(current_state)
        else:
            if sm is not None:
                sm.process_line(raw_line)
            # Lines before the first state banner are ignored (header content)

    if sm:
        venues.extend(sm.finalize())

    # Final filter: must have an address to be geocodeable
    valid = [v for v in venues if v["address"]]
    skipped = len(venues) - len(valid)

    print(f"  Parsed {len(valid)} venues with addresses ({skipped} skipped — no address)")
    return valid


if __name__ == "__main__":
    import json
    import sys

    pdf_file = sys.argv[1] if len(sys.argv) > 1 else "data/pdfs/astc.pdf"
    venues = parse_astc_pdf(pdf_file)
    print(json.dumps(venues[:5], indent=2))
    print(f"\nTotal valid venues: {len(venues)}")
