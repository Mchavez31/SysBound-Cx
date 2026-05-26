import pdfplumber

spec_path = 'uploads/9f620b32-96b2-42a5-bd5a-dce843dc93bc/tagspec_Willow_Tagging_Specificiation_WILG-WFXX-ADM-SPC-WOD-00000-00002-00_10-21-24.pdf'
with pdfplumber.open(spec_path) as pdf:
    print(f"Tagging Specification - Total pages: {len(pdf.pages)}\n")
    
    # Read first few pages to get overview
    for i in range(min(3, len(pdf.pages))):
        text = pdf.pages[i].extract_text() or ''
        print(f"=== Page {i+1} ===")
        print(text[:1000])
        print("\n" + "="*80 + "\n")
