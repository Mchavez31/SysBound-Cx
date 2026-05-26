import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import useProjectStore from '../hooks/useProjectStore'
import api from '../lib/api'

function StatCard({ label, value, sub, accent, colorClass = 'teal' }) {
  return (
    <div className={`stat-card ${colorClass}`} style={{ transition: 'all 0.2s' }} onMouseEnter={(e) => e.currentTarget.style.borderColor = 'var(--border-bright)'} onMouseLeave={(e) => e.currentTarget.style.borderColor = 'var(--border-dim)'}>
      <div style={{ fontSize: 12, color: 'var(--teal-bright)', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 600, color: accent || 'var(--text-primary)', lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 5 }}>{sub}</div>}
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
      <div style={{ marginBottom: 28, borderBottom: '1px solid var(--border-dim)', paddingBottom: 16 }}>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>{activeProject?.name || 'Project Dashboard'}</h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
          {activeProject?.client && <span>{activeProject.client} · </span>}
          {activeProject?.facility_type && <span>{activeProject.facility_type} · </span>}
          {activeProject?.description}
        </p>
      </div>

      {/* Stats grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
        <StatCard colorClass="teal" label="Drawings" value="0" sub="Upload PDFs to get started" />
        <StatCard colorClass="blue" label="Tags tracked" value="0" sub="Across all drawings" />
        <StatCard colorClass="amber" label="Subsystems" value={subsystems.length} sub={subsystems.length > 0 ? 'In register' : 'Upload register'} accent={subsystems.length > 0 ? 'var(--teal-bright)' : undefined} />
        <StatCard colorClass="green" label="Color palettes" value={totalPaletteEntries} sub={paletteSummary.length > 0 ? `${plants.length} plant${plants.length !== 1 ? 's' : ''}` : 'Upload palette files'} accent={totalPaletteEntries > 0 ? 'var(--teal-bright)' : undefined} />
      </div>

      {/* Setup checklist (shown when project is new) */}
      {(paletteSummary.length === 0 || subsystems.length === 0) && (
        <div className="card" style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 16, color: 'var(--teal-bright)' }}>Project setup checklist</h2>
          {[
            { done: paletteSummary.length > 0, label: 'Upload color palette files', desc: 'Upload the Excel palette files for each plant (WCF, WOC, DrillSites, KPAD, Infrastructure)', action: () => navigate(`/project/${projectId}/palettes`), actionLabel: 'Go to Palettes' },
            { done: subsystems.length > 0, label: 'Upload subsystem register', desc: 'Upload the PIMS subsystem register so the app can validate assignments', action: () => navigate(`/project/${projectId}/subsystems`), actionLabel: 'Go to Subsystems' },
            { done: false, label: 'Upload drawings', desc: 'Upload systemized PDFs (current) and new engineering PDFs to compare', action: () => navigate(`/project/${projectId}/drawings`), actionLabel: 'Go to Drawings', disabled: paletteSummary.length === 0 || subsystems.length === 0 },
          ].map(({ done, label, desc, action, actionLabel, disabled }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '12px 0', borderBottom: '1px solid var(--border-dim)' }}>
              <div style={{ width: 22, height: 22, borderRadius: '50%', background: done ? 'var(--teal-dim)' : 'var(--bg-elevated)', border: `2px solid ${done ? 'var(--border-bright)' : 'var(--border-mid)'}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 2 }}>
                {done && <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--teal-bright)" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: done ? 'var(--text-dim)' : 'var(--teal-bright)', textDecoration: done ? 'line-through' : 'none' }}>{label}</div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>{desc}</div>
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
        <div className="card" style={{ overflow: 'hidden', padding: 0 }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-dim)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h2 style={{ fontSize: 14, fontWeight: 600, color: 'var(--teal-bright)' }}>Color palette coverage</h2>
            <button className="sm" onClick={() => navigate(`/project/${projectId}/palettes`)}>View all</button>
          </div>
          <table>
            <thead><tr><th>Plant</th><th>Drawing type</th><th>Entries</th></tr></thead>
            <tbody>
              {paletteSummary.map((p, idx) => (
                <tr key={`${p.plant}-${p.drawing_type}`} style={{ background: idx % 2 === 0 ? 'var(--bg-card)' : 'rgba(20,184,166,0.03)' }}>
                  <td><span className="badge teal">{p.plant}</span></td>
                  <td>{p.drawing_type}</td>
                  <td><span className="badge gray">{p.count}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
