"""
parse_acm.py — ACM Reciprocal Network PDF parser.

Handles the 3-column layout of the ACM Reciprocal List PDF.
Returns a list of venue dicts ready for DB insertion.
"""

import re
import pdfplumber
from pathlib import Path

# US States and territories
US_STATES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming", "District of Columbia"
}

ALL_HEADERS = US_STATES.union({"International", "Canada", "US Virgin Islands", "U.S. Virgin Islands"})

def parse_acm_pdf(pdf_path: str | Path) -> list[dict]:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print(f"Parsing ACM PDF: {pdf_path}")
    venues = []
    current_section = None
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            w = page.width
            h = page.height
            
            # Divide each page into 3 columns
            col1 = page.within_bbox((0, 0, w * 0.35, h)).extract_text() or ""
            col2 = page.within_bbox((w * 0.35, 0, w * 0.68, h)).extract_text() or ""
            col3 = page.within_bbox((w * 0.68, 0, w, h)).extract_text() or ""
            
            for col_idx, col_text in enumerate([col1, col2, col3]):
                lines = col_text.split("\n")
                buffer = []
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                        
                    # Skip page 1 intro/boilerplate
                    if "membership card" in line or "Reciprocal Network" in line or "brochure to receive" in line or "Enjoy your visit!" in line or "Remember:" in line or "You must have" in line or "ID may be required" in line or "Verify museum" in line or "Questions about" in line:
                        continue
                    if line.startswith(chr(65533)) or line.startswith("•"):
                        continue
                    if "www.childrensmuseums.org" in line or "Administered by the Association" in line:
                        continue
                        
                    # Check if it's a section header
                    if line in ALL_HEADERS:
                        if buffer:
                            process_buffer(buffer, current_section, venues)
                            buffer = []
                        if line != "International":
                            current_section = line
                        continue
                        
                    if not current_section:
                        continue
                        
                    buffer.append(line)
                    
                    # Buffer flush heuristic
                    if len(buffer) > 0:
                        last_line = buffer[-1]
                        if "," in last_line:
                            parts = [p.strip() for p in last_line.split(",")]
                            last_part = parts[-1]
                            
                            # U.S. Virgin Islands line wrap check
                            if last_part == "U.S.":
                                continue
                                
                            # Flush if the line ends with a valid capitalized city/state word
                            if re.match(r'^[A-Z][a-zA-Z\s\'.]+$', last_part) and not any(x in last_part for x in ["Inc", "aka", "Children's", "Museum", "programs", "Greentrike"]):
                                is_us = current_section in US_STATES
                                full_so_far = " ".join(buffer)
                                commas_count = full_so_far.count(",")
                                
                                if is_us and commas_count >= 1:
                                    process_buffer(buffer, current_section, venues)
                                    buffer = []
                                elif not is_us and commas_count >= 2:
                                    process_buffer(buffer, current_section, venues)
                                    buffer = []
                                    
                if buffer:
                    process_buffer(buffer, current_section, venues)
                    
    print(f"  Parsed {len(venues)} ACM venues")
    return venues

def process_buffer(buffer, section, venues):
    full_text = " ".join(buffer).strip()
    if not full_text:
        return
        
    is_us = section in US_STATES
    
    if is_us:
        # Format: Name, City
        if "," in full_text:
            parts = [p.strip() for p in full_text.split(",")]
            city = parts[-1]
            name = ", ".join(parts[:-1]).strip()
            state = section
            
            # Normalization
            name = re.sub(r'\s+', ' ', name).replace("P rovidence", "Providence")
            city = re.sub(r'\s+', ' ', city)
            
            state_map = {
                "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
                "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
                "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
                "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
                "Massachusetts": "MA", "MICHIGAN": "MI", "Minnesota": "MN", "Mississippi": "MS",
                "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
                "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
                "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
                "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
                "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
                "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC"
            }
            state_code = state_map.get(state, state)
            
            venues.append({
                "name": name,
                "address": f"{city}, {state_code}",
                "city": city,
                "state": state_code,
                "zip": "",
                "phone": "",
                "email": "",
                "website": "",
                "individual_memberships": "50% off general admission for up to six (6) people, including the cardholder.",
                "group_memberships": "",
                "proof_of_residence": 0
            })
    else:
        # Format: Name, City, State/Province (e.g. London Regional Children's Museum, London, Ontario)
        parts = [p.strip() for p in full_text.split(",")]
        if len(parts) >= 3:
            state_prov = parts[-1]
            city = parts[-2]
            name = ", ".join(parts[:-2]).strip()
            
            # Normalizations
            name = re.sub(r'\s+', ' ', name)
            city = re.sub(r'\s+', ' ', city)
            state_prov = re.sub(r'\s+', ' ', state_prov)
            
            if state_prov.lower() == "ontario":
                state_code = "ON"
            elif "virgin islands" in state_prov.lower():
                state_code = "VI"
            else:
                state_code = state_prov
                
            venues.append({
                "name": name,
                "address": f"{city}, {state_code}",
                "city": city,
                "state": state_code,
                "zip": "",
                "phone": "",
                "email": "",
                "website": "",
                "individual_memberships": "50% off general admission for up to six (6) people, including the cardholder.",
                "group_memberships": "",
                "proof_of_residence": 0
            })
