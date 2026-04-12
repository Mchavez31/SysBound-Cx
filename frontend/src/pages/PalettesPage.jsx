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
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>Color palettes</h1>
        <p style={{ color: '#6b7280', fontSize: 14 }}>Upload Excel palette files for each plant. These colors are used to apply systemization highlights to drawings.</p>
      </div>

      {/* Upload section */}
      <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 12, padding: '18px 20px', marginBottom: 20 }}>
        <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>Upload palette file</h2>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 160 }}>
            <div style={{ fontSize: 11, fontWeight: 500, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 5 }}>Plant</div>
            <select value={uploadPlant} onChange={(e) => setUploadPlant(e.target.value)} style={{ width: '100%' }}>
              {PLANTS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 11, fontWeight: 500, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 5 }}>Excel palette file (.xlsx)</div>
            <label style={{ display: 'block', border: '2px dashed #d1d5db', borderRadius: 8, padding: '10px 16px', cursor: 'pointer', background: uploading ? '#f9fafb' : 'white', transition: 'border-color 0.15s', textAlign: 'center', color: '#6b7280', fontSize: 13 }}>
              {uploading ? 'Uploading…' : 'Click to choose file or drag & drop'}
              <input type="file" accept=".xlsx" onChange={handleUpload} disabled={uploading} style={{ display: 'none' }} />
            </label>
          </div>
        </div>
        <div style={{ marginTop: 10, fontSize: 12, color: '#9ca3af' }}>
          Supports the standard palette format: Color (cell fill), System Number, Description, R, G, B columns. Sheet names identify drawing types automatically.
        </div>
      </div>

      {/* Filter & browse */}
      <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #f3f4f6', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flex: 1 }}>
            {PLANTS.map((p) => {
              const count = summary.filter((s) => s.plant === p).reduce((a, s) => a + s.count, 0)
              return (
                <button key={p} onClick={() => { setSelectedPlant(p); setSelectedDtype('') }}
                  style={{ padding: '5px 12px', fontSize: 12, fontWeight: selectedPlant === p ? 600 : 400, background: selectedPlant === p ? '#1a2744' : '#f3f4f6', color: selectedPlant === p ? 'white' : '#374151', border: 'none', borderRadius: 6 }}>
                  {p} {count > 0 && <span style={{ opacity: 0.7, fontSize: 11 }}>({count})</span>}
                </button>
              )
            })}
          </div>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search subsystem…" style={{ width: 200, fontSize: 12, padding: '6px 10px' }} />
        </div>

        {/* Drawing type sub-filter */}
        {dtypes.length > 0 && (
          <div style={{ padding: '8px 16px', borderBottom: '1px solid #f3f4f6', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button onClick={() => setSelectedDtype('')} style={{ padding: '3px 10px', fontSize: 11, background: !selectedDtype ? '#eff6ff' : '#f9fafb', color: !selectedDtype ? '#1d4ed8' : '#6b7280', border: 'none', borderRadius: 4, fontWeight: !selectedDtype ? 600 : 400 }}>All types</button>
            {dtypes.map((d) => (
              <button key={d} onClick={() => setSelectedDtype(d)} style={{ padding: '3px 10px', fontSize: 11, background: selectedDtype === d ? '#eff6ff' : '#f9fafb', color: selectedDtype === d ? '#1d4ed8' : '#6b7280', border: 'none', borderRadius: 4, fontWeight: selectedDtype === d ? 600 : 400 }}>{d}</button>
            ))}
          </div>
        )}

        {isLoading ? (
          <div style={{ padding: 32, textAlign: 'center', color: '#6b7280' }}>Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="empty-state">
            <div className="icon">🎨</div>
            <h3>No palette entries</h3>
            <p>Upload a palette file for <strong>{selectedPlant}</strong> using the form above.</p>
          </div>
        ) : (
          <table>
            <thead>
              <tr><th style={{ width: 52 }}>Color</th><th>Subsystem</th><th>Description</th><th>Drawing type</th><th>Hex</th></tr>
            </thead>
            <tbody>
              {filtered.map((p) => (
                <tr key={p.id}>
                  <td><div className="color-dot" style={{ background: p.hex_color, width: 22, height: 22 }} /></td>
                  <td style={{ fontWeight: 500 }}>{p.subsystem_number}</td>
                  <td style={{ color: '#374151' }}>{p.subsystem_description || '—'}</td>
                  <td><span className="badge gray">{p.drawing_type}</span></td>
                  <td style={{ fontFamily: 'monospace', fontSize: 12, color: '#6b7280' }}>{p.hex_color}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {filtered.length > 0 && (
          <div style={{ padding: '10px 16px', borderTop: '1px solid #f3f4f6', fontSize: 12, color: '#6b7280' }}>
            {filtered.length} entr{filtered.length === 1 ? 'y' : 'ies'}{search && ` matching "${search}"`}
          </div>
        )}
      </div>
    </div>
  )
}
