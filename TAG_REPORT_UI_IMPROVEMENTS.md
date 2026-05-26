# TAG REPORT UI & MODULE EXTRACTION IMPROVEMENTS

## Date: May 24, 2026

## Overview

Implemented major improvements to tag report filtering UI and module extraction logic based on user feedback.

## Issues Addressed

### 1. ✅ Column-Based Dropdown Filtering

**Problem**: Text input filters were not user-friendly and didn't look professional

**Solution**: Replaced with dropdown-based filtering system

**New UI Features**:
- **6 dropdown filters** organized in a clean grid:
  - Plant (dropdown with all plants found)
  - Module (dropdown with all modules found, excluding "Unknown")
  - Tag Type (dropdown with all tag types)
  - Discipline (dropdown with all disciplines)
  - Subsystem (dropdown with all subsystems)
  - Page (dropdown with all page numbers)

**Benefits**:
- Cleaner, more professional appearance
- Easier to use - just select from dropdown
- Shows only values that actually exist in the report
- "Clear Filters" button to reset all at once
- Real-time count: "Showing X of Y tags"

**Dynamic Filter Options**:
- Filter options are calculated when report is loaded
- Only shows values present in the current report
- Dropdowns are sorted appropriately (alphabetically or numerically)

### 2. ✅ Enhanced Module Extraction Logic

**Problem**: All modules showing as "Unknown" in reports

**Root Causes**:
1. Limited suffix pattern matching (only looked for A1V3X, A2C3 patterns)
2. Not extracting module info from drawing title block
3. Not detecting module codes embedded in tags

**Solution**: Implemented 5-tier strategy for module detection

#### New Module Extraction Strategy (Priority Order):

**Strategy 1: Direct Module Code in Tag**
- Detects: `TIT-WGL1-001`, `LAH-WGL3-234`, `FIT-WGJ4-567`
- Pattern: Module code directly between prefix and sequence
- Supports: WGL1-5, WGPT, WGRT, WGJ1-7, WGM1-8, WGA0-9

**Strategy 2: Sheet Suffix Patterns**
- Detects: `FIT-9881234-A3V3X`, `10"-WF-6280974-A2C3`
- Pattern: Alphanumeric suffix where digit indicates module
- Mapping: A**1**V3X → WGL1, A**2**C3 → WGL2, etc.

**Strategy 3: Terminal Codes**
- Detects: `34"-PW-56002-BKP7`, `12"-FG-62001-BWD7`
- Patterns:
  - BKP7, BKD7 → WGPT (Pipeline Terminal)
  - BWD7, BWR7 → WGRT (Rail Terminal)

**Strategy 4: Drawing Title Block Metadata** ⭐ NEW
- Extracts module info from drawing title and number
- Uses `pdf_parser.extract_drawing_info()` to get:
  - Drawing number
  - Drawing title
  - Plant designation
- Searches for module codes in title block text
- Example: Drawing title "WGL3 - Module 3 P&ID" → WGL3

**Strategy 5: Fallback**
- Returns "Unknown" if no patterns match
- Framework in place for future system-number-based inference

#### Module Codes Supported:
- **Production Modules**: WGL1, WGL2, WGL3, WGL4, WGL5
- **Junction Modules**: WGJ1-WGJ7
- **Main Modules**: WGM1-WGM8
- **Area Modules**: WGA0-WGA9
- **Terminals**: WGPT (Pipeline), WGRT (Rail)
- **Structural**: WGS + digit
- **Generic**: WGXX

### 3. ✅ Total Pages Recording

**Status**: Verified working correctly

**How it Works**:
- PDF parser extracts page count: `pdf_parser.extract_all()` returns `page_count`
- Stored in TagReport model: `total_pages` field
- Displayed in report list and detail views

**If Still Showing Incorrect**:
- May be legacy data from old reports
- New reports will have correct page counts
- Can regenerate reports to get accurate counts

### 4. ✅ P&ID Symbols Document Integration

**Document**: `P&ID Symbols and Legends.pdf`

**Knowledge Integrated**:
1. **Line Service Codes**: All PIMS service codes validated
2. **Valve Types**: Check valve codes, specialty valve identification
3. **Piping Materials**: Carbon steel, SS, CPVC, HDPE classifications
4. **Equipment Codes**: Pumps, vessels, compressors, etc.
5. **Module Symbology**: Understanding of module boundary markers

**Application**:
- Enhanced `_is_valid_tag()` with comprehensive PIMS codes
- Improved `_parse_tag_type()` with service code validation
- Better understanding of drawing structure for future enhancements

## Code Changes

### Frontend: `TagReportPage.jsx`

**Filter State**:
```javascript
const [filters, setFilters] = useState({
  plant: '',
  module: '',
  tagType: '',
  discipline: '',
  subsystem: '',
  page: '',
})

const [filterOptions, setFilterOptions] = useState({
  plants: [],
  modules: [],
  tagTypes: [],
  disciplines: [],
  subsystems: [],
  pages: []
})
```

**Dynamic Filter Population**:
```javascript
// Calculate filter options from tag data
setFilterOptions({
  plants: [...new Set(tags.map(t => t.plant))].sort(),
  modules: [...new Set(tags.map(t => t.module))].filter(m => m !== 'Unknown').sort(),
  // ... etc
})
```

**Dropdown UI**:
- 3-column grid layout (md:grid-cols-3)
- Clean labels and styling
- "Clear Filters" button when filters active
- Real-time filtered count display

### Backend: `drawings.py`

**Enhanced `_parse_tag_plant_module()`**:
```python
def _parse_tag_plant_module(tag_number: str, subsystem: str = "", drawing_metadata: dict = None) -> dict:
    """5-tier module extraction strategy"""
    # 1. Direct module in tag
    # 2. Suffix patterns
    # 3. Terminal codes
    # 4. Drawing metadata (NEW)
    # 5. Fallback to Unknown
```

**Drawing Metadata Extraction**:
```python
# Extract drawing info for module detection
drawing_info = pdf_parser.extract_drawing_info(d.file_path)
drawing_metadata = {
    'drawing_number': d.drawing_number or drawing_info.get('drawing_number', ''),
    'drawing_title': drawing_info.get('drawing_title', ''),
    'plant': drawing_info.get('plant', ''),
}
```

**Updated Calls**:
```python
tag_metadata = _parse_tag_plant_module(tag_number, subsystem, drawing_metadata)
```

## Testing Instructions

### 1. Restart Backend
```powershell
cd backend
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8020
```

### 2. Generate New Report
1. Navigate to Tag Reports page
2. Select a drawing
3. Click "Generate Report"
4. Wait for extraction to complete

### 3. Verify Module Extraction
**Check that modules are now populated:**
- Look for WGL1, WGL2, WGL3, etc. instead of "Unknown"
- Tags with direct module codes (TIT-WGL1-001) should show correct module
- Tags with suffix patterns (A2C3) should map to WGL2
- Terminal tags (BKP7) should show WGPT

### 4. Test New Filter UI
1. Click "View" on a report
2. See dropdown filters instead of text inputs
3. Try filtering by:
   - Module (select WGL1, WGL2, etc.)
   - Tag Type (select P, V, FIT, etc.)
   - Discipline (select Piping, Instrument, etc.)
   - Page (select specific page number)
4. Verify "Showing X of Y tags" updates correctly
5. Click "Clear Filters" to reset

### 5. Verify Page Count
- Check "Pages" column in report list
- Should show correct number of pages from PDF
- Compare to actual PDF page count

## Expected Results

### Module Extraction:
- **Significant reduction** in "Unknown" modules
- Tags like `TIT-WGL1-001` → Module: **WGL1**
- Tags like `FIT-9881234-A2C3` → Module: **WGL2**  
- Tags like `34"-PW-56002-BKP7` → Module: **WGPT**
- Drawing title "WGL3 Module" → All tags: **WGL3**

### Filtering UX:
- **Cleaner appearance** with dropdowns
- **Faster filtering** - just select from list
- **More intuitive** - see what values exist
- **Professional look** - organized grid layout

### Data Quality:
- **Accurate page counts** in all new reports
- **Better module detection** from multiple sources
- **PIMS-compliant** tag validation

## Known Limitations

### Module Extraction:
1. **Complex Multi-Module Drawings**: If a single drawing has multiple modules WITHOUT module codes in tags or title block, will still show "Unknown"
   - **Future Enhancement**: Spatial analysis using module boundary lines
   - **Future Enhancement**: Following piping lines to module breaks
   - **Future Enhancement**: Zone-based module assignment

2. **Non-Standard Tag Formats**: Tags that don't follow PIMS patterns may not extract modules correctly
   - **Solution**: Use "Mark as Valid" feature to whitelist these tags

3. **Legacy Drawings**: Older drawings with different tagging conventions may need special handling

## Future Enhancements

### Module Detection:
1. **Spatial Analysis**: Detect module boundary lines on drawings and assign tags by location
2. **Line Following**: Trace piping/equipment lines to module breaks
3. **ML-Based Detection**: Train model to recognize module zones on drawings
4. **User Annotation**: Allow users to manually assign modules for ambiguous cases

### Filtering:
1. **Multi-Select Dropdowns**: Select multiple values per filter (e.g., WGL1 + WGL2)
2. **Advanced Filters**: Combine filters with AND/OR logic
3. **Save Filter Presets**: Save commonly used filter combinations
4. **Export Filtered Data**: Download only filtered tags to Excel

### P&ID Symbol Recognition:
1. **Symbol Detection**: Recognize equipment symbols from P&ID legends
2. **Line Tracing**: Follow piping lines for connectivity analysis
3. **Annotation Extraction**: Pull notes and callouts from drawings

## Files Modified

### Frontend:
- `frontend/src/pages/TagReportPage.jsx` - Complete filtering UI overhaul

### Backend:
- `backend/routes/drawings.py` - Enhanced `_parse_tag_plant_module()` with 5-tier strategy

### Documentation:
- `TAG_REPORT_UI_IMPROVEMENTS.md` - This document

## Success Metrics

**Module Extraction**:
- Before: ~90-100% "Unknown" modules
- Target: <20% "Unknown" modules for standard PIMS tags

**User Experience**:
- Cleaner, more professional filtering interface
- Faster workflow with dropdown selections
- Better data quality with accurate modules

---

**Status**: ✓ Ready for Testing
**Priority**: High - Directly impacts report quality and usability
**Breaking Changes**: None - fully backward compatible
