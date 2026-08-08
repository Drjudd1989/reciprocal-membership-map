import pdfplumber

with pdfplumber.open("data/pdfs/aza.pdf") as pdf:
    for i, page in enumerate(pdf.pages):
        print(f"\n================ PAGE {i+1} ================")
        w = page.width
        h = page.height
        print(f"Page width: {w}, height: {h}")
        
        words = page.extract_words()
        print(f"Total words: {len(words)}")
        
        # Let's print some sample words that represent columns
        print("Sample words and their horizontal start positions (x0):")
        # Find words on a few lines to check coordinates
        # Let's group words by top coordinate (line)
        lines = {}
        for wd in words:
            top_rounded = round(wd['top'], 1)
            # Find close tops
            matched = False
            for k in lines.keys():
                if abs(k - top_rounded) < 2:
                    lines[k].append(wd)
                    matched = True
                    break
            if not matched:
                lines[top_rounded] = [wd]
                
        # Sort lines by top coordinate
        sorted_tops = sorted(lines.keys())
        for top in sorted_tops[:15]:
            line_words = sorted(lines[top], key=lambda w: w['x0'])
            line_str = " ".join([f"x0={w['x0']:.1f}..{w['x1']:.1f}:{w['text']}" for w in line_words])
            print(f"  top={top:.1f} | {line_str}")
