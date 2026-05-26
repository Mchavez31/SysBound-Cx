import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/api'
import toast from 'react-hot-toast'

export default function SubsystemsPage() {
  const { projectId } = useParams()
  const [search, setSearch] = useState('')
  const [uploading, setUploading] = useState(false)
  const qc = useQueryClient()

  const { data: subsystems = [], isLoading } = useQuery({
    queryKey: ['subsystems', projectId],
    queryFn: () => api.get(`/subsystems/${projectId}`).then((r) => r.data),
  })

  async function handleUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await api.post(`/subsystems/${projectId}/upload`, form)
      toast.success(`Imported ${res.data.imported} subsystems`)
      qc.invalidateQueries(['subsystems', projectId])
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const filtered = subsystems.filter((s) =>
    !search ||
    s.number.toLowerCase().includes(search.toLowerCase()) ||
    s.description.toLowerCase().includes(search.toLowerCase())
  )

  // Group by system group
  const groups = {}
  filtered.forEach((s) => {
    const g = s.system_group || s.number.split('-')[0]
    if (!groups[g]) groups[g] = []
    groups[g].push(s)
  })

  return (
    <div style={{ padding: '28px 28px 48px' }}>
      <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)', borderBottom: '1px solid var(--border-dim)', paddingBottom: 16, marginBottom: 24 }}>Subsystem register</h1>
      <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginBottom: 24 }}>Upload the PIMS subsystem register for this project. This validates all subsystem assignments and powers the color lookup.</p>

      {/* Upload */}
      <div className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12, color: 'var(--teal-bright)' }}>Upload subsystem register</h2>
        <label className="drop-zone">
          {uploading ? 'Importing…' : '📂  Choose Excel file (.xlsx)  —  Subsystem, Description, System columns'}
          <input type="file" accept=".xlsx" onChange={handleUpload} disabled={uploading} style={{ display: 'none' }} />
        </label>
        {subsystems.length > 0 && (
          <span style={{ marginLeft: 14, fontSize: 13, color: 'var(--text-secondary)' }}>Currently <strong style={{ color: 'var(--teal-bright)' }}>{subsystems.length}</strong> subsystems loaded</span>
        )}
      </div>

      {/* Browse */}
      <div className="card" style={{ overflow: 'hidden', padding: 0 }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-dim)', display: 'flex', gap: 10, alignItems: 'center' }}>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by number or description…" style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>{filtered.length} of {subsystems.length}</span>
        </div>

        {isLoading ? (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-dim)' }}>Loading…</div>
        ) : subsystems.length === 0 ? (
          <div className="empty-state">
            <div className="icon">📋</div>
            <h3>No subsystems loaded</h3>
            <p>Upload the PIMS Subsystem Register Excel file above. Expects columns: Subsystem, Description, System.</p>
          </div>
        ) : Object.keys(groups).length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-dim)', fontSize: 13 }}>No results for "{search}"</div>
        ) : (
          <div>
            {Object.entries(groups).sort(([a], [b]) => Number(a) - Number(b)).map(([group, items]) => (
              <div key={group}>
                <div className="section-label" style={{ padding: '6px 16px', background: 'var(--bg-elevated)', borderBottom: '1px solid var(--border-dim)', borderTop: '1px solid var(--border-dim)' }}>
                  System {group} · {items.length} subsystem{items.length !== 1 ? 's' : ''}
                </div>
                <table>
                  <tbody>
                    {items.map((s, idx) => (
                      <tr key={s.id} style={{ background: idx % 2 === 0 ? 'var(--bg-card)' : 'rgba(20,184,166,0.03)' }}>
                        <td style={{ width: 90, fontWeight: 600, color: 'var(--teal-bright)', fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>{s.number}</td>
                        <td>{s.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
