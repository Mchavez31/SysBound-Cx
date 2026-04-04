import { Outlet, NavLink, useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import useAuthStore from '../hooks/useAuthStore'
import useProjectStore from '../hooks/useProjectStore'
import api from '../lib/api'

const NAV_ITEMS = [
  { to: '', label: 'Dashboard', end: true, icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg> },
  { to: 'drawings', label: 'Drawings', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> },
  { to: 'palettes', label: 'Color Palettes', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 011.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/></svg> },
  { to: 'subsystems', label: 'Subsystems', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg> },
]

export default function ProjectLayout() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const logout = useAuthStore((s) => s.logout)
  const user = useAuthStore((s) => s.user)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)
  const activeProject = useProjectStore((s) => s.activeProject)

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get(`/projects/${projectId}`).then((r) => { setActiveProject(r.data); return r.data }),
    initialData: activeProject?.id === projectId ? activeProject : undefined,
  })

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {/* Sidebar */}
      <div style={{ width: 228, background: '#1a2744', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        {/* App logo */}
        <div style={{ padding: '16px 16px 12px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <div style={{ width: 28, height: 28, background: 'rgba(255,255,255,0.12)', borderRadius: 7, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round">
                <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
                <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
              </svg>
            </div>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'white' }}>Systemization</span>
          </div>
          {/* Project switcher button */}
          <button
            onClick={() => navigate('/projects')}
            style={{ width: '100%', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 8, padding: '8px 10px', color: 'white', display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', transition: 'background 0.15s', textAlign: 'left' }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.14)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.08)'}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'white', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{project?.name || 'Loading…'}</div>
              {project?.client && <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', marginTop: 1 }}>{project.client}</div>}
            </div>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.5)" strokeWidth="2.5" strokeLinecap="round">
              <polyline points="15 18 9 12 15 6"/>
            </svg>
          </button>
        </div>

        {/* Nav links */}
        <nav style={{ flex: 1, padding: '10px 8px' }}>
          {NAV_ITEMS.map(({ to, label, end, icon }) => (
            <NavLink
              key={label}
              to={to}
              end={end}
              style={({ isActive }) => ({
                display: 'flex', alignItems: 'center', gap: 9,
                padding: '8px 10px', borderRadius: 7, marginBottom: 2,
                color: isActive ? 'white' : 'rgba(255,255,255,0.55)',
                background: isActive ? 'rgba(255,255,255,0.12)' : 'transparent',
                fontWeight: isActive ? 500 : 400, fontSize: 13,
                textDecoration: 'none', transition: 'all 0.12s',
              })}
              onMouseEnter={(e) => { if (!e.currentTarget.classList.contains('active')) e.currentTarget.style.background = 'rgba(255,255,255,0.07)' }}
              onMouseLeave={(e) => { if (!e.currentTarget.classList.contains('active')) e.currentTarget.style.background = 'transparent' }}
            >
              {icon} {label}
            </NavLink>
          ))}
        </nav>

        {/* User footer */}
        <div style={{ padding: '12px 16px', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 28, height: 28, background: '#2563eb', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 600, color: 'white', flexShrink: 0 }}>
              {user?.name?.charAt(0).toUpperCase()}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: 'white', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{user?.name}</div>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{user?.email}</div>
            </div>
            <button onClick={logout} title="Sign out" style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', padding: 4, display: 'flex' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div style={{ flex: 1, overflow: 'auto', background: '#f3f4f6' }}>
        <Outlet />
      </div>
    </div>
  )
}
