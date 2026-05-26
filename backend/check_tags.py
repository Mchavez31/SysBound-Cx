from database_connection import SessionLocal
from models.database import Drawing
from services import pdf_parser

db = SessionLocal()
d = db.query(Drawing).filter(Drawing.id.like('6d000768%')).first()

if d:
    print(f"Drawing: {d.drawing_number}")
    result = pdf_parser.extract_all(d.file_path)
    
    print(f"\nTotal tags found: {len(result['tags'])}")
    print(f"Total pages: {result.get('page_count', 0)}")
    print(f"Subsystem labels found: {result.get('label_count', 0)}")
    
    page_178_tags = [t for t in result['tags'] if t.get('page_number') == 178]
    print(f"\nTags on page 178: {len(page_178_tags)}")
    
    print("\nFirst 15 tags on page 178:")
    for t in page_178_tags[:15]:
        color = t.get('tag_fill_color', 'N/A')
        subsystem = t.get('nearest_subsystem', 'N/A')
        print(f"  {t['tag_number']:20s} | color: {color:10s} | subsystem: {subsystem}")
else:
    print("Drawing not found")

db.close()
