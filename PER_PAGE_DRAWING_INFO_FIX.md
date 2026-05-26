# Tag Report Fixes - Drawing Number & Revision Per Page

**Date:** 2026-05-25  
**Issues Fixed:** P&ID column showing same value, missing revision column, per-page extraction

## Issues Identified

1. **All P&ID document numbers were the same**: The Excel report was using a single drawing number for all tags, instead of extracting it from each page's titleblock.

2. **Missing Revision column**: The revision from the bottom-right titleblock was not included in the report.

3. **Extraction from first page only**: The original `extract_drawing_info` only looked at page 0, not individual pages.

## Solutions Implemented

### 1. Per-Page Drawing Info Extraction

**New Function:** `_extract_page_drawing_info(page, page_num)`

```python
def _extract_page_drawing_info(page: Any, page_num: int) -> dict[str, Any]:
    """
    Extract drawing number and revision from a single page's titleblock.
    Focuses on bottom-right corner where titleblocks typically are.
    """
```

**What it does:**
- Extracts from the **bottom 15%** of each page (titleblock area)
- Looks for drawing number patterns like `WMOC-WGXX-PRO-PID-WOD-00000-61011-01`
- Extracts revision using existing `_extract_revision()` (finds "REV. 11" or "REVISION 11")

**Returns:**
```python
{
    "drawing_number": "WMOC-WGXX-PRO-PID-WOD-00000-61011-01",
    "revision": "11"
}
```

### 2. Integration into Tag Extraction

**Modified:** `_extract_combined_page_range()`

**Changes:**
1. Calls `_extract_page_drawing_info(page, pnum)` for each page
2. Adds `pid_drawing_number` and `pid_revision` to each tag
3. Each tag now knows its specific page's drawing number and revision

```python
# Extract drawing info for this specific page
page_drawing_info = _extract_page_drawing_info(page, pnum)

# ... tag extraction ...

for t in page_tags:
    # ... existing color logic ...
    
    # Add page-specific drawing info to each tag
    t["pid_drawing_number"] = page_drawing_info["drawing_number"]
    t["pid_revision"] = page_drawing_info["revision"]
```

### 3. Excel Report Updates

**File:** `backend/services/excel_generator.py`

**Changes:**

1. **Added 'P&ID Rev' column** to headers (after 'P&ID Drawing Name'):
   ```python
   headers = [
       # ...
       'P&ID Drawing Name',
       'P&ID Rev',  # NEW
       'Page Number',
       # ...
   ]
   ```

2. **Use per-tag drawing number** instead of function parameter:
   ```python
   # OLD: ws.cell(row=row_num, column=8, value=drawing_number)
   # NEW: 
   ws.cell(row=row_num, column=8, value=tag.get('pid_drawing_number', drawing_number))
   ```

3. **Add revision data** to new column:
   ```python
   ws.cell(row=row_num, column=9, value=tag.get('pid_revision', ''))
   ```

## Expected Results

### Before
```
P&ID Drawing Name
-----------------
WILG-WFXX-PRO-PID-WOD-00000-00001-01
WILG-WFXX-PRO-PID-WOD-00000-00001-01  <-- All the same!
WILG-WFXX-PRO-PID-WOD-00000-00001-01
```

### After
```
P&ID Drawing Name                      | P&ID Rev
---------------------------------------|----------
WMOC-WGXX-PRO-PID-WOD-00000-61011-01  | 11
WMOC-WGXX-PRO-PID-WOD-00000-61012-01  | 08
WMOC-WGXX-PRO-PID-WOD-00000-61013-01  | 11
```

Each tag now has:
- ✅ Correct drawing number from its specific page
- ✅ Revision number from its specific page's titleblock
- ✅ Separate column for revision

## Testing

1. **Navigate to:** `http://localhost:5178`
2. **Generate a new tag report** on the multi-page PDF
3. **Open the Excel file**
4. **Check columns 8 and 9:**
   - Column 8: Different drawing numbers for different pages
   - Column 9: Revision numbers (e.g., "11", "08", etc.)

## Technical Details

### Titleblock Extraction Area

- **Vertical crop:** Bottom 15% of page (0.85 * height to height)
- **Horizontal:** Full width
- This is where titleblocks typically are on P&ID drawings

### Drawing Number Pattern

Matches formats like:
- `WMOC-WGXX-PRO-PID-WOD-00000-61011-01`
- `WILG-WFXX-PRO-PID-WOD-00000-00001-01`
- Minimum 20 characters for validity

### Revision Pattern

Matches:
- `REV. 11`
- `REV 11`
- `REVISION 11`
- Case insensitive
- Captures 1-2 digit numbers

## Impact

### Data Integrity
- ✅ Tags now correctly associated with their page's drawing number
- ✅ Revision tracking per drawing (critical for change management)
- ✅ Matches PIMS commissioning format expectations

### Compliance
- ✅ Each tag traceable to specific drawing and revision
- ✅ Audit trail for tag sources
- ✅ Proper documentation for commissioning

## Next Steps

After generating a new report:

1. **Verify drawing numbers** match the titleblocks in the PDF
2. **Verify revisions** match the titleblocks
3. **Review missing tags** - still need to address:
   - Diagonal SP tags (TagType diagonal to left of Tag Number)
   - Other non-standard layouts
   - Tags in unusual fonts or sizes

## Notes

- The fallback to `drawing_number` parameter ensures backward compatibility
- If extraction fails for a page, that tag will use the overall drawing number
- Revision column can be empty if not found in titleblock
- This works for multi-sheet drawings where each sheet has its own titleblock

---

**Status:** ✅ Implemented and ready to test  
**Backend restarted:** Running on port 8020  
**Frontend:** `http://localhost:5178`  
**Files modified:**
- `backend/services/pdf_parser.py` (added `_extract_page_drawing_info`)
- `backend/services/excel_generator.py` (added revision column, per-tag drawing numbers)
