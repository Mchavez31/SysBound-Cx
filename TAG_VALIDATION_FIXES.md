# TAG VALIDATION FIXES - PIMS Specification Compliance

## Date: May 24, 2026

## Problem Statement

The tag extraction system was identifying illegitimate tags from P&ID drawings that do not match the PIMS Tagging Specification (WILG-WFXX-ADM-SPC-WOD-00000-00002-00, Rev 12). Text fragments, drawing metadata, and malformed tags were being extracted as valid equipment tags.

## Analysis Results

From the tag report `tag_report_WILG-WFXX-PRO-PID-WOD-00000-00001-01_2026-05-24.xlsx`:

**Total tags in report**: 2,497 tags
**Invalid tags identified**: Approximately 300-400 illegitimate tags

### Categories of Invalid Tags Found:

1. **Drawing Metadata Codes**
   - `WOD-00000` - Drawing number, not equipment
   - `WWOC-WGXX` - Drawing identifier  
   - `WILG-WFXX` - Project code prefix

2. **Text Fragments** (words from annotations, not tags)
   - `ALVE-61728530828` (from "VALVE")
   - `ANDLI-4983501B` (from "HANDLING")
   - `ALARM-5881001` (from "ALARM")
   - `ATON-...`, `ETON-...`, `ALOW-...`, `AIRN-...`, etc.

3. **Annotation Codes**
   - `ENT-320087` (from "CURRENT")
   - `RENT-320087` (from "CURRENT" text fragment)
   - `NOTE-...` - Drawing notes

4. **Malformed SPSP Tags**
   - `SPSP-008015WGL3` - Invalid format, module code concatenated

5. **Unknown Equipment Codes** (not in PIMS specification)
   - `KL-...`, `KLN-...` - Not in any PIMS equipment table
   - `BC-...` (when not Battery Charger context)
   - `DLFR-...`, `BTT-...`, `FCT-...`, `PITMV-...`, etc.

6. **Malformed Piping Tags**
   - `34"-PW-56002-BKP7` - Only 5 digits instead of required 7
   - `94"-FG-62001-BWD7` - Only 5 digits instead of required 7
   - Some piping tags captured with concatenated text

## Solution Implemented

### 1. Created Comprehensive PIMS Prefix Validation

**New Function**: `_is_valid_pims_prefix(prefix: str) -> bool`

This function validates tag prefixes against ALL valid PIMS equipment codes:

- **Mechanical Equipment** (Table 6.1.1): A, AW, BLN, C, DP, E, EF, F, G, H, HH, K, M, P, S, SF, T, TB, U, V, VET, W, X, Z
- **Manual Valves** (Table 6.2.1): MV, CK
- **HVAC Equipment** (Table 6.4.1): ACU, AHU, BD, CU, CVD, EHC, EUH, FSD, HHC, HU, MCD, RAG, RF, SAD, SAG, SOD, TAG, TF, TU, UH, VCD
- **Electrical Equipment** (Table 6.6.1): AB, AGS, ANT, ASD, ATS, BC, BKR, BS, CAM, CCTV, CP, DP, ELP, EPH, GR, HT, IP, LP, MCC, MR, MS, PMS, PTR, SG, TP, UPS, etc. (60+ codes)
- **Instrumentation** (Table 6.9.1): AAH, AAL, AC, AI, AIT, FIT, FT, LAH, LAL, LIT, LT, PAH, PAL, PIT, PT, TAH, TAL, TIT, TT, HS, XV, MOV, PSV, ZT, ZIC, etc. (300+ codes)
- **Piping Service Codes** (Table 6.3.1): AI, AM, AP, BC, BM, BW, CA, CB, CC, CCA, CCH, CD, CE, CF, CG, CH, CI, CM, CO, CS, CW, DF, DO, DP, FD, FG, FH, FL, GI, GL, GM, GN, GW, HF, HG, HO, HW, LF, LN, LNG, LO, MC, ME, MG, MI, MP, MS, MT, MU, MV, MW, MX, NGL, OS, PC, PG, PO, PW, SO, ST, SW, VA, WA, WC, WD, WF, WG, WH, WI, WL, WM, WO, WR, WS, WX
- **Special Items** (Section 6.5): SP

### 2. Enhanced `_is_valid_tag()` Function

**Location**: `backend/routes/drawings.py` (lines 742-866)

**New Validation Logic**:

```python
def _is_valid_tag(tag_number: str) -> bool:
    """Validate against PIMS specification.
    
    Returns False for:
    - Drawing codes (WOD-, WWO-, WOC-, WWC-)
    - Project codes (WILG-...)
    - Text fragments (ALVE, ANDLI, ALARM, etc.)
    - Tags with unknown prefixes not in PIMS spec
    - Malformed piping tags
    
    Returns True ONLY for valid PIMS equipment tags.
    """
```

**Key Improvements**:

1. **Expanded text fragment detection** - Added 50+ known text fragments
2. **PIMS prefix validation** - Every non-piping tag prefix is checked against the complete PIMS specification
3. **Piping format validation** - Validates piping tags match format `NN"-XXX-NNNNNNN` with valid service codes
4. **Drawing metadata filtering** - Blocks all drawing/project code patterns

### 3. Updated `_parse_tag_type()` Function

**Location**: `backend/routes/drawings.py` (lines 868-934)

**Key Changes**:

1. Now uses `_is_valid_pims_prefix()` for all prefix validation
2. Returns 'Unknown' for any prefix not in PIMS specification
3. Validates piping service codes against Table 6.3.1
4. More accurate tag type extraction

## Expected Results

After restarting the backend, the tag extraction should:

### ✓ Correctly Extract:
- `V-37803` → Valid Vessel tag
- `P-31001` → Valid Pump tag  
- `U-00810` → Valid Packaged Unit tag
- `FIT-9881234` → Valid Flow Instrument Transmitter
- `LAH-9881715` → Valid Level Alarm High
- `10"-WF-6280974-A2C3` → Valid piping line (if 7-digit number)
- `XV-3100001` → Valid Control Valve
- `T-42001` → Valid Tank

### ✗ Correctly Reject:
- `WOD-00000` - Drawing code
- `WWOC-WGXX` - Drawing identifier
- `WILG-WFXX` - Project code
- `ALVE-61728530828` - Text fragment from "VALVE"
- `ANDLI-4983501B` - Text fragment from "HANDLING"
- `ALARM-5881001` - Text fragment from "ALARM"
- `ENT-320087` - Text fragment from "CURRENT"
- `RENT-320087` - Text fragment from "CURRENT"
- `KL-...`, `KLN-...`, `ETON-...` - Unknown codes not in PIMS
- `SPSP-008015WGL3` - Malformed format
- `34"-PW-56002-BKP7` - Malformed (5 digits instead of 7)

## Testing Instructions

1. **Restart the Backend**:
   ```powershell
   cd backend
   python -m uvicorn main:app --reload --host 127.0.0.1 --port 8020
   ```
   Or use `npm run dev` from project root.

2. **Generate a New Tag Report**:
   - Navigate to Drawings page
   - Select drawing: `WILG-WFXX-PRO-PID-WOD-00000-00001-01`
   - Click "Tag Report"
   - Download the Excel report

3. **Verify Results**:
   - Check that text fragments like `ALVE`, `ANDLI`, `ALARM`, `ATON`, `ETON` are no longer in the report
   - Verify drawing codes `WOD-00000`, `WWOC-WGXX` are filtered out
   - Confirm valid equipment tags like `V-37803`, `P-31001`, `U-00810` ARE still present
   - Look at "Tag Type" column - should only show valid PIMS codes
   - Total tag count should be significantly reduced (likely 2100-2200 valid tags vs. previous 2497)

4. **Compare to PIMS Reports**:
   - Cross-reference with your PIMS commissioning reports
   - Tag format should match expected PIMS format
   - All equipment codes should be recognizable from PIMS tables

## Files Modified

1. **`backend/routes/drawings.py`**
   - Added `_is_valid_pims_prefix()` function (lines 809-866)
   - Updated `_is_valid_tag()` function (lines 742-807)
   - Updated `_parse_tag_type()` function (lines 868-934)

## Technical Notes

- The validation is applied during tag report generation in the `generate_tag_report()` endpoint
- Invalid tags are filtered out before being added to the report
- Filtered tag count is logged to console: `"Tag Extraction Report: X valid tags extracted, Y invalid tags filtered out"`
- The same validation is applied during comparison operations to exclude invalid tags

## References

- PIMS Tagging Specification: `WILG-WFXX-ADM-SPC-WOD-00000-00002-00, Rev 12`
- Tag Report Analyzed: `tag_report_WILG-WFXX-PRO-PID-WOD-00000-00001-01_2026-05-24.xlsx`
- Invalid Tags Report: `backend/invalid_tags_report.xlsx` (generated by validation script)

## Next Steps

After testing, if additional text fragments or invalid patterns are discovered:

1. Add them to the `text_fragments` set in `_is_valid_tag()`
2. Or add missing equipment codes to `_is_valid_pims_prefix()` if they are legitimate PIMS codes

---

**Status**: ✓ Ready for Testing
**Author**: AI Assistant
**Date**: May 24, 2026, 1:50 AM UTC-5
