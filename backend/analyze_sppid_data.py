import pandas as pd

# Read SPPID Export
print("=== SPPID Export Analysis ===\n")
sppid = pd.read_excel(r'C:\Users\micha\OneDrive\Documents\Willow\Systemization Documents\SPPID Export 5-13-26.xlsx')
print(f"Total rows: {len(sppid)}")
print(f"\nColumns: {sppid.columns.tolist()}")
print(f"\nSample data (first 10 rows):")
print(sppid.head(10).to_string())

# Analyze Module codes
print("\n\n=== Unique Module Codes ===")
modules = sppid['Module'].dropna().unique()
print(f"Found {len(modules)} unique modules:")
for m in sorted(modules):
    count = len(sppid[sppid['Module'] == m])
    print(f"  {m}: {count} tags")

# Analyze Tag Types
print("\n\n=== Unique Tag Types ===")
tag_types = sppid['Tag Type'].dropna().unique()
print(f"Found {len(tag_types)} unique tag types:")
for tt in sorted(tag_types):
    count = len(sppid[sppid['Tag Type'] == tt])
    print(f"  {tt}: {count} tags")

# Read Valid Lookup Values
print("\n\n=== Valid Lookup Values Analysis ===\n")
lookup = pd.read_excel(r'C:\Users\micha\OneDrive\Documents\Willow\Systemization Documents\Valid Lookup Values 2_15_22.xlsx', 
                       sheet_name='valid lookup values', header=1)
print(f"Total lookup rows: {len(lookup)}")
print(f"\nColumns: {lookup.columns.tolist()}")

# Get unique types
types = lookup['Type'].dropna().unique()
print(f"\n=== Lookup Types Available ===")
for t in sorted(types):
    count = len(lookup[lookup['Type'] == t])
    print(f"  {t}: {count} values")

# Show sample tags with their modules
print("\n\n=== Sample Tags with Complete Data ===")
sample = sppid[sppid['Tag Number'].notna()].head(20)[['Tag Type', 'Tag Number', 'Module', 'CSU Subsytem', 'P&ID Drawing Name']]
print(sample.to_string(index=False))
