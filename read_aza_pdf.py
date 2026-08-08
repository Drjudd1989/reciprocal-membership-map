import pdfplumber

with pdfplumber.open("data/pdfs/aza.pdf") as pdf:
    print(f"Total pages: {len(pdf.pages)}")
    for i, page in enumerate(pdf.pages):
        print(f"\n--- Page {i+1} ---")
        text = page.extract_text()
        if text:
            lines = text.split("\n")
            print(f"Lines count: {len(lines)}")
            for line in lines[:40]:
                print(f"  {line}")
        else:
            print("  No text extracted!")
