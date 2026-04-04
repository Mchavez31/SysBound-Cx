import { useParams } from 'react-router-dom'

export default function DrawingsPage() {
  const { projectId } = useParams()
  return (
    <div style={{ padding: '28px 28px 48px' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>Drawings</h1>
        <p style={{ color: '#6b7280', fontSize: 14 }}>Upload systemized and non-systemized PDFs to compare and process.</p>
      </div>
      <div className="card empty-state">
        <div className="icon">📐</div>
        <h3>Drawing upload coming in Phase 2</h3>
        <p>This is where you'll upload PDFs, run comparisons, apply systemization, and export layered drawings.<br /><br />
        Make sure your color palettes and subsystem register are loaded first.</p>
      </div>
    </div>
  )
}
