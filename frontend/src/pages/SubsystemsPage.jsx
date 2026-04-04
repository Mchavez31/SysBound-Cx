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
      const res = await api.post(`/subsystems/${projectId}/upload`, form, { headers: { 'Content-Type': 'multipart/form-data' } })
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
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>Subsystem register</h1>
        <p style={{ color: '#6b7280', fontSize: 14 }}>Upload the PIMS subsystem register for this project. This validates all subsystem assignments and powers the color lookup.</p>
      </div>

      {/* Upload */}
      <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 12, padding: '18px 20px', marginBottom: 20 }}>
        <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Upload subsystem register</h2>
        <label style={{ display: 'inline-block', border: '2px dashed #d1d5db', borderRadius: 8, padding: '12px 20px', cursor: 'pointer', color: '#6b7280', fontSize: 13, background: uploading ? '#f9fafb' : 'white' }}>
          {uploading ? 'Importing…' : '📂  Choose Excel file (.xlsx)  —  Subsystem, Description, System columns'}
          <input type="file" accept=".xlsx" onChange={handleUpload} disabled={uploading} style={{ display: 'none' }} />
        </label>
        {subsystems.length > 0 && (
          <span style={{ marginLeft: 14, fontSize: 13, color: '#6b7280' }}>Currently <strong>{subsystems.length}</strong> subsystems loaded</span>
        )}
      </div>

      {/* Browse */}
      <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid #f3f4f6', display: 'flex', gap: 10, alignItems: 'center' }}>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by number or description…" style={{ flex: 1, fontSize: 12, padding: '7px 10px' }} />
          <span style={{ fontSize: 12, color: '#6b7280', whiteSpace: 'nowrap' }}>{filtered.length} of {subsystems.length}</span>
        </div>

        {isLoading ? (
          <div style={{ padding: 32, textAlign: 'center', color: '#6b7280' }}>Loading…</div>
        ) : subsystems.length === 0 ? (
          <div className="empty-state">
            <div className="icon">📋</div>
            <h3>No subsystems loaded</h3>
            <p>Upload the PIMS Subsystem Register Excel file above. Expects columns: Subsystem, Description, System.</p>
          </div>
        ) : Object.keys(groups).length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#6b7280', fontSize: 13 }}>No results for "{search}"</div>
        ) : (
          <div>
            {Object.entries(groups).sort(([a], [b]) => Number(a) - Number(b)).map(([group, items]) => (
              <div key={group}>
                <div style={{ padding: '6px 16px', background: '#f9fafb', fontSize: 11, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid #f3f4f6', borderTop: '1px solid #f3f4f6' }}>
                  System {group} · {items.length} subsystem{items.length !== 1 ? 's' : ''}
                </div>
                <table>
                  <tbody>
                    {items.map((s) => (
                      <tr key={s.id}>
                        <td style={{ width: 90, fontWeight: 600, color: '#1d4ed8', fontFamily: 'monospace', fontSize: 13 }}>{s.number}</td>
                        <td style={{ color: '#374151' }}>{s.description}</td>
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
