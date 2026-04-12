import axios from 'axios'
import toast from 'react-hot-toast'

const _apiBase =
  typeof import.meta.env.VITE_API_URL === 'string' && import.meta.env.VITE_API_URL.trim()
    ? import.meta.env.VITE_API_URL.trim().replace(/\/$/, '')
    : '/api'

/** Vite base path with trailing slash (e.g. `/` or `/Systemize/`) for redirects */
function appBasePath() {
  const b = typeof import.meta.env.BASE_URL === 'string' ? import.meta.env.BASE_URL : '/'
  return b.endsWith('/') ? b : `${b}/`
}

const api = axios.create({
  baseURL: _apiBase,
  // Keep reasonable default so the UI does not spin for minutes when the API is down.
  // Long-running compare uses a per-request override in DrawingsPage.
  timeout: 45000,
})

function _detailFromParsedBody(data) {
  const d = data?.detail
  if (typeof d === 'string') return d.length > 500 ? `${d.slice(0, 500)}…` : d
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join('; ')
  return null
}

const TIMEOUT_HINT =
  'Cannot reach the API. From the project root run npm run dev (API on port 8020 + Vite). Or start the API: python -m uvicorn main:app --reload --host 127.0.0.1 --port 8020 in backend, then npm run dev in frontend. If /api/health never loads, check the port in package.json dev:api and frontend/.env.development VITE_DEV_PROXY_API (they must match). Remove VITE_API_URL from frontend/.env unless you mean to bypass the proxy.'

/** Short copy for toasts; same id replaces duplicates when many requests fail at once. */
const TOAST_UNREACHABLE =
  'Cannot reach the API. From the project root run npm run dev (backend on 8020, Vite on 5173). Match package.json dev:api with frontend/.env.development VITE_DEV_PROXY_API. Test http://127.0.0.1:8020/api/health in a browser.'

export function isUnreachableAxiosError(err) {
  if (!err || err.response) return false
  if (err.code === 'ECONNABORTED') return true
  if (String(err.message || '').toLowerCase().includes('timeout')) return true
  const m = String(err.message || '').toLowerCase()
  if (m.includes('network') || m.includes('econnrefused')) return true
  return false
}

/** Use instead of toast.error(formatAxiosError(...)) so connection failures show once, not stacked. */
export function toastAxiosError(err, fallback = 'Request failed') {
  if (isUnreachableAxiosError(err)) {
    toast.error(TOAST_UNREACHABLE, { id: 'api-unreachable', duration: 11000 })
    return
  }
  toast.error(formatAxiosError(err, fallback), { duration: 6000 })
}

/** Human-readable API/network error for toasts */
export function formatAxiosError(err, fallback = 'Request failed') {
  if (err.code === 'ECONNABORTED' || String(err.message || '').toLowerCase().includes('timeout')) {
    return TIMEOUT_HINT
  }
  if (!err.response) {
    const m = String(err.message || '')
    if (m.toLowerCase().includes('network') || m.toLowerCase().includes('econnrefused')) {
      return `${TIMEOUT_HINT} (${m || 'network error'})`
    }
    return m || 'Network error — server closed the connection or became unreachable.'
  }
  const data = err.response.data
  if (data instanceof Blob) {
    return fallback
  }
  const parsed = _detailFromParsedBody(data)
  if (parsed) return parsed
  return fallback
}

/**
 * Same as formatAxiosError but reads FastAPI JSON from Blob bodies (required when
 * request used responseType: 'blob' and the server returned 4xx/5xx).
 */
export async function formatAxiosErrorAsync(err, fallback = 'Request failed') {
  if (err.code === 'ECONNABORTED' || String(err.message || '').toLowerCase().includes('timeout')) {
    return TIMEOUT_HINT
  }
  if (!err.response) {
    const m = String(err.message || '')
    if (m.toLowerCase().includes('network') || m.toLowerCase().includes('econnrefused')) {
      return `${TIMEOUT_HINT} (${m || 'network error'})`
    }
    return m || 'Network error — server closed the connection or became unreachable.'
  }
  const data = err.response.data
  if (data instanceof Blob) {
    try {
      const text = await data.text()
      if (text) {
        try {
          const j = JSON.parse(text)
          const d = _detailFromParsedBody(j)
          if (d) return d
        } catch {
          const t = text.length > 500 ? `${text.slice(0, 500)}…` : text
          if (t.trim()) return t
        }
      }
    } catch {
      /* ignore */
    }
    if (err.response.status === 404) return 'Not found (404).'
    return fallback
  }
  return formatAxiosError(err, fallback)
}

api.interceptors.request.use((config) => {
  try {
    const raw = localStorage.getItem('auth-storage')
    const token = raw ? JSON.parse(raw)?.state?.token : null
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  } catch {
    /* ignore */
  }
  if (config.data instanceof FormData) {
    // Never set multipart/form-data manually — it omits the boundary and breaks FastAPI file uploads.
    const h = config.headers
    if (h && typeof h.delete === 'function') {
      h.delete('Content-Type')
      h.delete('content-type')
    } else if (h) {
      delete h['Content-Type']
      delete h['content-type']
    }
  } else if (config.data instanceof URLSearchParams) {
    // Login uses OAuth2 form body; must not be sent as JSON (empty {} breaks FastAPI)
    config.headers['Content-Type'] = 'application/x-www-form-urlencoded'
  } else if (config.data && typeof config.data === 'object') {
    config.headers['Content-Type'] = 'application/json'
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('auth-storage')
      window.location.href = `${appBasePath()}login`
    }
    return Promise.reject(err)
  }
)

export default api
