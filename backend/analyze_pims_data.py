import pandas as pd
import os

# Analyze all three PIMS exports
files = [
    (r'C:\Users\micha\OneDrive\Documents\Willow\Systemization Documents\WOC Tag Export PIMS 2-10-26.xlsx', 'WOC'),
    (r'C:\Users\micha\OneDrive\Documents\Willow\Systemization Documents\KPAD Tag Export PIMS 2-10-26.xlsx', 'KPAD'),
    (r'C:\Users\micha\OneDrive\Documents\Willow\Systemization Documents\WCF Tag Export 2 5-13-26.xlsx', 'WCF')
]

for file_path, plant_name in files:
    print(f"\n{'='*80}")
    print(f"=== {plant_name} PIMS Export Analysis ===")
    print(f"{'='*80}\n")
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        continue
    
    try:
        df = pd.read_excel(file_path)
        
        print(f"Total rows: {len(df)}")
        print(f"\nColumns ({len(df.columns)} total):")
        for col in df.columns:
            print(f"  - {col}")
        
        print(f"\n\nSample data (first 10 rows):")
        print(df.head(10).to_string())
        
        # Check for key columns
        if 'Tag Number' in df.columns or 'TagNumber' in df.columns:
            tag_col = 'Tag Number' if 'Tag Number' in df.columns else 'TagNumber'
            print(f"\n\nSample tag numbers (first 20):")
            sample_tags = df[tag_col].dropna().head(20)
            for tag in sample_tags:
                print(f"  {tag}")
        
        # Check for module column
        if 'Module' in df.columns:
            modules = df['Module'].dropna().unique()
            print(f"\n\nUnique modules ({len(modules)}):")
            for m in sorted(modules)[:30]:  # Show first 30
                count = len(df[df['Module'] == m])
                print(f"  {m}: {count} tags")
        
        # Check for tag type/class
        for col_name in ['Tag Type', 'TagType', 'Type', 'Tag Class', 'Class']:
            if col_name in df.columns:
                types = df[col_name].dropna().unique()
                print(f"\n\nUnique {col_name} values ({len(types)}):")
                for t in sorted(types):
                    count = len(df[df[col_name] == t])
                    print(f"  {t}: {count} tags")
                break
        
    except Exception as e:
        print(f"Error reading file: {e}")
        import traceback
        traceback.print_exc()

print("\n\n" + "="*80)
print("Analysis complete!")
