import pdfplumber
import re

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

def parse_aza_pdf(pdf_path="data/pdfs/aza.pdf"):
    venues = []
    
    current_state = None
    current_city = None
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            h = page.height
            words = page.extract_words()
            
            # Group words into rows based on top coordinate clustering
            rows_dict = {}
            for w in words:
                # Ignore sidebar
                if w['x0'] >= 605:
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
                
                # Sift words into columns
                state_words = []
                city_words = []
                zoo_words = []
                recip_words = []
                
                for w in line_words:
                    x0 = w['x0']
                    text = w['text']
                    
                    if 15 <= x0 < 74:
                        state_words.append(text)
                    elif 74 <= x0 < 155:
                        city_words.append(text)
                    elif 155 <= x0 < 360:
                        zoo_words.append(text)
                    elif 360 <= x0 < 406:
                        recip_words.append(text)
                        
                state_cell = " ".join(state_words).strip()
                city_cell = " ".join(city_words).strip()
                zoo_cell = " ".join(zoo_words).strip()
                recip_cell = " ".join(recip_words).strip()
                
                # Skip headers
                if "State" in state_cell and "City" in city_cell:
                    continue
                if "Always call" in state_cell or "Always call" in city_cell or "current policies" in state_cell:
                    continue
                if not state_cell and not city_cell and not zoo_cell and not recip_cell:
                    continue
                    
                # If we have a reciprocity value, it's a new venue!
                if recip_cell:
                    # Update current state if provided
                    if state_cell:
                        current_state = state_cell.strip()
                    # Update current city if provided
                    if city_cell:
                        current_city = city_cell.strip()
                        
                    # Handle country prefix (e.g., "CANADA Calgary -Alberta")
                    # If state contains CANADA or COLOMBIA or MEXICO
                    state_cleaned = current_state or ""
                    city_cleaned = current_city or ""
                    
                    if "Calgary -Alberta" in city_cleaned:
                        state_cleaned = "Alberta"
                        city_cleaned = "Calgary"
                    elif "Granby - Quebec" in city_cleaned:
                        state_cleaned = "Quebec"
                        city_cleaned = "Granby"
                    elif "Winnipeg - Manitoba" in city_cleaned:
                        state_cleaned = "Manitoba"
                        city_cleaned = "Winnipeg"
                    elif "CANADA" in state_cleaned:
                        state_cleaned = state_cleaned.replace("CANADA", "").strip()
                    elif "COLOMBIA" in state_cleaned:
                        state_cleaned = "Colombia"
                    elif "MEXICO" in state_cleaned:
                        state_cleaned = "Mexico"
                        
                    state_code = STATE_MAP.get(state_cleaned, state_cleaned)
                    
                    # Determine membership discount text
                    recip_lower = recip_cell.lower()
                    if "50%" in recip_lower:
                        discount = "50% admission discount for members of participating AZA institutions."
                    elif "100%" in recip_lower:
                        discount = "Free admission (100% discount) for members of 100% reciprocal AZA institutions; 50% discount for members of 50% reciprocal AZA institutions."
                    elif "free" in recip_lower:
                        discount = "Free admission to the public (reciprocal members may receive other discounts/benefits)."
                    else:
                        discount = f"Reciprocal discount: {recip_cell}"
                        
                    venues.append({
                        "name": zoo_cell,
                        "address": f"{city_cleaned}, {state_code}",
                        "city": city_cleaned,
                        "state": state_code,
                        "zip": "",
                        "phone": "",
                        "email": "",
                        "website": "",
                        "individual_memberships": discount,
                        "group_memberships": "",
                        "proof_of_residence": 0,
                        "raw_recip": recip_cell
                    })
                else:
                    # It's a continuation line! Append to the last venue
                    if venues and zoo_cell:
                        last_v = venues[-1]
                        # Append the zoo cell to description or name?
                        # E.g. "15% discount in gift shop" -> append to description
                        # E.g. "Endangered Species Tour and" -> append to description
                        if "discount" in zoo_cell.lower() or "tour" in zoo_cell.lower() or "howl" in zoo_cell.lower() or "adventure" in zoo_cell.lower() or "pass" in zoo_cell.lower():
                            if last_v["group_memberships"]:
                                last_v["group_memberships"] += " " + zoo_cell
                            else:
                                last_v["group_memberships"] = zoo_cell
                        else:
                            # It's part of the zoo name (multiline name wrap)
                            last_v["name"] += " " + zoo_cell
                            
    return venues

venues = parse_aza_pdf()
print(f"Total venues parsed: {len(venues)}")
print("First 15 parsed venues:")
for v in venues[:15]:
    print(f"  {v['name']} | {v['city']}, {v['state']} | Recip: {v['raw_recip']} | Group: {v['group_memberships']}")
print("\nLast 15 parsed venues:")
for v in venues[-15:]:
    print(f"  {v['name']} | {v['city']}, {v['state']} | Recip: {v['raw_recip']} | Group: {v['group_memberships']}")
