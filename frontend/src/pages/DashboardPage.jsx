import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import useProjectStore from '../hooks/useProjectStore'
import api from '../lib/api'

function StatCard({ label, value, sub, accent }) {
  return (
    <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 10, padding: '16px 20px' }}>
      <div style={{ fontSize: 12, color: '#6b7280', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 600, color: accent || '#111827', lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: '#6b7280', marginTop: 5 }}>{sub}</div>}
    </div>
  )
}

export default function DashboardPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const activeProject = useProjectStore((s) => s.activeProject)

  const { data: paletteSummary = [] } = useQuery({
    queryKey: ['palette-summary', projectId],
    queryFn: () => api.get(`/palettes/${projectId}/summary`).then((r) => r.data),
  })

  const { data: subsystems = [] } = useQuery({
    queryKey: ['subsystems', projectId],
    queryFn: () => api.get(`/subsystems/${projectId}`).then((r) => r.data),
  })

  const totalPaletteEntries = paletteSummary.reduce((sum, p) => sum + p.count, 0)
  const plants = [...new Set(paletteSummary.map((p) => p.plant))]

  return (
    <div style={{ padding: '28px 28px 48px' }}>
      {/* Page header */}
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: '#111827', marginBottom: 4 }}>{activeProject?.name || 'Project Dashboard'}</h1>
        <p style={{ color: '#6b7280', fontSize: 14 }}>
          {activeProject?.client && <span>{activeProject.client} · </span>}
          {activeProject?.facility_type && <span>{activeProject.facility_type} · </span>}
          {activeProject?.description}
        </p>
      </div>

      {/* Stats grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
        <StatCard label="Drawings" value="0" sub="Upload PDFs to get started" />
        <StatCard label="Tags tracked" value="0" sub="Across all drawings" />
        <StatCard label="Subsystems" value={subsystems.length} sub={subsystems.length > 0 ? 'In register' : 'Upload register'} accent={subsystems.length > 0 ? '#2563eb' : undefined} />
        <StatCard label="Color palettes" value={totalPaletteEntries} sub={paletteSummary.length > 0 ? `${plants.length} plant${plants.length !== 1 ? 's' : ''}` : 'Upload palette files'} accent={totalPaletteEntries > 0 ? '#2563eb' : undefined} />
      </div>

      {/* Setup checklist (shown when project is new) */}
      {(paletteSummary.length === 0 || subsystems.length === 0) && (
        <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 12, padding: '20px 24px', marginBottom: 24 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Project setup checklist</h2>
          {[
            { done: paletteSummary.length > 0, label: 'Upload color palette files', desc: 'Upload the Excel palette files for each plant (WCF, WOC, DrillSites, KPAD, Infrastructure)', action: () => navigate(`/project/${projectId}/palettes`), actionLabel: 'Go to Palettes' },
            { done: subsystems.length > 0, label: 'Upload subsystem register', desc: 'Upload the PIMS subsystem register so the app can validate assignments', action: () => navigate(`/project/${projectId}/subsystems`), actionLabel: 'Go to Subsystems' },
            { done: false, label: 'Upload drawings', desc: 'Upload systemized PDFs (current) and new engineering PDFs to compare', action: () => navigate(`/project/${projectId}/drawings`), actionLabel: 'Go to Drawings', disabled: paletteSummary.length === 0 || subsystems.length === 0 },
          ].map(({ done, label, desc, action, actionLabel, disabled }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '12px 0', borderBottom: '1px solid #f3f4f6' }}>
              <div style={{ width: 22, height: 22, borderRadius: '50%', background: done ? '#16a34a' : '#f3f4f6', border: `2px solid ${done ? '#16a34a' : '#d1d5db'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 2 }}>
                {done && <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: done ? '#6b7280' : '#111827', textDecoration: done ? 'line-through' : 'none' }}>{label}</div>
                <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 2 }}>{desc}</div>
              </div>
              {!done && (
                <button onClick={action} disabled={disabled} className="sm" style={{ flexShrink: 0, opacity: disabled ? 0.4 : 1 }}>{actionLabel}</button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Palette summary */}
      {paletteSummary.length > 0 && (
        <div style={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid #f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h2 style={{ fontSize: 14, fontWeight: 600 }}>Color palette coverage</h2>
            <button className="sm" onClick={() => navigate(`/project/${projectId}/palettes`)}>View all</button>
          </div>
          <table>
            <thead><tr><th>Plant</th><th>Drawing type</th><th>Entries</th></tr></thead>
            <tbody>
              {paletteSummary.map((p) => (
                <tr key={`${p.plant}-${p.drawing_type}`}>
                  <td><span className="badge gray">{p.plant}</span></td>
                  <td style={{ color: '#374151' }}>{p.drawing_type}</td>
                  <td><span className="badge blue">{p.count}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
