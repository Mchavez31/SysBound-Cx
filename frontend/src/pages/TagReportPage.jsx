import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import api, { toastAxiosError } from '../lib/api'
import toast from 'react-hot-toast'

export default function TagReportPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const drawingId = searchParams.get('drawing')
  
  // Ref to prevent infinite loop when auto-loading most recent report
  const hasAutoLoadedRef = useRef(false)

  const [drawings, setDrawings] = useState([])
  const [selectedDrawing, setSelectedDrawing] = useState(drawingId || '')
  const [generating, setGenerating] = useState(false)
  const [savedReports, setSavedReports] = useState([])
  
  // Current report being displayed
  const [currentReport, setCurrentReport] = useState(null)
  const [reportTags, setReportTags] = useState([])
  const [filteredTags, setFilteredTags] = useState([])
  const [showFilteredTags, setShowFilteredTags] = useState(false)
  
  // Filter and sort state
  const [filters, setFilters] = useState({
    plant: '',
    module: '',
    tagType: '',
    discipline: '',
    subsystem: '',
    page: '',
  })
  const [sortField, setSortField] = useState('tag_number')
  const [sortDirection, setSortDirection] = useState('asc')
  
  // Dropdown filter options
  const [filterOptions, setFilterOptions] = useState({
    plants: [],
    modules: [],
    tagTypes: [],
    disciplines: [],
    subsystems: [],
    pages: []
  })

  useEffect(() => {
    if (projectId) {
      loadDrawings()
      loadSavedReports()
    }
    // Reset auto-load flag when projectId changes
    hasAutoLoadedRef.current = false
  }, [projectId])

  // Auto-display most recent report when savedReports loads (only once)
  useEffect(() => {
    if (savedReports.length > 0 && !currentReport && !hasAutoLoadedRef.current) {
      hasAutoLoadedRef.current = true
      // Most recent report is first in the list (sorted by date descending)
      const mostRecent = savedReports[0]
      displayReport(mostRecent)
    }
  }, [savedReports, currentReport])

  const loadDrawings = async () => {
    try {
      const { data } = await api.get(`/drawings/${projectId}`)
      setDrawings(data.drawings || [])
    } catch (error) {
      toastAxiosError(error, 'Failed to load drawings')
    }
  }

  const loadSavedReports = async () => {
    try {
      const { data } = await api.get(`/drawings/${projectId}/reports`)
      setSavedReports(data.reports || [])
    } catch (error) {
      console.error('Failed to load saved reports:', error)
    }
  }

  const generateReport = async () => {
    if (!selectedDrawing) {
      toast.error('Please select a drawing')
      return
    }

    setGenerating(true)
    try {
      const { data } = await api.get(
        `/drawings/${projectId}/drawing/${selectedDrawing}/tag-report`,
        { timeout: 600000 }
      )
      
      toast.success(
        `Report generated: ${data.total_tags} valid tags extracted${data.filtered_tags_count > 0 ? `, ${data.filtered_tags_count} tags filtered out` : ''}`
      )
      
      // Reload saved reports list
      await loadSavedReports()
      
      // Automatically display the newly generated report
      if (data.report_id) {
        const newReport = {
          id: data.report_id,
          drawing_id: selectedDrawing,
          drawing_number: data.drawing_number,
          total_tags: data.total_tags,
          filtered_tags_count: data.filtered_tags_count || 0,
          total_pages: data.total_pages,
          generated_at: data.extraction_timestamp
        }
        
        // Set up the display with the data we already have
        setCurrentReport(newReport)
        setReportTags(data.tags || [])
        setShowFilteredTags(false)
        
        // Calculate filter options
        const tags = data.tags || []
        setFilterOptions({
          plants: [...new Set(tags.map(t => t.plant))].sort(),
          modules: [...new Set(tags.map(t => t.module))].filter(m => m !== 'Unknown').sort(),
          tagTypes: [...new Set(tags.map(t => t.tag_type))].sort(),
          disciplines: [...new Set(tags.map(t => t.discipline))].sort(),
          subsystems: [...new Set(tags.map(t => t.subsystem).filter(s => s))].sort(),
          pages: [...new Set(tags.map(t => t.page_number))].sort((a, b) => a - b)
        })
        
        // Reset filters
        setFilters({
          plant: '',
          module: '',
          tagType: '',
          discipline: '',
          subsystem: '',
          page: '',
        })
      }
    } catch (error) {
      toastAxiosError(error, 'Failed to generate tag report')
    } finally {
      setGenerating(false)
    }
  }

  // Display a report that was already generated (no re-extraction)
  const displayReport = async (report) => {
    // For now, we still need to re-extract to get the tag data
    // TODO: Store tag data in database to avoid re-extraction
    try {
      const { data } = await api.get(`/drawings/${projectId}/drawing/${report.drawing_id}/tag-report`)
      
      setCurrentReport(report)
      setReportTags(data.tags || [])
      setShowFilteredTags(false)
      
      // Calculate filter options from the data
      const tags = data.tags || []
      setFilterOptions({
        plants: [...new Set(tags.map(t => t.plant))].sort(),
        modules: [...new Set(tags.map(t => t.module))].filter(m => m !== 'Unknown').sort(),
        tagTypes: [...new Set(tags.map(t => t.tag_type))].sort(),
        disciplines: [...new Set(tags.map(t => t.discipline))].sort(),
        subsystems: [...new Set(tags.map(t => t.subsystem).filter(s => s))].sort(),
        pages: [...new Set(tags.map(t => t.page_number))].sort((a, b) => a - b)
      })
      
      // Reset filters
      setFilters({
        plant: '',
        module: '',
        tagType: '',
        discipline: '',
        subsystem: '',
        page: '',
      })
    } catch (error) {
      toastAxiosError(error, 'Failed to load report')
    }
  }

  const loadFilteredTags = async (reportId) => {
    try {
      const { data } = await api.get(`/drawings/${projectId}/reports/${reportId}/filtered-tags`)
      setFilteredTags(data.filtered_tags || [])
      setShowFilteredTags(true)
    } catch (error) {
      toastAxiosError(error, 'Failed to load filtered tags')
    }
  }

  const markTagAsValid = async (tagNumber) => {
    try {
      await api.post(`/drawings/${projectId}/validated-tags`, {
        tag_number: tagNumber,
        tag_type: '',
        notes: 'Marked as valid from filtered tags review'
      })
      
      toast.success(`Tag "${tagNumber}" marked as valid. It will be included in future reports.`)
      
      // Refresh filtered tags list
      if (currentReport) {
        loadFilteredTags(currentReport.id)
      }
    } catch (error) {
      toastAxiosError(error, 'Failed to validate tag')
    }
  }

  const downloadReport = async (reportId, drawingNumber) => {
    try {
      const response = await api.get(
        `/drawings/${projectId}/reports/${reportId}/download`,
        { responseType: 'blob' }
      )
      
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `tag_report_${drawingNumber.replace(/\//g, '_')}_${new Date().toISOString().split('T')[0]}.xlsx`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      
      toast.success('Report downloaded')
    } catch (error) {
      toastAxiosError(error, 'Failed to download report')
    }
  }

  const deleteReport = async (reportId) => {
    if (!confirm('Are you sure you want to delete this report?')) {
      return
    }
    
    try {
      await api.delete(`/drawings/${projectId}/reports/${reportId}`)
      toast.success('Report deleted')
      
      // If we're viewing the deleted report, clear it
      if (currentReport && currentReport.id === reportId) {
        setCurrentReport(null)
        setReportTags([])
        setFilteredTags([])
        setShowFilteredTags(false)
      }
      
      // Reload the reports list, which will auto-display the new most recent report
      await loadSavedReports()
    } catch (error) {
      toastAxiosError(error, 'Failed to delete report')
    }
  }

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
  }

  const getFilteredAndSortedTags = () => {
    let filtered = reportTags.filter(tag => {
      return (
        (filters.plant === '' || tag.plant === filters.plant) &&
        (filters.module === '' || tag.module === filters.module) &&
        (filters.tagType === '' || tag.tag_type === filters.tagType) &&
        (filters.discipline === '' || tag.discipline === filters.discipline) &&
        (filters.subsystem === '' || tag.subsystem === filters.subsystem) &&
        (filters.page === '' || tag.page_number.toString() === filters.page)
      )
    })

    filtered.sort((a, b) => {
      let aVal = a[sortField]
      let bVal = b[sortField]
      
      if (typeof aVal === 'string') {
        aVal = aVal.toLowerCase()
        bVal = bVal.toLowerCase()
      }

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1
      return 0
    })

    return filtered
  }

  const filteredAndSortedTags = getFilteredAndSortedTags()

  const SortIcon = ({ field }) => {
    if (sortField !== field) return <span style={{ color: 'rgba(209,232,226,0.4)' }} className="ml-1">⇅</span>
    return sortDirection === 'asc' ? 
      <span style={{ color: '#D1E8E2' }} className="ml-1">↑</span> : 
      <span style={{ color: '#D1E8E2' }} className="ml-1">↓</span>
  }

  return (
    <div className="max-w-full mx-auto p-6">
      <div className="mb-6">
        <button
          onClick={() => navigate(`/project/${projectId}`)}
          className="mb-4"
          style={{ color: 'var(--teal-bright)', background: 'none', border: 'none', cursor: 'pointer', fontSize: '14px', fontWeight: 500 }}
        >
          ← Back to Project
        </button>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)', borderBottom: '1px solid var(--border-dim)', paddingBottom: 16, marginBottom: 12 }}>
          Tag Extraction Reports
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
          Generate and manage detailed tag reports from P&ID drawings
        </p>
      </div>

      {/* Generate New Report Section */}
      <div className="card" style={{ marginBottom: 20 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--teal-bright)', marginBottom: 16 }}>Generate New Report</h3>
        <label className="form-group" style={{ marginBottom: 0 }}>
          <span style={{ display: 'block', marginBottom: 8, fontWeight: 500, color: 'var(--text-primary)' }}>Select Drawing</span>
          <div className="flex gap-4">
            <select
              value={selectedDrawing}
              onChange={(e) => setSelectedDrawing(e.target.value)}
              className="flex-1"
            >
              <option value="">-- Select a drawing --</option>
              {drawings.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.drawing_number} - {d.drawing_role || 'No role'} {d.revision ? `(Rev ${d.revision})` : ''}
                </option>
              ))}
            </select>
            <button
              onClick={generateReport}
              disabled={!selectedDrawing || generating}
              className="accent"
              style={{ cursor: !selectedDrawing || generating ? 'not-allowed' : 'pointer' }}
            >
              {generating ? 'Generating...' : 'Generate Report'}
            </button>
          </div>
        </label>
      </div>

      {/* Saved Reports List - Always visible if reports exist */}
      {savedReports.length > 0 && (
        <div className="card" style={{ marginBottom: 20, overflow: 'hidden', padding: 0 }}>
          <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-dim)' }}>
            <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--teal-bright)' }}>
              Saved Reports ({savedReports.length})
            </h3>
          </div>
          <table>
            <thead>
              <tr>
                <th>Drawing Number</th>
                <th>Generated</th>
                <th>Valid Tags</th>
                <th>Filtered Tags</th>
                <th>Pages</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {savedReports.map((report, idx) => (
                <tr 
                  key={report.id} 
                  style={{ 
                    background: currentReport && currentReport.id === report.id 
                      ? 'rgba(20,184,166,0.1)' 
                      : idx % 2 === 0 ? 'var(--bg-card)' : 'rgba(20,184,166,0.03)',
                    cursor: 'pointer'
                  }}
                  onClick={() => displayReport(report)}
                >
                  <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: currentReport && currentReport.id === report.id ? 'var(--teal)' : 'var(--teal-bright)', fontWeight: 600 }}>
                    {report.drawing_number}
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                    {new Date(report.generated_at).toLocaleString()}
                  </td>
                  <td style={{ color: 'var(--teal-bright)', fontWeight: 600 }}>
                    {report.total_tags}
                  </td>
                  <td style={{ color: report.filtered_tags_count > 0 ? 'var(--amber)' : 'var(--text-dim)' }}>
                    {report.filtered_tags_count || 0}
                  </td>
                  <td style={{ color: 'var(--text-secondary)' }}>
                    {report.total_pages}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }} onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => downloadReport(report.id, report.drawing_number)}
                        className="sm accent"
                      >
                        📥 Excel
                      </button>
                      <button
                        onClick={() => deleteReport(report.id)}
                        className="sm danger"
                      >
                        🗑️ Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Current Report Display */}
      {currentReport && (
        <>
          {/* Report Header */}
          <div className="flex justify-between items-center mb-6">
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 600, color: 'var(--teal-bright)', marginBottom: 4 }}>
                {currentReport.drawing_number}
              </h2>
              <p style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                Generated: {new Date(currentReport.generated_at).toLocaleString()}
              </p>
            </div>
            <div className="flex gap-3">
              {currentReport.filtered_tags_count > 0 && (
                <button
                  onClick={() => loadFilteredTags(currentReport.id)}
                  className="accent"
                >
                  📋 View Filtered Tags ({currentReport.filtered_tags_count})
                </button>
              )}
            </div>
          </div>

          {/* Summary Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="stat-card teal">
              <div className="label">Valid Tags</div>
              <div className="value" style={{ fontSize: 32 }}>{currentReport.total_tags}</div>
            </div>
            <div className="stat-card amber">
              <div className="label">Filtered Tags</div>
              <div className="value" style={{ fontSize: 32 }}>{currentReport.filtered_tags_count || 0}</div>
            </div>
            <div className="stat-card green">
              <div className="label">Pages</div>
              <div className="value" style={{ fontSize: 32 }}>{currentReport.total_pages}</div>
            </div>
            <div className="stat-card blue">
              <div className="label">Showing</div>
              <div className="value" style={{ fontSize: 32 }}>{filteredAndSortedTags.length}</div>
            </div>
          </div>

          {/* Filtered Tags View */}
          {showFilteredTags && (
            <div className="card" style={{ marginBottom: 20 }}>
              <div className="flex justify-between items-center mb-4">
                <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--amber)' }}>
                  Filtered Tags ({filteredTags.length})
                </h3>
                <button onClick={() => setShowFilteredTags(false)} className="sm secondary">
                  ✕ Close
                </button>
              </div>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                These tags were filtered out because they don't match the PIMS tagging specification. 
                If a tag should be included, click "Mark as Valid" to add it to your validated tags list.
              </p>
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Tag Number</th>
                      <th>Page</th>
                      <th>Reason</th>
                      <th>Color</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredTags.map((tag, idx) => (
                      <tr key={idx} style={{ background: idx % 2 === 0 ? 'var(--bg-card)' : 'rgba(20,184,166,0.03)' }}>
                        <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--amber)', fontWeight: 600 }}>
                          {tag.tag_number}
                        </td>
                        <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
                          {tag.page_number}
                        </td>
                        <td style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                          {tag.reason}
                        </td>
                        <td>
                          {tag.tag_color && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <div className="color-dot" style={{ backgroundColor: tag.tag_color, width: 20, height: 20 }} />
                              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: 'var(--text-dim)' }}>
                                {tag.tag_color}
                              </span>
                            </div>
                          )}
                        </td>
                        <td>
                          <button
                            onClick={() => markTagAsValid(tag.tag_number)}
                            className="sm accent"
                          >
                            ✓ Mark as Valid
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Filters */}
          {!showFilteredTags && (
            <div className="card" style={{ marginBottom: 20 }}>
              <h3 style={{ fontSize: 15, fontWeight: 600, color: 'var(--teal-bright)', marginBottom: 16 }}>
                Quick Filters
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
                    Plant
                  </label>
                  <select
                    value={filters.plant}
                    onChange={(e) => setFilters({ ...filters, plant: e.target.value })}
                    style={{ width: '100%' }}
                  >
                    <option value="">All Plants</option>
                    {filterOptions.plants.map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
                    Module
                  </label>
                  <select
                    value={filters.module}
                    onChange={(e) => setFilters({ ...filters, module: e.target.value })}
                    style={{ width: '100%' }}
                  >
                    <option value="">All Modules</option>
                    {filterOptions.modules.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
                    Tag Type
                  </label>
                  <select
                    value={filters.tagType}
                    onChange={(e) => setFilters({ ...filters, tagType: e.target.value })}
                    style={{ width: '100%' }}
                  >
                    <option value="">All Types</option>
                    {filterOptions.tagTypes.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
                    Discipline
                  </label>
                  <select
                    value={filters.discipline}
                    onChange={(e) => setFilters({ ...filters, discipline: e.target.value })}
                    style={{ width: '100%' }}
                  >
                    <option value="">All Disciplines</option>
                    {filterOptions.disciplines.map(d => <option key={d} value={d}>{d}</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
                    Subsystem
                  </label>
                  <select
                    value={filters.subsystem}
                    onChange={(e) => setFilters({ ...filters, subsystem: e.target.value })}
                    style={{ width: '100%' }}
                  >
                    <option value="">All Subsystems</option>
                    {filterOptions.subsystems.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 6, fontSize: 13, color: 'var(--text-secondary)' }}>
                    Page
                  </label>
                  <select
                    value={filters.page}
                    onChange={(e) => setFilters({ ...filters, page: e.target.value })}
                    style={{ width: '100%' }}
                  >
                    <option value="">All Pages</option>
                    {filterOptions.pages.map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
              </div>
              <div style={{ marginTop: 12, fontSize: 13, color: 'var(--text-secondary)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>
                  Showing <strong style={{ color: 'var(--teal-bright)' }}>{filteredAndSortedTags.length}</strong> of <strong>{reportTags.length}</strong> tags
                </span>
                {(filters.plant || filters.module || filters.tagType || filters.discipline || filters.subsystem || filters.page) && (
                  <button
                    onClick={() => setFilters({ plant: '', module: '', tagType: '', discipline: '', subsystem: '', page: '' })}
                    className="sm secondary"
                  >
                    Clear Filters
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Tag Table */}
          {!showFilteredTags && (
            <div className="card" style={{ overflow: 'hidden', padding: 0 }}>
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th onClick={() => handleSort('plant')} style={{ cursor: 'pointer' }}>Plant <SortIcon field="plant" /></th>
                      <th onClick={() => handleSort('module')} style={{ cursor: 'pointer' }}>Module <SortIcon field="module" /></th>
                      <th onClick={() => handleSort('tag_number')} style={{ cursor: 'pointer' }}>Tag Number <SortIcon field="tag_number" /></th>
                      <th onClick={() => handleSort('tag_type')} style={{ cursor: 'pointer' }}>Tag Type <SortIcon field="tag_type" /></th>
                      <th onClick={() => handleSort('subsystem')} style={{ cursor: 'pointer' }}>Subsystem <SortIcon field="subsystem" /></th>
                      <th onClick={() => handleSort('discipline')} style={{ cursor: 'pointer' }}>Discipline <SortIcon field="discipline" /></th>
                      <th onClick={() => handleSort('page_number')} style={{ cursor: 'pointer' }}>Page <SortIcon field="page_number" /></th>
                      <th>Color</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredAndSortedTags.map((tag, idx) => (
                      <tr key={idx} style={{ background: idx % 2 === 0 ? 'var(--bg-card)' : 'rgba(20,184,166,0.03)' }}>
                        <td>{tag.plant}</td>
                        <td style={{ color: 'var(--teal-bright)', fontWeight: 600 }}>{tag.module}</td>
                        <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--teal-bright)', fontWeight: 600 }}>
                          {tag.tag_number}
                        </td>
                        <td style={{ fontWeight: 500 }}>{tag.tag_type}</td>
                        <td style={{ color: 'var(--text-dim)' }}>{tag.subsystem || '-'}</td>
                        <td>
                          <span className={`badge ${
                            tag.discipline === 'Instrument' ? 'amber' :
                            tag.discipline === 'Piping' ? 'teal' :
                            tag.discipline === 'Mechanical' ? 'blue' :
                            tag.discipline === 'Electrical' ? 'green' : 'gray'
                          }`}>
                            {tag.discipline}
                          </span>
                        </td>
                        <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>{tag.page_number}</td>
                        <td>
                          {tag.tag_color && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <div className="color-dot" style={{ backgroundColor: tag.tag_color, width: 20, height: 20 }} title={tag.tag_color} />
                              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: 'var(--text-dim)' }}>
                                {tag.tag_color}
                              </span>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* Empty State - No Reports */}
      {savedReports.length === 0 && (
        <div className="empty-state">
          <div className="icon">📊</div>
          <h3>No reports yet</h3>
          <p>Generate your first tag extraction report by selecting a drawing above</p>
        </div>
      )}
    </div>
  )
}
