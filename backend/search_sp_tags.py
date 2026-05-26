import pdfplumber

pdf_path = 'uploads/9f620b32-96b2-42a5-bd5a-dce843dc93bc/supplemental_P_ID_Symbols_and_Legends.pdf'
with pdfplumber.open(pdf_path) as pdf:
    print(f"Total pages: {len(pdf.pages)}\n")
    
    # Search for SP/Specialty mentions
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ''
        if 'SP-' in text or 'SPECIALTY' in text.upper():
            print(f"=== Page {i+1} mentions SP/SPECIALTY ===")
            # Find context around SP
            lines = text.split('\n')
            for line in lines:
                if 'SP' in line.upper() and ('SPECIAL' in line.upper() or 'SP-' in line):
                    print(f"  {line}")
            print()
