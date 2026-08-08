import pdfplumber

with pdfplumber.open("data/pdfs/aza.pdf") as pdf:
    page = pdf.pages[2] # Page 3
    h = page.height
    
    # Define vertical columns
    # We ignore headers at the top by starting y0 around 70
    col_state = page.within_bbox((15, 70, 74, h)).extract_text() or ""
    col_city = page.within_bbox((74, 70, 155, h)).extract_text() or ""
    col_zoo = page.within_bbox((155, 70, 360, h)).extract_text() or ""
    col_recip = page.within_bbox((360, 70, 406, h)).extract_text() or ""
    col_phone = page.within_bbox((496, 70, 600, h)).extract_text() or ""
    
    print("--- STATE COLUMN ---")
    print(col_state.split("\n")[:15])
    
    print("\n--- CITY COLUMN ---")
    print(col_city.split("\n")[:15])
    
    print("\n--- ZOO COLUMN ---")
    print(col_zoo.split("\n")[:15])
    
    print("\n--- RECIPROCITY COLUMN ---")
    print(col_recip.split("\n")[:15])
