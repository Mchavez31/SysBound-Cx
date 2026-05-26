import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../lib/api'
import toast from 'react-hot-toast'

const PLANTS = ['WCF', 'WOC', 'DrillSites', 'KPAD', 'Infrastructure']

export default function PalettesPage() {
  const { projectId } = useParams()
  const [selectedPlant, setSelectedPlant] = useState(PLANTS[0])
  const [selectedDtype, setSelectedDtype] = useState('')
  const [search, setSearch] = useState('')
  const [uploadPlant, setUploadPlant] = useState('WCF')
  const [uploading, setUploading] = useState(false)
  const qc = useQueryClient()

  const { data: palettes = [], isLoading } = useQuery({
    queryKey: ['palettes', projectId, selectedPlant, selectedDtype],
    queryFn: () => api.get(`/palettes/${projectId}`, { params: { plant: selectedPlant, drawing_type: selectedDtype || undefined } }).then((r) => r.data),
  })

  const { data: summary = [] } = useQuery({
    queryKey: ['palette-summary', projectId],
    queryFn: () => api.get(`/palettes/${projectId}/summary`).then((r) => r.data),
  })

  const dtypes = [...new Set(summary.filter((s) => s.plant === selectedPlant).map((s) => s.drawing_type))]

  async function handleUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await api.post(`/palettes/${projectId}/upload?plant=${encodeURIComponent(uploadPlant)}`, form)
      toast.success(`Imported ${res.data.imported} color entries for ${uploadPlant}`)
      qc.invalidateQueries(['palettes', projectId])
      qc.invalidateQueries(['palette-summary', projectId])
      setSelectedPlant(uploadPlant)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const filtered = palettes.filter((p) =>
    !search || p.subsystem_number.toLowerCase().includes(search.toLowerCase()) || (p.subsystem_description || '').toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div style={{ padding: '28px 28px 48px' }}>
      <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)', borderBottom: '1px solid var(--border-dim)', paddingBottom: 16, marginBottom: 24 }}>Color palettes</h1>
      <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginBottom: 24 }}>Upload Excel palette files for each plant. These colors are used to apply systemization highlights to drawings.</p>

      {/* Upload section */}
      <div className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 14, color: 'var(--teal-bright)' }}>Upload palette file</h2>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="form-group" style={{ marginBottom: 0, minWidth: 160 }}>
            <label>Plant</label>
            <select value={uploadPlant} onChange={(e) => setUploadPlant(e.target.value)}>
              {PLANTS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <label className="section-label" style={{ marginBottom: 5 }}>Excel palette file (.xlsx)</label>
            <label className="drop-zone">
              {uploading ? 'Uploading…' : 'Click to choose file or drag & drop'}
              <input type="file" accept=".xlsx" onChange={handleUpload} disabled={uploading} style={{ display: 'none' }} />
            </label>
          </div>
        </div>
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-dim)' }}>
          Supports the standard palette format: Color (cell fill), System Number, Description, R, G, B columns. Sheet names identify drawing types automatically.
        </div>
      </div>

      {/* Filter & browse */}
      <div className="card" style={{ overflow: 'hidden', padding: 0 }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border-dim)', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flex: 1 }}>
            {PLANTS.map((p) => {
              const count = summary.filter((s) => s.plant === p).reduce((a, s) => a + s.count, 0)
              const isActive = selectedPlant === p
              return (
                <button 
                  key={p} 
                  onClick={() => { setSelectedPlant(p); setSelectedDtype('') }}
                  className={isActive ? 'accent' : 'sm'}
                  style={{ 
                    background: isActive ? 'var(--teal)' : 'var(--bg-elevated)',
                    color: isActive ? '#020f0e' : 'var(--text-secondary)'
                  }}
                >
                  {p} {count > 0 && <span style={{ opacity: 0.7, fontSize: 11 }}>({count})</span>}
                </button>
              )
            })}
          </div>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search subsystem…" style={{ width: 200 }} />
        </div>

        {/* Drawing type sub-filter */}
        {dtypes.length > 0 && (
          <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--border-dim)', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button onClick={() => setSelectedDtype('')} className="sm" style={{ background: !selectedDtype ? 'var(--teal-dim)' : 'var(--bg-elevated)', color: !selectedDtype ? 'var(--teal-bright)' : 'var(--text-secondary)', fontWeight: !selectedDtype ? 600 : 400 }}>All types</button>
            {dtypes.map((d) => (
              <button key={d} onClick={() => setSelectedDtype(d)} className="sm" style={{ background: selectedDtype === d ? 'var(--teal-dim)' : 'var(--bg-elevated)', color: selectedDtype === d ? 'var(--teal-bright)' : 'var(--text-secondary)', fontWeight: selectedDtype === d ? 600 : 400 }}>{d}</button>
            ))}
          </div>
        )}

        {isLoading ? (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-dim)' }}>Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="empty-state">
            <div className="icon">🎨</div>
            <h3>No palette entries</h3>
            <p>Upload a palette file for <strong>{selectedPlant}</strong> using the form above.</p>
          </div>
        ) : (
          <table>
            <thead><tr><th style={{ width: 52 }}>Color</th><th>Subsystem</th><th>Description</th><th>Drawing type</th><th>Hex</th></tr></thead>
            <tbody>
              {filtered.map((p, idx) => (
                <tr key={p.id} style={{ background: idx % 2 === 0 ? 'var(--bg-card)' : 'rgba(20,184,166,0.03)' }}>
                  <td><div className="color-dot" style={{ background: p.hex_color, width: 22, height: 22 }} /></td>
                  <td style={{ fontWeight: 600, color: 'var(--teal-bright)', fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>{p.subsystem_number}</td>
                  <td>{p.subsystem_description || '—'}</td>
                  <td><span className="badge gray">{p.drawing_type}</span></td>
                  <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-dim)' }}>{p.hex_color}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {filtered.length > 0 && (
          <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border-dim)', fontSize: 12, color: 'var(--text-dim)' }}>
            {filtered.length} entr{filtered.length === 1 ? 'y' : 'ies'}{search && ` matching "${search}"`}
          </div>
        )}
      </div>
    </div>
  )
}
