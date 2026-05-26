import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import useAuthStore from '../hooks/useAuthStore'
import useProjectStore from '../hooks/useProjectStore'
import api, { formatAxiosError } from '../lib/api'
import toast from 'react-hot-toast'

const FACILITY_TYPES = ['WCF', 'WOC', 'BT1', 'BT2', 'BT3', 'KPAD', 'Infrastructure', 'Mixed', 'Other']

function ProjectCard({ project, onSelect }) {
  const isActive = useProjectStore((s) => s.activeProjectId) === project.id
  return (
    <div
      onClick={() => onSelect(project)}
      className="card"
      style={{
        background: isActive ? 'rgba(20,184,166,0.12)' : 'var(--bg-card)', 
        border: `2px solid ${isActive ? 'var(--teal)' : 'var(--border-dim)'}`,
        cursor: 'pointer',
        transition: 'all 0.15s',
        position: 'relative',
      }}
      onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.borderColor = 'var(--border-mid)' }}
      onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.borderColor = 'var(--border-dim)' }}
    >
      {isActive && (
        <span style={{ position: 'absolute', top: 12, right: 12, background: 'rgba(20,184,166,0.2)', color: 'var(--teal-bright)', fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 4, textTransform: 'uppercase', letterSpacing: '0.05em', border: '1px solid var(--teal)' }}>
          Active
        </span>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
        <div style={{ width: 40, height: 40, background: isActive ? 'rgba(20,184,166,0.15)' : 'rgba(20,184,166,0.05)', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'background 0.15s', border: `1px solid ${isActive ? 'var(--teal)' : 'var(--border-dim)'}` }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={isActive ? 'var(--teal-bright)' : 'var(--teal)'} strokeWidth="2" strokeLinecap="round">
            <path d="M2 9l10-7 10 7v11a2 2 0 01-2 2H4a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
          </svg>
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)' }}>{project.name}</div>
          {project.client && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 1 }}>{project.client}</div>}
        </div>
      </div>
      {project.description && (
        <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 10 }}>{project.description}</p>
      )}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {project.facility_type && (
          <span className="badge amber">{project.facility_type}</span>
        )}
        <span className="badge teal">{project.drawing_count || 0} drawings</span>
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
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={onClose}>
      <div className="card" style={{ padding: 28, width: '100%', maxWidth: 460, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }} onClick={(e) => e.stopPropagation()}>
        <h2 style={{ fontSize: 17, fontWeight: 600, marginBottom: 20, color: 'var(--text-primary)' }}>Create new project</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label style={{ color: 'var(--teal-bright)' }}>Project name *</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Willow Development Project" autoFocus required />
          </div>
          <div className="form-group">
            <label style={{ color: 'var(--teal-bright)' }}>Client / Company</label>
            <input value={client} onChange={(e) => setClient(e.target.value)} placeholder="e.g. ConocoPhillips" />
          </div>
          <div className="form-group">
            <label style={{ color: 'var(--teal-bright)' }}>Primary facility type</label>
            <select value={facilityType} onChange={(e) => setFacilityType(e.target.value)}>
              <option value="">Select facility type…</option>
              {FACILITY_TYPES.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 22 }}>
            <label style={{ color: 'var(--teal-bright)' }}>Description</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Brief description of the project scope…" rows={3} style={{ resize: 'vertical' }} />
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose} className="secondary">Cancel</button>
            <button type="submit" className="accent" disabled={mutation.isPending}>
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

  const {
    data: projects = [],
    isLoading,
    isError,
    error: projectsError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get('/projects').then((r) => r.data),
    retry: 1,
  })

  function handleSelectProject(project) {
    setActiveProject(project)
    navigate(`/project/${project.id}`)
    toast.success(`Switched to ${project.name}`)
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-base)' }}>
      {/* Top bar */}
      <div style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', padding: '0 24px', height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-dim)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 32, height: 32, background: 'rgba(20,184,166,0.15)', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid var(--teal)' }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--teal-bright)" strokeWidth="2" strokeLinecap="round">
              <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
          </div>
          <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--teal-bright)' }}>Systemization Platform</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{user?.name}</span>
          <button onClick={logout} className="secondary" style={{ padding: '6px 12px', fontSize: 12 }}>Sign out</button>
        </div>
      </div>

      {/* Content */}
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '36px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Your projects</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>Select a project to start working, or create a new one.</p>
          </div>
          <button className="accent" onClick={() => setShowModal(true)} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 18, lineHeight: 1 }}>+</span> New project
          </button>
        </div>

        {isError ? (
          <div className="card" style={{ padding: 28, maxWidth: 520, margin: '0 auto' }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--amber)' }}>Could not reach the server</h2>
            <p style={{ fontSize: 14, color: 'var(--text-primary)', lineHeight: 1.6, marginBottom: 12 }}>
              {formatAxiosError(projectsError, 'Request failed')}
            </p>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: 16 }}>
              From the <strong>project root</strong>, run <code style={{ background: 'var(--bg-elevated)', padding: '2px 6px', borderRadius: 4, color: 'var(--teal-bright)' }}>npm run dev</code> (API on port <strong>8020</strong> + UI). Open{' '}
              <a href="http://127.0.0.1:8020/api/health" style={{ color: 'var(--teal-bright)' }} target="_blank" rel="noreferrer">
                http://127.0.0.1:8020/api/health
              </a>{' '}
              — if that never loads, a stuck process may be blocking ports; restart your PC or end old <code style={{ background: 'var(--bg-elevated)', padding: '2px 6px', borderRadius: 4, color: 'var(--teal-bright)' }}>python.exe</code> in Task Manager. Then retry.
            </p>
            <button type="button" className="accent" onClick={() => refetch()} disabled={isFetching}>
              {isFetching ? 'Retrying…' : 'Retry'}
            </button>
          </div>
        ) : isLoading ? (
          <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>Loading projects…</div>
        ) : projects.length === 0 ? (
          <div className="card empty-state">
            <div className="icon">🗂️</div>
            <h3>No projects yet</h3>
            <p>Create your first project to get started with systemization.</p>
            <button className="accent" onClick={() => setShowModal(true)} style={{ marginTop: 16 }}>Create first project</button>
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
