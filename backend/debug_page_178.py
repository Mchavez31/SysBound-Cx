import pdfplumber
from database_connection import SessionLocal
from models.database import Drawing

# Get the drawing
db = SessionLocal()
d = db.query(Drawing).filter(Drawing.id.like('6d000768%')).first()

if d and d.file_path:
    print(f"Analyzing: {d.drawing_number}")
    print(f"File: {d.file_path}\n")
    
    with pdfplumber.open(d.file_path) as pdf:
        if len(pdf.pages) >= 178:
            page = pdf.pages[177]  # 0-indexed
            print("=" * 80)
            print("PAGE 178 TEXT CONTENT (first 3000 characters):")
            print("=" * 80)
            text = page.extract_text()
            print(text[:3000] if text else "No text found")
            print("\n" + "=" * 80)
            print("SEARCHING FOR SPECIFIC TAGS:")
            print("=" * 80)
            
            search_tags = ['XV-9881520', 'XV-9881521', 'ZIO-9881715', 'S-98840', 'V-98815']
            for tag in search_tags:
                if text and tag in text:
                    print(f"✓ FOUND: {tag}")
                    # Show context
                    idx = text.index(tag)
                    context = text[max(0, idx-30):min(len(text), idx+30)]
                    print(f"  Context: ...{context}...")
                else:
                    print(f"✗ NOT FOUND: {tag}")
        else:
            print(f"PDF only has {len(pdf.pages)} pages")
else:
    print("Drawing not found")

db.close()
