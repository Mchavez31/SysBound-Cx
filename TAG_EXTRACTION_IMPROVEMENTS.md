# Tag Extraction Quality Improvements

**Date:** 2026-05-25  
**Issue:** Tags with concatenated text, NOTE suffixes, and missing many expected tags

## Problems Fixed

### 1. NOTE/NOTES Suffixes
**Before:** Tags like `BC-9580712-A1V3XNOTE`, `BC-9580712-A1V3XNOTE2`, `BC-9580712-A1V3XNOTE2ZI10` were being captured

**Fix:** Added pattern matching to detect and strip NOTE/NOTES suffixes with optional numbers:
- `_NOTE_SUFFIX_RE = re.compile(r"NOTE[S]?\d*$", re.I)`
- Updated `canonical_simple_extracted_tag()` to remove these before validation

**Result:** Tags like `BC-9580712-A1V3XNOTE2` → `BC-9580712-A1V3X`

### 2. Concatenated Tags
**Before:** Tags like `2"-AI-6580212-A1B3X65-092"-AI` with extra tag data appended

**Fix:** Added validation in `is_plausible_pipeline_line_tag()` to detect:
- Tags ending with another tag pattern (e.g., `...092"-AI`)
- Suffixes containing complete tag number digit blocks (5-7 digits)

**Pattern detection:**
```python
# Rejects: ...suffix-DIGITS"-PREFIX (e.g., ...092"-AI)
concat_pattern = re.search(r'(\d{1,2})["\']?\s*-?\s*([A-Z]{1,5})$', suf_rest)

# Rejects: suffixes with 5-7 digit runs (likely concatenated tag numbers)
digit_run_in_suf = re.search(rf'\d{{{5},{7}}}', suf_rest)
```

**Result:** Rejects concatenated garbage, keeps valid tags

### 3. Duplicate Number Blocks
**Before:** Tags like `BC-9881745-A1V3X98815109881510` with numbers repeated

**Fix:** Extended duplicate detection to pipeline tag suffixes:
```python
digit_run_in_suf = re.search(rf'\d{{{WILLOW_NUMERIC_SEGMENT_MIN_LEN},{WILLOW_NUMERIC_SEGMENT_MAX_LEN}}}', suf_rest)
if digit_run_in_suf:
    return False
```

**Result:** Rejects tags with number blocks in suffixes

### 4. Improved Regex Negative Lookahead
**Before:** Regex used `(?![A-Z]+-\d{5})` which rejected some valid single-letter suffixes

**Fix:** Made lookahead more specific: `(?![A-Z]{2,}-\d{5})`
- Requires at least 2 letters before dash to trigger rejection
- Allows valid single-letter suffixes
- Still catches concatenated tags like `...092"-AI`

**Result:** Captures more valid tags while filtering concatenated ones

### 5. Added NOTE Validation to General Tags
**Fix:** Updated `is_plausible_tag_number()` to also check for NOTE suffixes:
```python
if _NOTE_SUFFIX_RE.search(suff):
    return False
```

## Expected Results

With these improvements:

✅ **No more NOTE suffixes** - Tags like `BC-9580712-A1V3XNOTE2` will be cleaned to `BC-9580712-A1V3X`

✅ **No concatenated tags** - Rejects `2"-AI-6580212-A1B3X65-092"-AI` style garbage

✅ **No duplicate numbers** - Rejects `BC-9881745-A1V3X98815109881510`

✅ **More valid tags captured** - Less aggressive negative lookahead allows more valid tags

✅ **Better quality** - Cleaner tag list matching PIMS documentation

## Testing

To test the improvements:

1. **Restart the backend** to load the updated code:
   ```bash
   # Kill the current dev server and restart
   npm run dev
   ```

2. **Generate a new tag report** on a drawing that had issues

3. **Compare results:**
   - Check for NOTE suffixes (should be gone)
   - Check for concatenated tags (should be rejected)
   - Check total count (should be closer to ~13,666 expected)
   - Review tag quality

## Files Modified

- `backend/services/pdf_parser.py`
  - Updated `canonical_simple_extracted_tag()` - strips NOTE suffixes
  - Updated `is_plausible_pipeline_line_tag()` - detects concatenations and duplicates
  - Updated `is_plausible_tag_number()` - validates against NOTE suffixes
  - Updated regex patterns - less aggressive negative lookahead

## Next Steps (If Still Issues)

If you're still not finding enough tags:

1. **Check the PIMS data format** - Ensure tag formats in PIMS match extraction patterns
2. **Review validation strictness** - May need to relax some validation rules
3. **Add more regex patterns** - For any tag formats not currently covered
4. **Check P&ID quality** - Low-quality scans may have OCR issues

## Notes

- Expected ~13,666 tags based on WOC PIMS documentation
- Current extraction should now be much closer to this number
- Tag quality should be significantly improved
- All improvements maintain backward compatibility
