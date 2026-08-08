"""
geocode.py — Nominatim geocoding helper with rate limiting and fallback logic.
Respects Nominatim ToS: 1 request/second, descriptive User-Agent.
"""

import time
import requests
import os
import re
from dotenv import load_dotenv

load_dotenv()

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_EMAIL = os.getenv("NOMINATIM_EMAIL", "toolsbyjudd@gmail.com")
HEADERS = {
    "User-Agent": f"ReciprocalMembershipMap/1.0 ({NOMINATIM_EMAIL})"
}

def _query_nominatim(query: str) -> tuple[float, float] | None:
    """Helper to perform the raw HTTP request to Nominatim."""
    if not query or not query.strip():
        return None

    params = {
        "q": query,
        "format": "json",
        "limit": 1,
    }

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params=params,
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()

        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])

    except requests.RequestException as e:
        print(f"  [NOMINATIM ERROR] for {query!r}: {e}")
    except (ValueError, KeyError, IndexError) as e:
        print(f"  [NOMINATIM PARSE ERROR] for {query!r}: {e}")

    return None

def clean_address(address: str) -> str:
    if not address:
        return ""
    # Standardize spaces and smart quotes
    addr = address.replace("’", "'").replace("‘", "'").strip()
    
    # Remove room/suite/floor/unit/building/#/apartment info
    # E.g., "Room 202", "Ste 4", "Suite A", "# 12", "#12", "Unit B", "Rm 5"
    addr = re.sub(r'\b(room|rm|suite|ste|floor|fl|unit|apt|apartment|dept|department|building|bldg|box)\b\.?\s*\w+\b', '', addr, flags=re.I)
    addr = re.sub(r'#\s*\w+\b', '', addr)
    
    # Remove parenthetical info or specific extra phrases
    addr = re.sub(r'\(.*?\)', '', addr)
    addr = re.sub(r'\bAlong the River Trail\b', '', addr, flags=re.I)
    
    # Strip leading words before street numbers (e.g. "Grant Park 567 S Poli Street" -> "567 S Poli Street")
    addr = re.sub(r'^[a-zA-Z\s,]+\s+(\d+)\s+', r'\1 ', addr)
    
    # Replace spelled out starting numbers like "One" -> "1"
    addr = re.sub(r'^One\b', '1', addr, flags=re.I)
    addr = re.sub(r'^Two\b', '2', addr, flags=re.I)
    addr = re.sub(r'^Three\b', '3', addr, flags=re.I)
    addr = re.sub(r'^Four\b', '4', addr, flags=re.I)
    addr = re.sub(r'^Five\b', '5', addr, flags=re.I)
    
    # Replace ordinal word numbers (First -> 1st, Second -> 2nd, etc.)
    ordinals = {
        "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th",
        "sixth": "6th", "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th"
    }
    for word, digit in ordinals.items():
        addr = re.sub(r'\b' + word + r'\b', digit, addr, flags=re.I)
        
    # Replace OCR "oo" / "o" in numbers (e.g. 18oo -> 1800)
    addr = re.sub(r'\b(\d+)[oO]+\b', lambda m: m.group(1) + '0' * (len(m.group(0)) - len(m.group(1))), addr)
    
    # Fix common abbreviations
    addr = re.sub(r'\bState Hw\.?\s*(\d+)', r'State Highway \1', addr, flags=re.I)
    addr = re.sub(r'\bState Hwy\b\.?', 'State Highway', addr, flags=re.I)
    addr = re.sub(r'\bFt\b\.?', 'Fort', addr, flags=re.I)
    
    # Clean up double commas, trailing/leading commas and spaces
    addr = re.sub(r',\s*,', ',', addr)
    addr = re.sub(r'\s+', ' ', addr)
    addr = addr.strip(", ")
    
    return addr

def clean_name(name: str) -> str:
    if not name:
        return ""
    n = name.replace("’", "'").replace("‘", "'").strip()
    
    # Strip leading "The " (case-insensitive)
    n = re.sub(r'^The\s+', '', n, flags=re.I)
    
    # Strip possessive prefixes like "Frank Lloyd Wright's Graycliff" -> "Graycliff"
    n = re.sub(r"^[a-zA-Z\s']+\'s\s+", "", n)
    
    # Fix typical OCR ligature errors
    ocr_fixes = {
        "NaAonal": "National",
        "ReflecAon": "Reflection",
        "Corpus ChrisA": "Corpus Christi",
        "InternaAonal": "International",
        "MeeAnghouse": "Meetinghouse",
        "CincinnaA": "Cincinnati",
        "Grand JuncAon": "Grand Junction",
        "HorAcultural": "Horticultural",
        "horAcultural": "horticultural",
        "ParAcipaAng": "Participating",
        "parAcipaAng": "participating",
        "sApulaAons": "stipulations",
        "FoundaAon": "Foundation",
        "PenitenAary": "Penitentiary",
        "PresidenAal": "Presidential",
        "ConnecAcut": "Connecticut",
        "AssociaAon": "Association",
        "ConvenAon": "Convention",
        "Paberson": "Patterson",
        "Pibsburgh": "Pittsburgh",
        "Chabanooga": "Chattanooga",
        "Buberfly": "Butterfly",
        "CanAgny": "Cantigny"
    }
    for bad, good in ocr_fixes.items():
        n = n.replace(bad, good)
        
    return n.strip()

def geocode_address(address: str, name: str = None, city: str = None, state: str = None) -> tuple[float, float] | None:
    """
    Geocode an address string using Nominatim, with robust fallback strategies.
    
    Returns (latitude, longitude) tuple or None on failure.
    IMPORTANT: Caller must sleep(1) between calls to respect ToS rate limit.
    """
    if not address or not address.strip():
        return None

    cleaned_addr = clean_address(address)
    cleaned_name = clean_name(name) if name else None

    # Try 1: Cleaned address
    result = _query_nominatim(cleaned_addr)
    if result:
        return result

    # Try 2: Landmark/Name query (Name, City, State)
    if cleaned_name and city and state:
        cleaned_city = city.replace("University", "").strip() if "University" in city else city
        query_2 = f"{cleaned_name}, {cleaned_city}, {state}"
        print(f"  [GEOCODE FALLBACK 1] trying: {query_2}")
        time.sleep(1)
        result = _query_nominatim(query_2)
        if result:
            return result

    # Try 3: Simplified address query (removes intermediate campus/university labels)
    parts = [p.strip() for p in cleaned_addr.split(",")]
    if len(parts) >= 3:
        simplified = f"{parts[0]}, {parts[-2]}, {parts[-1]}"
        if simplified != cleaned_addr:
            print(f"  [GEOCODE FALLBACK 2] trying simplified address: {simplified}")
            time.sleep(1)
            result = _query_nominatim(simplified)
            if result:
                return result

    # Try 4: Landmark/Name query (Name, State)
    if cleaned_name and state:
        query_4 = f"{cleaned_name}, {state}"
        print(f"  [GEOCODE FALLBACK 3] trying state-based: {query_4}")
        time.sleep(1)
        result = _query_nominatim(query_4)
        if result:
            return result

    # Try 5: Landmark/Name query (Name only)
    if cleaned_name:
        print(f"  [GEOCODE FALLBACK 4] trying global name: {cleaned_name}")
        time.sleep(1)
        result = _query_nominatim(cleaned_name)
        if result:
            return result

    # Try 6: Simplified Name (first part of name split by - or : or & or "and" or comma) + City + State
    if cleaned_name and city and state:
        simplified_name = re.split(r'[\-:&,()]|\band\b', cleaned_name, flags=re.I)[0].strip()
        if simplified_name != cleaned_name and len(simplified_name) > 3:
            query_6 = f"{simplified_name}, {city}, {state}"
            print(f"  [GEOCODE FALLBACK 5] trying: {query_6}")
            time.sleep(1)
            result = _query_nominatim(query_6)
            if result:
                return result

    # Try 7: Street + State (no house number, no city)
    if len(parts) >= 2:
        street = parts[0]
        street_no_num = re.sub(r'^\d+\s*', '', street).strip()
        state_part = parts[-1]
        if street_no_num and street_no_num != street and len(street_no_num) > 3:
            query_7 = f"{street_no_num}, {state_part}"
            print(f"  [GEOCODE FALLBACK 6] trying street + state: {query_7}")
            time.sleep(1)
            result = _query_nominatim(query_7)
            if result:
                return result

    # Try 8: University/College Name + State (if name contains university/college)
    if cleaned_name and state:
        if "University" in cleaned_name or "College" in cleaned_name:
            uni_match = re.search(r'\b([a-zA-Z\s]+University|[a-zA-Z\s]+College)\b', cleaned_name, re.I)
            if uni_match:
                query_8 = f"{uni_match.group(1)}, {state}"
                print(f"  [GEOCODE FALLBACK 7] trying university + state: {query_8}")
                time.sleep(1)
                result = _query_nominatim(query_8)
                if result:
                    return result

    # Try 9: City + State + Zip (last resort)
    if city and state:
        zip_part = parts[-1].split()[-1] if len(parts) > 0 and parts[-1].split() and parts[-1].split()[-1].isdigit() else ""
        query_9 = f"{city}, {state}"
        if zip_part and len(zip_part) == 5:
            query_9 += f" {zip_part}"
        print(f"  [GEOCODE FALLBACK 8] trying city + state + zip (last resort): {query_9}")
        time.sleep(1)
        result = _query_nominatim(query_9)
        if result:
            return result

    return None

def geocode_with_rate_limit(address: str, name: str = None, city: str = None, state: str = None) -> tuple[float, float] | None:
    """
    Geocode with built-in 1-second delay after the final call.
    Use this in batch loops so the caller doesn't need to manage the sleep.
    """
    result = geocode_address(address, name=name, city=city, state=state)
    time.sleep(1)  # Nominatim ToS: max 1 request/second
    return result
