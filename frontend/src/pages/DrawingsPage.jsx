import { useEffect, useRef, useState } from 'react'
import { useParams, useLocation, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api, { toastAxiosError } from '../lib/api'
import toast from 'react-hot-toast'

const ROLES = [
  { value: 'current_systemized', label: 'Current Systemized' },
  { value: 'prior_systemized', label: 'Prior Systemized' },
  { value: 'new_engineering', label: 'New Engineering' },
]

function comparisonLabel(type) {
  const m = {
    new_vs_systemized: 'New vs Systemized',
    systemized_vs_systemized: 'Systemized vs Systemized (weekly report)',
    new_vs_new: 'New vs New (pre-systemization)',
  }
  return m[type] || type
}

function inferType(a, b) {
  const s = new Set([a, b])
  if (s.has('current_systemized') && s.has('new_engineering')) return 'new_vs_systemized'
  if (s.has('current_systemized') && s.has('prior_systemized')) return 'systemized_vs_systemized'
  return 'new_vs_new'
}

export default function DrawingsPage() {
  const { projectId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [file, setFile] = useState(null)
  const [role, setRole] = useState('new_engineering')
  const [manualDn, setManualDn] = useState('')
  const [manualDt, setManualDt] = useState('')
  const [showManual, setShowManual] = useState(false)

  const [selA, setSelA] = useState('')
  const [selB, setSelB] = useState('')

  const [compareBusy, setCompareBusy] = useState(false)
  const [comparePct, setComparePct] = useState(0)
  const [compareMsg, setCompareMsg] = useState('')
  const comparePollRef = useRef(null)

  useEffect(() => {
    if (location.hash === '#comparisons') {
      document.getElementById('comparisons')?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [location])

  const { data, isLoading } = useQuery({
    queryKey: ['drawings', projectId],
    queryFn: () => api.get(`/drawings/${projectId}`).then((r) => r.data),
  })

  const drawings = data?.drawings || []

  const uploadMut = useMutation({
    mutationFn: async () => {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('drawing_role', role)
      if (manualDn) fd.append('manual_drawing_number', manualDn)
      if (manualDt) fd.append('manual_drawing_type', manualDt)
      return api.post(`/drawings/${projectId}/upload`, fd)
    },
    onSuccess: () => {
      toast.success('Drawing uploaded')
      qc.invalidateQueries({ queryKey: ['drawings', projectId] })
      setFile(null)
      setManualDn('')
      setManualDt('')
      setShowManual(false)
    },
    onError: (e) => toastAxiosError(e, 'Upload failed'),
  })

  useEffect(() => {
    return () => {
      if (comparePollRef.current) {
        clearTimeout(comparePollRef.current)
        comparePollRef.current = null
      }
    }
  }, [])

  async function runCompare() {
    if (!selA || !selB || selA === selB || compareBusy) return
    setCompareBusy(true)
    setComparePct(0)
    setCompareMsg('Starting…')
    if (comparePollRef.current) {
      clearTimeout(comparePollRef.current)
      comparePollRef.current = null
    }
    try {
      const { data } = await api.post(
        `/drawings/${projectId}/compare`,
        { drawing_id_a: selA, drawing_id_b: selB },
        { timeout: 600000 },
      )
      const cid = data?.comparison_id
      if (!cid || typeof cid !== 'string') {
        setCompareBusy(false)
        setComparePct(0)
        setCompareMsg('')
        toast.error('Invalid response from server (missing comparison id). Restart the API if this persists.')
        return
      }

      const progressPath = `/drawings/${encodeURIComponent(String(projectId).trim())}/comparisons/${encodeURIComponent(cid.trim())}/progress`
      let pollFailures = 0

      const schedulePoll = (delayMs) => {
        comparePollRef.current = setTimeout(runPoll, delayMs)
      }

      const runPoll = async () => {
        try {
          const pr = await api.get(progressPath, { timeout: 120000 })
          pollFailures = 0
          const p = pr.data
          setComparePct(typeof p.percent === 'number' ? p.percent : 0)
          setCompareMsg(p.message || '')
          if (p.done) {
            if (comparePollRef.current) {
              clearTimeout(comparePollRef.current)
              comparePollRef.current = null
            }
            setCompareBusy(false)
            if (p.error) {
              toast.error(typeof p.error === 'string' ? p.error : 'Comparison failed')
              setComparePct(0)
              setCompareMsg('')
              return
            }
            toast.success('Comparison complete')
            qc.invalidateQueries({ queryKey: ['comparisons', projectId] })
            qc.invalidateQueries({ queryKey: ['drawings', projectId] })
            navigate(`/project/${projectId}/comparison/${cid}`)
            setComparePct(0)
            setCompareMsg('')
            return
          }
          schedulePoll(450)
        } catch (e) {
          pollFailures += 1
          const st = e.response?.status
          if (st === 404) {
            if (comparePollRef.current) {
              clearTimeout(comparePollRef.current)
              comparePollRef.current = null
            }
            setCompareBusy(false)
            toast.error(
              'Progress not found (404). Use the latest backend with comparison progress columns; restart the API after updating. Check Comparison history if the run still finished.',
            )
            return
          }
          if (pollFailures < 8) {
            schedulePoll(Math.min(3000, 450 + pollFailures * 400))
            return
          }
          if (comparePollRef.current) {
            clearTimeout(comparePollRef.current)
            comparePollRef.current = null
          }
          setCompareBusy(false)
          toast.error(
            'Lost connection to progress updates after several tries. The comparison may still finish — check Comparison history in a minute.',
            { duration: 10000 },
          )
        }
      }

      schedulePoll(0)
    } catch (e) {
      setCompareBusy(false)
      setComparePct(0)
      setCompareMsg('')
      toastAxiosError(e, 'Comparison failed')
    }
  }

  const { data: comparisons = [] } = useQuery({
    queryKey: ['comparisons', projectId],
    queryFn: () => api.get(`/drawings/${projectId}/comparisons`).then((r) => r.data),
  })

  const roleA = drawings.find((d) => d.id === selA)?.drawing_role
  const roleB = drawings.find((d) => d.id === selB)?.drawing_role
  const previewType = roleA && roleB ? inferType(roleA, roleB) : null

  const deleteMut = useMutation({
    mutationFn: (id) => api.delete(`/drawings/${projectId}/${id}`),
    onSuccess: () => {
      toast.success('Deleted')
      qc.invalidateQueries({ queryKey: ['drawings', projectId] })
    },
    onError: (e) => toastAxiosError(e, 'Delete failed'),
  })

  const deleteComparisonMut = useMutation({
    mutationFn: (comparisonId) => api.delete(`/drawings/${projectId}/comparisons/${comparisonId}`),
    onSuccess: () => {
      toast.success('Comparison deleted')
      qc.invalidateQueries({ queryKey: ['comparisons', projectId] })
    },
    onError: (e) => toastAxiosError(e, 'Delete failed'),
  })

  return (
    <div style={{ padding: '28px 28px 48px', maxWidth: 1100 }}>
      <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)', borderBottom: '1px solid var(--border-dim)', paddingBottom: 16, marginBottom: 24 }}>Drawings</h1>
      <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginBottom: 24 }}>
        Upload PDFs, run comparisons between revisions, and export reports.
      </p>

      {/* Section 1 */}
      <section className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 14, color: 'var(--teal-bright)' }}>1. Upload PDF</h2>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px', gap: 16, alignItems: 'end' }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>PDF file</label>
            <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Drawing role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, cursor: 'pointer' }}>
          <input type="checkbox" checked={showManual} onChange={(e) => setShowManual(e.target.checked)} />
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Enter drawing number / type manually (if auto-detect failed)</span>
        </label>
        {showManual && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
            <div className="form-group">
              <label>Drawing number</label>
              <input value={manualDn} onChange={(e) => setManualDn(e.target.value)} placeholder="e.g. WILG-..." />
            </div>
            <div className="form-group">
              <label>Drawing type</label>
              <input value={manualDt} onChange={(e) => setManualDt(e.target.value)} placeholder="P&ID, SLD, …" />
            </div>
          </div>
        )}
        <button
          type="button"
          className="accent"
          style={{ marginTop: 16 }}
          disabled={!file || uploadMut.isPending}
          onClick={() => uploadMut.mutate()}
        >
          {uploadMut.isPending ? 'Uploading…' : 'Upload'}
        </button>
      </section>

      {/* Table */}
      <section className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12, color: 'var(--teal-bright)' }}>Uploaded drawings</h2>
        {isLoading ? (
          <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
        ) : drawings.length === 0 ? (
          <p style={{ color: 'var(--text-dim)' }}>No drawings yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead><tr><th>Drawing No.</th><th>Title</th><th>Type</th><th>Plant</th><th>Rev</th><th>Role</th><th>Uploaded</th><th /></tr></thead>
              <tbody>
                {drawings.map((d, idx) => (
                  <tr key={d.id} style={{ background: idx % 2 === 0 ? 'var(--bg-card)' : 'rgba(20,184,166,0.03)' }}>
                    <td style={{ fontWeight: 600, fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--teal-bright)' }}>{d.drawing_number}</td>
                    <td>{d.drawing_title || '—'}</td>
                    <td>{d.drawing_type || d.detected_drawing_type || '—'}</td>
                    <td>{d.plant || d.detected_plant || '—'}</td>
                    <td>{d.revision || d.detected_revision || '—'}</td>
                    <td>
                      <span className="badge gray">{d.drawing_role?.replace(/_/g, ' ')}</span>
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--text-dim)' }}>{d.created_at?.slice(0, 10) || '—'}</td>
                    <td>
                      <button type="button" className="sm danger" onClick={() => deleteMut.mutate(d.id)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {drawings.some((d) => d.extraction_error) && (
          <p style={{ fontSize: 12, color: 'var(--amber)', marginTop: 8 }}>
            Some files had partial text extraction. Use manual fields on next upload if needed.
          </p>
        )}
      </section>

      {/* Section 2 */}
      <section className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12, color: 'var(--teal-bright)' }}>2. Run comparison</h2>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div className="form-group">
            <label>Drawing A</label>
            <select value={selA} onChange={(e) => setSelA(e.target.value)}>
              <option value="">— Select —</option>
              {drawings.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.drawing_number} ({d.drawing_role})
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>Drawing B</label>
            <select value={selB} onChange={(e) => setSelB(e.target.value)}>
              <option value="">— Select —</option>
              {drawings.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.drawing_number} ({d.drawing_role})
                </option>
              ))}
            </select>
          </div>
        </div>
        {previewType && (
          <p style={{ marginTop: 10, fontSize: 13, color: 'var(--teal-bright)' }}>
            This will run: <strong>{comparisonLabel(previewType)}</strong>
          </p>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 14, marginTop: 16 }}>
          <button
            type="button"
            className="accent"
            disabled={!selA || !selB || selA === selB || compareBusy}
            onClick={() => runCompare()}
          >
            {compareBusy ? 'Running…' : 'Run comparison'}
          </button>
          {compareBusy && (
            <div style={{ flex: '1 1 220px', minWidth: 200, maxWidth: 480 }}>
              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{
                    width: `${Math.min(100, Math.max(0, comparePct))}%`,
                  }}
                />
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6, lineHeight: 1.4 }}>
                <strong>{Math.round(comparePct)}%</strong>
                {compareMsg ? ` — ${compareMsg}` : ''}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Section 3 */}
      <section className="card" id="comparisons">
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12, color: 'var(--teal-bright)' }}>3. Comparison history</h2>
        {comparisons.length === 0 ? (
          <p style={{ color: 'var(--text-dim)' }}>No comparisons yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead><tr><th>Date</th><th>Drawing A</th><th>Drawing B</th><th>Type</th><th>New</th><th>Removed</th><th>Changed</th><th style={{ minWidth: 220 }}>Actions</th></tr></thead>
              <tbody>
                {comparisons.map((c, idx) => (
                  <tr key={c.id} style={{ background: idx % 2 === 0 ? 'var(--bg-card)' : 'rgba(20,184,166,0.03)' }}>
                    <td style={{ fontSize: 12, color: 'var(--text-dim)' }}>{c.run_at?.slice(0, 19)?.replace('T', ' ') || '—'}</td>
                    <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--teal-bright)' }}>{c.drawing_a}</td>
                    <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--teal-bright)' }}>{c.drawing_b}</td>
                    <td>
                      <span className="badge blue">{comparisonLabel(c.comparison_type)}</span>
                    </td>
                    <td>{c.total_new}</td>
                    <td>{c.total_removed}</td>
                    <td>{c.total_subsystem_changes}</td>
                    <td style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <Link to={`/project/${projectId}/comparison/${c.id}`} style={{ color: 'var(--teal-bright)', fontWeight: 500, textDecoration: 'none' }}>
                        View
                      </Link>
                      <button
                        type="button"
                        className="sm"
                        style={{ border: 'none', background: 'none', color: 'var(--teal-bright)', padding: 0, cursor: 'pointer' }}
                        onClick={async () => {
                          try {
                            const res = await api.get(`/drawings/${projectId}/report`, {
                              params: { comparison_id: c.id, format: 'excel' },
                              responseType: 'blob',
                            })
                            const url = URL.createObjectURL(res.data)
                            const a = document.createElement('a')
                            a.href = url
                            a.download = `comparison-${c.id}.xlsx`
                            a.click()
                            URL.revokeObjectURL(url)
                          } catch {
                            toast.error('Download failed')
                          }
                        }}
                      >
                        Excel
                      </button>
                      <button
                        type="button"
                        className="sm danger"
                        style={{ border: 'none', background: 'none', padding: 0 }}
                        disabled={deleteComparisonMut.isPending}
                        onClick={() => {
                          if (!window.confirm('Delete this comparison from history? This cannot be undone.')) return
                          deleteComparisonMut.mutate(c.id)
                        }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
