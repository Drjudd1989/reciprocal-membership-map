import pdfplumber

with pdfplumber.open("data/pdfs/aza.pdf") as pdf:
    # Let's inspect pages 3 and 4
    for idx in [2, 3]:
        page = pdf.pages[idx]
        w = page.width
        h = page.height
        
        # Crop to the table area (left 600 points)
        cropped = page.within_bbox((0, 0, 600, h))
        text = cropped.extract_text()
        
        print(f"\n================ PAGE {idx+1} (CROPPED) ================")
        if text:
            lines = text.split("\n")
            print(f"Total lines: {len(lines)}")
            for line in lines[:30]:
                print(f"  {line}")
        else:
            print("  No text extracted!")
