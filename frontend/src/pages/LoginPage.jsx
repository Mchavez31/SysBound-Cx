import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import useAuthStore from '../hooks/useAuthStore'
import { isUnreachableAxiosError, toastAxiosError } from '../lib/api'
import toast from 'react-hot-toast'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const login = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    try {
      await login(email, password)
      navigate('/projects')
    } catch (err) {
      if (isUnreachableAxiosError(err)) {
        toastAxiosError(err, 'Login failed')
      } else {
        const d = err.response?.data?.detail
        const msg =
          err.response && d != null
            ? Array.isArray(d)
              ? d.map((x) => x.msg || String(x)).join('; ')
              : typeof d === 'string'
                ? d
                : 'Login failed'
            : 'Login failed'
        toast.error(msg, { duration: 8000 })
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-base)' }}>
      <div style={{ width: '100%', maxWidth: 400, padding: '0 16px' }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ width: 48, height: 48, background: 'var(--teal-dim)', borderRadius: 12, margin: '0 auto 14px', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '2px solid var(--border-bright)' }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--teal-bright)" strokeWidth="2" strokeLinecap="round">
              <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Systemization Platform</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>Sign in to your account</p>
        </div>
        <div className="card">
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label>Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" required autoFocus />
            </div>
            <div className="form-group" style={{ marginBottom: 20 }}>
              <label>Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required />
            </div>
            <button type="submit" className="accent" style={{ width: '100%' }} disabled={loading}>
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>
        <p style={{ textAlign: 'center', marginTop: 16, fontSize: 13, color: 'var(--text-secondary)' }}>
          Don't have an account? <Link to="/register" style={{ color: 'var(--teal-bright)', fontWeight: 500 }}>Create one</Link>
        </p>
        {import.meta.env.DEV ? (
          <p style={{ textAlign: 'center', marginTop: 14, fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.5 }}>
            Local dev: from the <strong>project root</strong> run <code style={{ background: 'var(--bg-elevated)', padding: '1px 5px', borderRadius: 4, color: 'var(--teal-bright)' }}>npm install</code> once, then{' '}
            <code style={{ background: 'var(--bg-elevated)', padding: '1px 5px', borderRadius: 4, color: 'var(--teal-bright)' }}>npm run dev</code> (API on port <strong>8020</strong> + UI). Or run{' '}
            <code style={{ background: 'var(--bg-elevated)', padding: '1px 5px', borderRadius: 4, color: 'var(--teal-bright)' }}>backend/run_dev.bat</code> and <code style={{ background: 'var(--bg-elevated)', padding: '1px 5px', borderRadius: 4, color: 'var(--teal-bright)' }}>npm run dev</code> in{' '}
            <code style={{ background: 'var(--bg-elevated)', padding: '1px 5px', borderRadius: 4, color: 'var(--teal-bright)' }}>frontend</code>. Test API:{' '}
            <a href="http://127.0.0.1:8020/api/health" style={{ color: 'var(--teal-bright)' }} target="_blank" rel="noreferrer">
              127.0.0.1:8020/api/health
            </a>
          </p>
        ) : null}
      </div>
    </div>
  )
}
