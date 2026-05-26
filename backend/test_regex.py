import re

# Copy the regex patterns from pdf_parser.py
_WIL_DIG = "{5,7}"  # Willow Tagging Specification: 5–7 digit numeric segment
TAG_RE_PRIMARY = re.compile(rf"\b[A-Z]{{1,5}}-[0-9]{_WIL_DIG}[A-Z0-9]{{0,4}}\b")
TAG_RE_SPACE = re.compile(rf"\b([A-Z]{{1,5}})\s+([0-9]{_WIL_DIG}[A-Z0-9]{{0,4}})\b")
TAG_RE_SPACE_WITH_NOISE = re.compile(rf"\b([A-Z]{{1,5}})(?:\s+[A-Z]{{1,2}})*\s+([0-9]{_WIL_DIG}[A-Z0-9]{{0,4}})\b")

# Test cases - missing tags from the user's screenshots + noisy cases
test_tags = [
    "XV-9881520",              # Should match TAG_RE_PRIMARY
    "XV 9881520",              # Should match TAG_RE_SPACE
    "ZIO-9881715",             # Should match TAG_RE_PRIMARY
    "ZIO 9881715",             # Should match TAG_RE_SPACE
    "ZIO U 9881715",           # Should match TAG_RE_SPACE_WITH_NOISE
    "ZIO U U 9881715",         # Should match TAG_RE_SPACE_WITH_NOISE
    "S-98840",                 # Should match TAG_RE_PRIMARY
    "V-98815",                 # Should match TAG_RE_PRIMARY
    "TI ZIO U U 9881719",      # Should match TAG_RE_SPACE_WITH_NOISE
]

print("=" * 80)
print("TESTING TAG_RE_PRIMARY (expects hyphen)")
print("=" * 80)
for tag in test_tags:
    m = TAG_RE_PRIMARY.search(tag)
    if m:
        print(f"MATCH: {tag:25s} -> {m.group(0)}")
    else:
        print(f"NO MATCH: {tag:25s}")

print("\n" + "=" * 80)
print("TESTING TAG_RE_SPACE (expects space between prefix and digits)")
print("=" * 80)
for tag in test_tags:
    m = TAG_RE_SPACE.search(tag)
    if m:
        print(f"MATCH: {tag:25s} -> prefix='{m.group(1)}' digits='{m.group(2)}'")
    else:
        print(f"NO MATCH: {tag:25s}")

print("\n" + "=" * 80)
print("TESTING TAG_RE_SPACE_WITH_NOISE (allows noise words between)")
print("=" * 80)
for tag in test_tags:
    m = TAG_RE_SPACE_WITH_NOISE.search(tag)
    if m:
        print(f"MATCH: {tag:25s} -> prefix='{m.group(1)}' digits='{m.group(2)}'")
    else:
        print(f"NO MATCH: {tag:25s}")

print("\n" + "=" * 80)
print("ANALYZING THE REGEX PATTERNS")
print("=" * 80)
print(f"TAG_RE_PRIMARY: {TAG_RE_PRIMARY.pattern}")
print(f"TAG_RE_SPACE:   {TAG_RE_SPACE.pattern}")
print(f"TAG_RE_SPACE_WITH_NOISE: {TAG_RE_SPACE_WITH_NOISE.pattern}")
print(f"\n_WIL_DIG = {_WIL_DIG} means digits must be 5-7 characters long")
print(f"'98840' has 5 digits - should match")
print(f"'9881715' has 7 digits - should match")
