# TAG REPORT MANAGEMENT & FILTERED TAGS FEATURE

## Date: May 24, 2026

## Overview

Implemented comprehensive tag report management system with filtered tags review and validation capabilities. Users can now review tags that were filtered out and mark legitimate ones as valid for future reports.

## New Features

### 1. **Improved Report Management UI**

**Before**: Reports were immediately displayed in full table format
**After**: Clean list view of all reports with action buttons

#### List View Shows:
- Drawing Number
- Generation timestamp
- Valid tags count (green)
- Filtered tags count (amber if > 0)
- Total pages
- Action buttons: **View**, **Excel** (download), **Delete**

### 2. **Detailed Report View**

Click "View" on any report to see:
- Full tag table with all extracted tags
- Filter controls (by Tag Number, Type, Discipline, Subsystem, Page)
- Sortable columns
- Summary statistics cards
- **"View Filtered Tags"** button (if filtered tags exist)
- **"Close"** button to return to list view

### 3. **Filtered Tags Review**

**Purpose**: Show users which tags were excluded and why

**Access**: Click "View Filtered Tags" button in detail view

**Displays**:
- Tag number (with monospace font)
- Page number where tag was found
- Reason for filtering (e.g., "Does not match PIMS tag format", "Unknown tag type")
- Tag color (visual indicator)
- **"Mark as Valid"** button for each tag

### 4. **Tag Validation System**

**Purpose**: Allow users to whitelist legitimate tags that were incorrectly filtered

**How it Works**:
1. User reviews filtered tags
2. Clicks "Mark as Valid" on a legitimate tag
3. Tag is added to project's validated tags whitelist
4. Future reports will automatically include this tag
5. Toast notification confirms action

**Backend Storage**:
- New `validated_tags` database table
- Stores tag number, tag type, notes, validator, and timestamp
- Project-specific whitelists

### 5. **Intelligent Filtering with Whitelist**

**New Logic**:
```
For each extracted tag:
  1. Check if tag is in validated whitelist
     → If YES: Include in report (bypass validation)
     → If NO: Continue to validation
  2. Validate against PIMS specification
     → If VALID: Include in report
     → If INVALID: Add to filtered tags with reason
  3. Track filtered tags for user review
```

## Database Changes

### New Table: `validated_tags`
```sql
CREATE TABLE validated_tags (
    id VARCHAR PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    tag_number VARCHAR NOT NULL,
    tag_type VARCHAR,
    notes TEXT,
    validated_by VARCHAR,
    validated_at TIMESTAMP
)
```

### Updated Table: `tag_reports`
```sql
ALTER TABLE tag_reports ADD COLUMN filtered_tags_count INTEGER DEFAULT 0;
ALTER TABLE tag_reports ADD COLUMN filtered_tags_json TEXT;
```

## API Endpoints

### New Endpoints:

1. **GET `/drawings/{project_id}/reports/{report_id}/filtered-tags`**
   - Returns list of tags that were filtered out
   - Includes tag number, page, reason, and color

2. **POST `/drawings/{project_id}/validated-tags`**
   - Body: `{ tag_number, tag_type, notes }`
   - Adds tag to validated whitelist
   - Returns validated tag record

3. **GET `/drawings/{project_id}/validated-tags`**
   - Lists all validated tags for project
   - Returns array with tag details and validation info

4. **DELETE `/drawings/{project_id}/validated-tags/{validated_tag_id}`**
   - Removes tag from validated whitelist

### Updated Endpoints:

**GET `/drawings/{project_id}/reports`**
- Now includes `filtered_tags_count` in response

**GET `/drawings/{project_id}/drawing/{drawing_id}/tag-report`**
- Now checks validated tags whitelist before filtering
- Tracks filtered tags with reasons
- Saves filtered tags JSON to database
- Returns `filtered_tags_count` in response

## User Workflow

### Scenario 1: Generate New Report

1. Navigate to Tag Reports page
2. Select drawing from dropdown
3. Click "Generate Report"
4. Toast shows: "Report generated: X valid tags extracted, Y tags filtered out"
5. Report appears in list view

### Scenario 2: View Report Details

1. From list view, click "View" on any report
2. See full tag table with filters
3. Apply filters/sorting as needed
4. Click "Close" to return to list

### Scenario 3: Review Filtered Tags

1. In detail view, click "View Filtered Tags (X)" button
2. Review list of excluded tags
3. For each legitimate tag:
   - Read the filter reason
   - Click "Mark as Valid" if it should be included
   - See confirmation toast
4. Click "Close" on filtered tags view
5. Generate new report to see validated tags included

### Scenario 4: Download or Delete Reports

1. From list view, click "Excel" to download Excel file
2. Click "Delete" to remove report (with confirmation)
3. If viewing deleted report in detail view, automatically returns to list

## Technical Implementation Details

### Frontend (TagReportPage.jsx)

**State Management**:
- `viewMode`: 'list' or 'detail'
- `activeReport`: Currently viewed report object
- `reportTags`: Full tag data for active report
- `filteredTags`: List of filtered tags for review
- `showFilteredTags`: Toggle between tag table and filtered tags view

**Key Functions**:
- `viewReport(report)`: Loads and displays report details
- `loadFilteredTags(reportId)`: Fetches filtered tags
- `markTagAsValid(tagNumber)`: Adds tag to whitelist
- `closeDetailView()`: Returns to list view

### Backend (drawings.py)

**Enhanced `generate_tag_report()`**:
1. Loads validated tags for project
2. Checks each tag against whitelist
3. Tracks filtered tags with reasons:
   - "Does not match PIMS tag format"
   - "Unknown tag type (prefix not in PIMS specification)"
4. Saves filtered tags as JSON
5. Returns filtered_tags_count

**Filter Reasons Tracked**:
- Drawing metadata codes (WOD-, WWOC-, etc.)
- Project codes (WILG-WFXX-)
- Text fragments (ALVE, ANDLI, ALARM, etc.)
- Unknown equipment codes not in PIMS spec
- Malformed piping tags
- Tags with no valid prefix

## Benefits

1. **User Confidence**: Users can verify the app is filtering correctly
2. **Transparency**: Clear reasons shown for why each tag was excluded
3. **Flexibility**: Easy to override incorrect filtering decisions
4. **Learning System**: Whitelist grows over time with validated tags
5. **Audit Trail**: All validations are timestamped and attributed to users
6. **Better UX**: Clean separation between report list and detail views

## Testing Checklist

- [ ] Generate new report - see filtered tags count
- [ ] View report details - see full tag table
- [ ] Click "View Filtered Tags" - see excluded tags with reasons
- [ ] Mark a filtered tag as valid - see toast confirmation
- [ ] Generate new report - validated tag now included
- [ ] Download Excel report
- [ ] Delete report
- [ ] Close detail view returns to list
- [ ] Filter and sort tags in detail view
- [ ] Multiple reports show in list view

## Migration Instructions

1. **Database Migration**:
   ```bash
   # Backend will auto-migrate on restart
   # Adds filtered_tags_count and filtered_tags_json columns
   # Creates validated_tags table
   ```

2. **No Breaking Changes**:
   - Existing reports still work
   - Existing filtered_tags_count defaults to 0
   - Validated tags start empty (users build over time)

3. **Restart Backend**:
   ```powershell
   cd backend
   python -m uvicorn main:app --reload --host 127.0.0.1 --port 8020
   ```

## Files Modified

### Backend:
- `backend/models/database.py` - Added ValidatedTag model, updated TagReport
- `backend/db_migrate.py` - Added migration for new columns/table
- `backend/routes/drawings.py` - Enhanced tag generation, added 4 new endpoints

### Frontend:
- `frontend/src/pages/TagReportPage.jsx` - Complete rewrite with new UX

## Next Steps

Future enhancements:
- Bulk validate multiple filtered tags at once
- Export filtered tags to Excel for offline review
- Tag validation notes/comments
- Validation history tracking
- Auto-suggest similar validated tags

---

**Status**: ✓ Ready for Testing
**Impact**: High - Significantly improves user confidence and tag filtering accuracy
**Breaking Changes**: None - fully backward compatible
