import { useEffect, useState } from 'react'
import api from '../lib/api'

const isLiveDemoHost =
  typeof window !== 'undefined' &&
  (window.location.hostname.endsWith('github.io') ||
    window.location.hostname.endsWith('vercel.app'))

export default function ApiStatusBanner() {
  const [status, setStatus] = useState('checking') // checking | ok | down

  useEffect(() => {
    let cancelled = false
    api
      .get('/health', { timeout: 8000 })
      .then(() => {
        if (!cancelled) setStatus('ok')
      })
      .catch(() => {
        if (!cancelled) setStatus('down')
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (status !== 'down') return null

  return (
    <div
      style={{
        marginBottom: 16,
        padding: '12px 14px',
        borderRadius: 8,
        border: '1px solid rgba(251, 191, 36, 0.45)',
        background: 'rgba(251, 191, 36, 0.08)',
        color: 'var(--text-primary)',
        fontSize: 13,
        lineHeight: 1.55,
      }}
    >
      <strong style={{ color: '#fbbf24' }}>Backend API not connected.</strong>{' '}
      {isLiveDemoHost ? (
        <>
          This live page is the UI only. Login and registration need the API deployed on Render
          (see <code style={{ color: 'var(--teal-bright)' }}>DEPLOYMENT.md</code> in the repo).
          For full access now, run locally:{' '}
          <code style={{ color: 'var(--teal-bright)' }}>npm run dev</code> then open{' '}
          <a href="http://localhost:5173" style={{ color: 'var(--teal-bright)' }}>
            localhost:5173
          </a>
          .
        </>
      ) : (
        <>
          Start the API from the project root with{' '}
          <code style={{ color: 'var(--teal-bright)' }}>npm run dev</code>, then test{' '}
          <a href="http://127.0.0.1:8020/api/health" style={{ color: 'var(--teal-bright)' }}>
            127.0.0.1:8020/api/health
          </a>
          .
        </>
      )}
    </div>
  )
}
