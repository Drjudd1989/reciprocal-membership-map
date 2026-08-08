from scripts.parse_ahs import parse_ahs_pdf, clean_ocr_text
import re

pdf_path = "data/pdfs/AHS-Garden-Network-List-5.21.26.pdf"
venues = parse_ahs_pdf(pdf_path)
leila = [v for v in venues if "Leila" in v["name"]]
print("Parsed Leila venues:")
for l in leila:
    print(l)
