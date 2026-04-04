import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import useAuthStore from '../hooks/useAuthStore'
import toast from 'react-hot-toast'

export default function RegisterPage() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const register = useAuthStore((s) => s.register)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    if (password.length < 8) { toast.error('Password must be at least 8 characters'); return }
    setLoading(true)
    try {
      await register(name, email, password)
      navigate('/projects')
      toast.success('Account created!')
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f3f4f6' }}>
      <div style={{ width: '100%', maxWidth: 400, padding: '0 16px' }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ width: 48, height: 48, background: '#1a2744', borderRadius: 12, margin: '0 auto 14px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round">
              <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 600, color: '#111827', marginBottom: 4 }}>Create your account</h1>
          <p style={{ color: '#6b7280', fontSize: 14 }}>Get started with Systemization Platform</p>
        </div>
        <div className="card">
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label>Full name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" required autoFocus />
            </div>
            <div className="form-group">
              <label>Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" required />
            </div>
            <div className="form-group" style={{ marginBottom: 20 }}>
              <label>Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Min 8 characters" required />
            </div>
            <button type="submit" className="primary" style={{ width: '100%' }} disabled={loading}>
              {loading ? 'Creating account…' : 'Create account'}
            </button>
          </form>
        </div>
        <p style={{ textAlign: 'center', marginTop: 16, fontSize: 13, color: '#6b7280' }}>
          Already have an account? <Link to="/login" style={{ color: '#2563eb', fontWeight: 500 }}>Sign in</Link>
        </p>
      </div>
    </div>
  )
}
