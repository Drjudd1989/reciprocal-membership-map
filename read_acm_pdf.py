import pdfplumber

with pdfplumber.open("data/pdfs/acm.pdf") as pdf:
    print(f"Total pages: {len(pdf.pages)}")
    for i, page in enumerate(pdf.pages):
        print(f"\n--- Page {i+1} ---")
        text = page.extract_text()
        if text:
            lines = text.split("\n")
            print(f"Lines count: {len(lines)}")
            # Print the first 25 lines
            for line in lines[:25]:
                print(f"  {line}")
        else:
            print("  No text extracted!")
