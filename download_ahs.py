import urllib.request
from pathlib import Path

pdf_dir = Path("data/pdfs")
pdf_dir.mkdir(parents=True, exist_ok=True)

url = "https://ahsgardening.org/wp-content/uploads/2026/05/AHS-Garden-Network-List-5.21.26.pdf"
dest = pdf_dir / "ahs_temp.pdf"

print(f"Downloading AHS PDF from {url}...")
try:
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ReciprocalMembershipMap/1.0'}
    )
    with urllib.request.urlopen(req) as response:
        dest.write_bytes(response.read())
    print(f"Saved AHS PDF to {dest} ({dest.stat().st_size} bytes)")
except Exception as e:
    print(f"Failed to download AHS PDF: {e}")
