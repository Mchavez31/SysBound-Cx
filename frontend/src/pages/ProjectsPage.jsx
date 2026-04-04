import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import useAuthStore from '../hooks/useAuthStore'
import useProjectStore from '../hooks/useProjectStore'
import api from '../lib/api'
import toast from 'react-hot-toast'

const FACILITY_TYPES = ['WCF', 'WOC', 'BT1', 'BT2', 'BT3', 'KPAD', 'Infrastructure', 'Mixed', 'Other']

function ProjectCard({ project, onSelect }) {
  const isActive = useProjectStore((s) => s.activeProjectId) === project.id
  return (
    <div
      onClick={() => onSelect(project)}
      style={{
        background: 'white', border: `2px solid ${isActive ? '#2563eb' : '#e5e7eb'}`,
        borderRadius: 12, padding: '18px 20px', cursor: 'pointer',
        transition: 'all 0.15s', position: 'relative',
      }}
      onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.borderColor = '#93c5fd' }}
      onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.borderColor = '#e5e7eb' }}
    >
      {isActive && (
        <span style={{ position: 'absolute', top: 12, right: 12, background: '#eff6ff', color: '#1d4ed8', fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Active
        </span>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
        <div style={{ width: 40, height: 40, background: isActive ? '#1a2744' : '#f3f4f6', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'background 0.15s' }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={isActive ? 'white' : '#6b7280'} strokeWidth="2" strokeLinecap="round">
            <path d="M2 9l10-7 10 7v11a2 2 0 01-2 2H4a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
          </svg>
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14, color: '#111827' }}>{project.name}</div>
          {project.client && <div style={{ fontSize: 12, color: '#6b7280', marginTop: 1 }}>{project.client}</div>}
        </div>
      </div>
      {project.description && (
        <p style={{ fontSize: 12, color: '#6b7280', lineHeight: 1.5, marginBottom: 10 }}>{project.description}</p>
      )}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {project.facility_type && (
          <span className="badge gray">{project.facility_type}</span>
        )}
        <span className="badge gray">{project.drawing_count || 0} drawings</span>
        <span className="badge gray" style={{ textTransform: 'capitalize' }}>{project.role}</span>
      </div>
    </div>
  )
}

function NewProjectModal({ onClose, onCreated }) {
  const [name, setName] = useState('')
  const [client, setClient] = useState('')
  const [description, setDescription] = useState('')
  const [facilityType, setFacilityType] = useState('')
  const qc = useQueryClient()

  const mutation = useMutation({
    mutationFn: (data) => api.post('/projects', data),
    onSuccess: (res) => {
      qc.invalidateQueries(['projects'])
      toast.success('Project created!')
      onCreated(res.data)
      onClose()
    },
    onError: (err) => toast.error(err.response?.data?.detail || 'Failed to create project'),
  })

  function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) { toast.error('Project name is required'); return }
    mutation.mutate({ name: name.trim(), client: client.trim() || null, description: description.trim() || null, facility_type: facilityType || null })
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={onClose}>
      <div style={{ background: 'white', borderRadius: 14, padding: 28, width: '100%', maxWidth: 460, boxShadow: '0 20px 60px rgba(0,0,0,0.2)' }} onClick={(e) => e.stopPropagation()}>
        <h2 style={{ fontSize: 17, fontWeight: 600, marginBottom: 20 }}>Create new project</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Project name *</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Willow Development Project" autoFocus required />
          </div>
          <div className="form-group">
            <label>Client / Company</label>
            <input value={client} onChange={(e) => setClient(e.target.value)} placeholder="e.g. ConocoPhillips" />
          </div>
          <div className="form-group">
            <label>Primary facility type</label>
            <select value={facilityType} onChange={(e) => setFacilityType(e.target.value)}>
              <option value="">Select facility type…</option>
              {FACILITY_TYPES.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 22 }}>
            <label>Description</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Brief description of the project scope…" rows={3} style={{ resize: 'vertical' }} />
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose}>Cancel</button>
            <button type="submit" className="primary" disabled={mutation.isPending}>
              {mutation.isPending ? 'Creating…' : 'Create project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function ProjectsPage() {
  const [showModal, setShowModal] = useState(false)
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)
  const navigate = useNavigate()

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get('/projects').then((r) => r.data),
  })

  function handleSelectProject(project) {
    setActiveProject(project)
    navigate(`/project/${project.id}`)
    toast.success(`Switched to ${project.name}`)
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f3f4f6' }}>
      {/* Top bar */}
      <div style={{ background: '#1a2744', color: 'white', padding: '0 24px', height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 32, height: 32, background: 'rgba(255,255,255,0.15)', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round">
              <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
          </div>
          <span style={{ fontSize: 15, fontWeight: 600 }}>Systemization Platform</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 13, opacity: 0.75 }}>{user?.name}</span>
          <button onClick={logout} style={{ background: 'rgba(255,255,255,0.1)', border: 'none', color: 'white', padding: '6px 12px', fontSize: 12 }}>Sign out</button>
        </div>
      </div>

      {/* Content */}
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '36px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 600, color: '#111827', marginBottom: 4 }}>Your projects</h1>
            <p style={{ color: '#6b7280', fontSize: 14 }}>Select a project to start working, or create a new one.</p>
          </div>
          <button className="primary" onClick={() => setShowModal(true)} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 18, lineHeight: 1 }}>+</span> New project
          </button>
        </div>

        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 48, color: '#6b7280' }}>Loading projects…</div>
        ) : projects.length === 0 ? (
          <div className="card empty-state">
            <div className="icon">🗂️</div>
            <h3>No projects yet</h3>
            <p>Create your first project to get started with systemization.</p>
            <button className="primary" onClick={() => setShowModal(true)} style={{ marginTop: 16 }}>Create first project</button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14 }}>
            {projects.map((p) => (
              <ProjectCard key={p.id} project={p} onSelect={handleSelectProject} />
            ))}
          </div>
        )}
      </div>

      {showModal && <NewProjectModal onClose={() => setShowModal(false)} onCreated={handleSelectProject} />}
    </div>
  )
}
