"""
parse_aza.py — AZA Reciprocal Network PDF parser.

Processes the landscape layout of the AZA Reciprocity PDF, sifting words into columns based on
horizontal coordinates and distinguishing new venues from continuation lines using the presence of
contact details.
"""

import re
import pdfplumber
from pathlib import Path

STATE_MAP = {
    # US States
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
    # Canadian Provinces
    "Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB", "New Brunswick": "NB",
    "Nova Scotia": "NS", "Ontario": "ON", "Quebec": "QC", "Saskatchewan": "SK"
}

def is_boilerplate(text: str) -> bool:
    text_lower = text.lower()
    phrases = [
        "always call",
        "current policies",
        "reciprocal admissions",
        "state city zoo",
        "contact name phone",
        "reciprocity list of aza",
        "chosen to participate",
        "reciprocal admission",
        "will reciprocate",
        "same discount that",
        "give your home zoo",
        "members.",
        "does not include",
        "free admission zoos",
        "green print-they",
        "look for your",
        "home zoo/aquarium",
        "receive a 50% discount",
        "except those in green",
        "100% or 50% in blue",
        "receive a 100% discount",
        "participating institutions",
        "close geographic proximity",
        "not required to offer",
        "each other's members",
        "reciprocal admissions program",
        "milwaukee county zoo",
        "henry vilas zoo, lincoln",
        "racine zoo. always call",
        "discretion of the",
        "honor entrance benefits",
        "always call ahead",
        "please note",
        "updated 5/"
    ]
    return any(p in text_lower for p in phrases)

def map_reciprocity_and_notes(recip_cell: str) -> tuple[str, str]:
    recip_lower = recip_cell.lower()
    
    if "free to public" in recip_lower or "free to the public" in recip_lower:
        discount = "Free admission to the public (reciprocal members may receive other discounts/benefits)."
        note = ""
        if "free to public" in recip_lower:
            idx = recip_lower.find("free to public") + len("free to public")
            note = recip_cell[idx:].strip()
        elif "free to the public" in recip_lower:
            idx = recip_lower.find("free to the public") + len("free to the public")
            note = recip_cell[idx:].strip()
        note = re.sub(r'^[-\s]+', '', note).strip()
        return discount, note
        
    elif "50%" in recip_lower:
        discount = "50% admission discount for members of participating AZA institutions."
        note = ""
        match = re.search(r'50%\s*(.*)', recip_cell)
        if match:
            note = match.group(1).strip()
        # Clean up any wrapping like "Limit 2" from parentheses
        note = re.sub(r'^[-\s]+', '', note).strip()
        return discount, note
        
    elif "100%" in recip_lower:
        discount = "Free admission (100% discount) for members of 100% reciprocal AZA institutions; 50% discount for members of 50% reciprocal AZA institutions."
        note = ""
        match = re.search(r'(?:100% OR 50%|100%)\s*(.*)', recip_cell, re.IGNORECASE)
        if match:
            note = match.group(1).strip()
        note = re.sub(r'^[-\s]+', '', note).strip()
        return discount, note
        
    else:
        discount = f"Reciprocal discount: {recip_cell}"
        return discount, ""

def parse_aza_pdf(pdf_path: str | Path = "data/pdfs/aza.pdf") -> list[dict]:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print(f"Parsing AZA PDF: {pdf_path}")
    venues = []
    
    current_state = None
    current_city = None
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            words = page.extract_words()
            
            # Group words into rows based on top coordinate clustering
            rows_dict = {}
            for w in words:
                # Ignore sidebar
                if w['x0'] >= 605:
                    continue
                # Ignore header lines (top < 70)
                if w['top'] < 70:
                    continue
                    
                top = w['top']
                # Cluster tops within 3 points
                matched_top = None
                for existing_top in rows_dict.keys():
                    if abs(existing_top - top) < 3:
                        matched_top = existing_top
                        break
                if matched_top is None:
                    rows_dict[top] = [w]
                else:
                    rows_dict[matched_top].append(w)
                    
            # Sort rows by top coordinate
            sorted_tops = sorted(rows_dict.keys())
            
            for top in sorted_tops:
                line_words = sorted(rows_dict[top], key=lambda w: w['x0'])
                line_text = " ".join([w['text'] for w in line_words]).strip()
                
                # Skip boilerplate text
                if is_boilerplate(line_text):
                    continue
                    
                # Sift words into columns based on x0 boundaries
                state_words = []
                city_words = []
                zoo_words = []
                recip_words = []
                contact_words = []
                phone_words = []
                
                for w in line_words:
                    x0 = w['x0']
                    text = w['text']
                    
                    if 15 <= x0 < 74:
                        state_words.append(text)
                    elif 74 <= x0 < 155:
                        city_words.append(text)
                    elif 155 <= x0 < 358:
                        zoo_words.append(text)
                    elif 358 <= x0 < 406:
                        recip_words.append(text)
                    elif 406 <= x0 < 496:
                        contact_words.append(text)
                    elif 496 <= x0 < 605:
                        phone_words.append(text)
                        
                state_cell = " ".join(state_words).strip()
                city_cell = " ".join(city_words).strip()
                zoo_cell = " ".join(zoo_words).strip()
                recip_cell = " ".join(recip_words).strip()
                contact_cell = " ".join(contact_words).strip()
                phone_cell = " ".join(phone_words).strip()
                
                if not state_cell and not city_cell and not zoo_cell and not recip_cell and not contact_cell and not phone_cell:
                    continue
                
                # A row represents a new venue if it contains contact details (name or phone)
                is_new_venue = bool(contact_cell or phone_cell)
                
                if is_new_venue:
                    # Update current state if provided
                    if state_cell:
                        current_state = state_cell.strip()
                    # Update current city if provided
                    if city_cell:
                        current_city = city_cell.strip()
                        
                    state_cleaned = current_state or ""
                    city_cleaned = current_city or ""
                    
                    # Clean up international/province prefixes
                    if "Calgary -Alberta" in city_cleaned:
                        state_cleaned = "Alberta"
                        city_cleaned = "Calgary"
                    elif "Granby - Quebec" in city_cleaned:
                        state_cleaned = "Quebec"
                        city_cleaned = "Granby"
                    elif "Winnipeg - Manitoba" in city_cleaned:
                        state_cleaned = "Manitoba"
                        city_cleaned = "Winnipeg"
                    elif "Toronto" in city_cleaned and ("CANADA" in state_cleaned or not state_cleaned):
                        state_cleaned = "Ontario"
                        city_cleaned = "Toronto"
                    elif "CANADA" in state_cleaned:
                        state_cleaned = state_cleaned.replace("CANADA", "").strip()
                    elif "COLOMBIA" in state_cleaned:
                        state_cleaned = "Colombia"
                    elif "MEXICO" in state_cleaned:
                        state_cleaned = "Mexico"
                        
                    state_code = STATE_MAP.get(state_cleaned, state_cleaned)
                    
                    name = zoo_cell
                    recip = recip_cell
                    
                    # Handle cases where FREE/FREE TO PUBLIC overflowed to the left and ended up in the name
                    for free_phrase in ["FREE TO PUBLIC", "Free TO PUBLIC", "FREE TO THE PUBLIC", "FREE", "Free"]:
                        if name.endswith(free_phrase):
                            name = name[:-len(free_phrase)].strip()
                            if recip:
                                recip = free_phrase + " " + recip
                            else:
                                recip = free_phrase
                            break
                    
                    # Clean up trailing dashes from name
                    name = re.sub(r'[-\s]+$', '', name).strip()
                    
                    discount, note = map_reciprocity_and_notes(recip)
                    
                    venues.append({
                        "name": name,
                        "address": f"{city_cleaned}, {state_code}",
                        "city": city_cleaned,
                        "state": state_code,
                        "zip": "",
                        "phone": phone_cell,
                        "email": "",
                        "website": "",
                        "individual_memberships": discount,
                        "group_memberships": note,
                        "proof_of_residence": 0
                    })
                else:
                    # Continuation line for the last venue
                    if venues:
                        # Combine any continuation text across Zoo and Reciprocity columns
                        cont_words = []
                        if zoo_cell:
                            cont_words.append(zoo_cell)
                        if recip_cell:
                            cont_words.append(recip_cell)
                            
                        continuation_text = " ".join(cont_words).strip()
                        if continuation_text and not is_boilerplate(continuation_text):
                            last_v = venues[-1]
                            
                            # Clean up leading dashes or spaces
                            continuation_text = re.sub(r'^[-\s]+', '', continuation_text).strip()
                            
                            if last_v["group_memberships"]:
                                last_v["group_memberships"] += " " + continuation_text
                            else:
                                last_v["group_memberships"] = continuation_text

    print(f"  Parsed {len(venues)} AZA venues")
    return venues

if __name__ == "__main__":
    import sys
    pdf = "data/pdfs/aza.pdf"
    if len(sys.argv) > 1:
        pdf = sys.argv[1]
    res = parse_aza_pdf(pdf)
    print(f"Sample parsed venues (first 10):")
    for v in res[:10]:
        print(f"  Name: {v['name']}")
        print(f"  City/State: {v['city']}, {v['state']}")
        print(f"  Indiv discount: {v['individual_memberships']}")
        print(f"  Group/Notes: {v['group_memberships']}")
        print(f"  Phone/Email: {v['phone']}")
        print("-" * 40)
