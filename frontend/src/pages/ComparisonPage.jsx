import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api, { formatAxiosError, formatAxiosErrorAsync, toastAxiosError } from '../lib/api'
import toast from 'react-hot-toast'

const CHANGE_TYPE_OPTIONS = [
  { value: 'new', label: 'New' },
  { value: 'removed', label: 'Removed' },
  { value: 'subsystem_changed', label: 'Subsystem changed' },
  { value: 'color_changed', label: 'Color changed' },
]

const ACTION_LABELS = {
  assign_subsystem: 'Assign Subsystem',
  review_removal: 'Review Removal',
  review_change: 'Review Change',
  x_tag: 'X-Tag',
  future: 'Future',
  none: 'No Action',
}

const TIP_SUB =
  'Subsystem bubble (NN-MM) chosen by matching bubble color to the color sampled at the tag (distance breaks ties). A dash means no bubble was linked for this tag in this PDF.'
const TIP_COLOR =
  'Fill color taken from the linked subsystem bubble. A dash means no bubble was linked on this side, so no color was recorded.'

/** Show em dash with tooltip when value is missing (extraction gap vs. visual gap). */
function MissingHint({ value, tip, as = '—' }) {
  if (value != null && value !== '') return value
  return (
    <span title={tip} style={{ cursor: 'help', borderBottom: '1px dotted var(--border-mid)', color: 'var(--text-dim)' }}>
      {as}
    </span>
  )
}

function rowStyle(row, idx) {
  const ct = row.change_type
  const baseStyle = idx % 2 === 0 ? { background: 'var(--bg-card)' } : { background: 'rgba(20,184,166,0.03)' }
  
  if (ct === 'new') return { ...baseStyle, borderLeft: '3px solid var(--amber)' }
  if (ct === 'removed') return { ...baseStyle, borderLeft: '3px solid var(--red)' }
  if (ct === 'subsystem_changed' || ct === 'color_changed') return { ...baseStyle, borderLeft: '3px solid var(--blue)' }
  if (row.is_x_tag) return { ...baseStyle, borderLeft: '3px solid var(--teal)' }
  if (row.action_needed === 'future') return { ...baseStyle, opacity: 0.7 }
  return baseStyle
}

function ActionBadge({ action }) {
  const map = {
    assign_subsystem: 'amber',
    review_removal: 'red',
    review_change: 'blue',
    x_tag: 'purple',
    future: 'gray',
    none: 'green',
  }
  const cls = map[action] || 'gray'
  return <span className={`badge ${cls}`}>{ACTION_LABELS[action] || action}</span>
}

/** Coerce JSON page fields (number/string) to a positive integer for the API. */
function parsePageNumber(p) {
  if (p == null || p === '') return null
  const s = String(p).trim()
  if (!s) return null
  const n = Number(s)
  if (!Number.isFinite(n) || n < 1) return null
  return Math.max(1, Math.floor(n))
}

async function blobIsPng(blob) {
  if (!blob || blob.size < 8) return false
  const ab = await blob.slice(0, 8).arrayBuffer()
  const u = new Uint8Array(ab)
  return u[0] === 0x89 && u[1] === 0x50 && u[2] === 0x4e && u[3] === 0x47
}

async function textFromBlob(blob) {
  try {
    return await blob.text()
  } catch {
    return ''
  }
}

function changeTypeFilterLabel(selected) {
  const list = Array.isArray(selected) ? selected : []
  if (!list.length) return 'All types'
  const map = Object.fromEntries(CHANGE_TYPE_OPTIONS.map((o) => [o.value, o.label]))
  return list.map((v) => map[v] || v).join(', ')
}

/** Button + dropdown with checkboxes; multi-select change types. */
function ChangeTypeFilterDropdown({ value, onToggle, onClear }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)

  useEffect(() => {
    function onDocClick(e) {
      if (!wrapRef.current || wrapRef.current.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  useEffect(() => {
    if (!open) return undefined
    function onKey(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div ref={wrapRef} style={{ position: 'relative', minWidth: 220 }}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        style={{
          width: '100%',
          textAlign: 'left',
          padding: '8px 10px',
          fontSize: 14,
          border: '1px solid var(--border-mid)',
          borderRadius: 6,
          background: 'var(--bg-elevated)',
          color: 'var(--text-primary)',
          cursor: 'pointer',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          minHeight: 40,
          boxSizing: 'border-box',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{changeTypeFilterLabel(value)}</span>
        <span style={{ color: 'var(--text-dim)', fontSize: 12, flexShrink: 0 }}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div
          role="listbox"
          aria-multiselectable="true"
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: 'calc(100% + 4px)',
            zIndex: 200,
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-mid)',
            borderRadius: 8,
            boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
            padding: '6px 0',
            maxHeight: 280,
            overflowY: 'auto',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {CHANGE_TYPE_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              role="option"
              aria-selected={Array.isArray(value) && value.includes(opt.value)}
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                gap: 10,
                padding: '8px 14px',
                fontSize: 13,
                cursor: 'pointer',
                margin: 0,
                textTransform: 'none',
                fontWeight: 400,
                color: 'var(--text-primary)',
              }}
            >
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 18,
                  flexShrink: 0,
                }}
              >
                <input
                  type="checkbox"
                  checked={Array.isArray(value) && value.includes(opt.value)}
                  onChange={() => onToggle(opt.value)}
                  style={{ margin: 0, width: 16, height: 16, cursor: 'pointer' }}
                />
              </span>
              <span style={{ flex: 1, minWidth: 0, lineHeight: 1.3 }}>{opt.label}</span>
            </label>
          ))}
          <div style={{ borderTop: '1px solid var(--border-dim)', marginTop: 4, padding: '8px 14px 6px' }}>
            <button
              type="button"
              className="sm secondary"
              style={{ width: '100%' }}
              onClick={() => {
                onClear()
                setOpen(false)
              }}
            >
              Clear (show all)
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function ZoomableSnippetPanel({
  src,
  label,
  emptyLabel,
  viewMode = 'focus',
  onViewModeChange,
  hasFullPage = false,
}) {
  const viewportRef = useRef(null)
  const [zoom, setZoom] = useState(1)
  const [panning, setPanning] = useState(false)
  const draggingRef = useRef(false)
  const lastPtrRef = useRef({ x: 0, y: 0 })

  useEffect(() => {
    setZoom(1)
    const el = viewportRef.current
    if (el) el.scrollTo({ left: 0, top: 0 })
  }, [src])

  const clampZoom = (z) => Math.min(8, Math.max(0.25, z))

  const onWheel = (e) => {
    if (!src) return
    if (!e.ctrlKey && !e.metaKey) return
    e.preventDefault()
    const factor = e.deltaY > 0 ? 0.92 : 1.08
    setZoom((z) => clampZoom(z * factor))
  }

  const onPointerDown = (e) => {
    if (!src || e.button !== 0) return
    draggingRef.current = true
    setPanning(true)
    lastPtrRef.current = { x: e.clientX, y: e.clientY }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e) => {
    if (!draggingRef.current || !viewportRef.current) return
    const el = viewportRef.current
    const dx = e.clientX - lastPtrRef.current.x
    const dy = e.clientY - lastPtrRef.current.y
    lastPtrRef.current = { x: e.clientX, y: e.clientY }
    el.scrollLeft -= dx
    el.scrollTop -= dy
  }

  const endDrag = (e) => {
    if (!draggingRef.current) return
    draggingRef.current = false
    setPanning(false)
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* noop */
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        flex: 1,
        height: '100%',
        background: 'var(--bg-base)',
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          padding: '6px 10px',
          background: 'var(--bg-surface)',
          color: 'var(--text-primary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        <span style={{ flex: 1, minWidth: 0 }}>{label}</span>
        {hasFullPage && typeof onViewModeChange === 'function' ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, marginRight: 4 }}>
            <button
              type="button"
              className="sm"
              title="Zoomed crop around the tag"
              onClick={() => onViewModeChange('focus')}
              style={{
                background: viewMode === 'focus' ? 'var(--teal)' : 'transparent',
                color: viewMode === 'focus' ? 'var(--bg-base)' : 'var(--text-secondary)',
                border: '1px solid var(--border-mid)',
              }}
            >
              Tag region
            </button>
            <button
              type="button"
              className="sm"
              title="Whole PDF page (pan to see everything)"
              onClick={() => onViewModeChange('full')}
              style={{
                background: viewMode === 'full' ? 'var(--teal)' : 'transparent',
                color: viewMode === 'full' ? 'var(--bg-base)' : 'var(--text-secondary)',
                border: '1px solid var(--border-mid)',
              }}
            >
              Full page
            </button>
          </div>
        ) : null}
        {src ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            <button
              type="button"
              className="sm"
              title="Zoom out"
              onClick={() => setZoom((z) => clampZoom(z / 1.15))}
            >
              −
            </button>
            <span style={{ fontSize: 10, color: 'var(--text-secondary)', minWidth: 44, textAlign: 'center' }}>{Math.round(zoom * 100)}%</span>
            <button
              type="button"
              className="sm"
              title="Zoom in"
              onClick={() => setZoom((z) => clampZoom(z * 1.15))}
            >
              +
            </button>
            <button
              type="button"
              className="sm"
              title="Reset zoom and pan"
              onClick={() => {
                setZoom(1)
                viewportRef.current?.scrollTo({ left: 0, top: 0 })
              }}
            >
              Reset
            </button>
          </div>
        ) : null}
      </div>
      <div
        ref={viewportRef}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        style={{
          flex: 1,
          minHeight: 200,
          overflow: 'auto',
          padding: 8,
          cursor: src ? (panning ? 'grabbing' : 'grab') : 'default',
          touchAction: 'none',
        }}
      >
        {src ? (
          <img
            src={src}
            alt=""
            draggable={false}
            style={{
              width: `${100 * zoom}%`,
              height: 'auto',
              display: 'block',
              margin: '0 auto',
              maxWidth: 'none',
              userSelect: 'none',
              pointerEvents: 'none',
            }}
          />
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 180, color: 'var(--text-dim)', fontSize: 13 }}>
            {emptyLabel}
          </div>
        )}
      </div>
    </div>
  )
}

function snippetParamsForSide(row, side, page) {
  if (!page) return null
  const p = { page, margin: 175 }
  const tx = side === 'a' ? row?.tag_x_a : row?.tag_x_b
  const ty = side === 'a' ? row?.tag_y_a : row?.tag_y_b
  if (tx != null && ty != null) {
    p.x = tx
    p.y = ty
  }
  return p
}

/** Full-page downscaled render (no x/y) so users can pan the whole sheet. */
function snippetParamsFullPage(page) {
  if (!page) return null
  return { page, margin: 170 }
}

function revokeSnippetObjectUrls(ref) {
  const o = ref.current
  ;['af', 'afu', 'bf', 'bfu'].forEach((k) => {
    if (o[k]) {
      URL.revokeObjectURL(o[k])
      o[k] = null
    }
  })
}

function summarizeComparisonChange(row) {
  if (!row) return ''
  const ct = row.change_type
  if (ct === 'subsystem_changed') {
    const a = row.subsystem_a != null && row.subsystem_a !== '' ? row.subsystem_a : '—'
    const b = row.subsystem_b != null && row.subsystem_b !== '' ? row.subsystem_b : '—'
    return `Change found: subsystem label ${a} → ${b}`
  }
  if (ct === 'color_changed') {
    const a = row.color_a || '—'
    const b = row.color_b || '—'
    return `Change found: bubble fill color ${a} → ${b}`
  }
  if (ct === 'new') return 'Change found: tag appears only on drawing B (current).'
  if (ct === 'removed') return 'Change found: tag appears only on drawing A (prior).'
  return ct ? `Change type: ${ct}` : ''
}

function SideBySidePdfModal({ open, onClose, projectId, row, drawingAId, drawingBId, docA, docB }) {
  const idA = (drawingAId && String(drawingAId).trim()) || row?.drawing_id_a
  const idB = (drawingBId && String(drawingBId).trim()) || row?.drawing_id_b
  const pageA = parsePageNumber(row?.page_a)
  const pageB = parsePageNumber(row?.page_b)
  const [snipUrls, setSnipUrls] = useState({
    a: { focus: null, full: null },
    b: { focus: null, full: null },
  })
  const [viewMode, setViewMode] = useState({ a: 'focus', b: 'focus' })
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const snippetObjectUrlsRef = useRef({ af: null, afu: null, bf: null, bfu: null })

  useEffect(() => {
    if (!open) {
      revokeSnippetObjectUrls(snippetObjectUrlsRef)
      setSnipUrls({ a: { focus: null, full: null }, b: { focus: null, full: null } })
      setViewMode({ a: 'focus', b: 'focus' })
      setErr(null)
      setLoading(false)
      return undefined
    }
    if (!projectId || !idA || !idB) {
      revokeSnippetObjectUrls(snippetObjectUrlsRef)
      setSnipUrls({ a: { focus: null, full: null }, b: { focus: null, full: null } })
      setErr('Missing drawing references. Reload the page, or open this comparison from Drawings → Comparison history.')
      setLoading(false)
      return undefined
    }
    let cancelled = false
    setLoading(true)
    setErr(null)
    revokeSnippetObjectUrls(snippetObjectUrlsRef)
    setSnipUrls({ a: { focus: null, full: null }, b: { focus: null, full: null } })
    setViewMode({ a: 'focus', b: 'focus' })
    ;(async () => {
      try {
        const tasks = []
        if (pageA != null) {
          const pf = snippetParamsForSide(row, 'a', pageA)
          const pfu = snippetParamsFullPage(pageA)
          if (pf) {
            tasks.push(
              api
                .get(`/drawings/${projectId}/drawing/${idA}/snippet`, { params: pf, responseType: 'blob' })
                .then((r) => ({ ok: true, key: 'af', blob: r.data }))
                .catch(async (err) => ({ ok: false, key: 'af', err })),
            )
          }
          if (pfu) {
            tasks.push(
              api
                .get(`/drawings/${projectId}/drawing/${idA}/snippet`, { params: pfu, responseType: 'blob' })
                .then((r) => ({ ok: true, key: 'afu', blob: r.data }))
                .catch(async (err) => ({ ok: false, key: 'afu', err })),
            )
          }
        }
        if (pageB != null) {
          const pf = snippetParamsForSide(row, 'b', pageB)
          const pfu = snippetParamsFullPage(pageB)
          if (pf) {
            tasks.push(
              api
                .get(`/drawings/${projectId}/drawing/${idB}/snippet`, { params: pf, responseType: 'blob' })
                .then((r) => ({ ok: true, key: 'bf', blob: r.data }))
                .catch(async (err) => ({ ok: false, key: 'bf', err })),
            )
          }
          if (pfu) {
            tasks.push(
              api
                .get(`/drawings/${projectId}/drawing/${idB}/snippet`, { params: pfu, responseType: 'blob' })
                .then((r) => ({ ok: true, key: 'bfu', blob: r.data }))
                .catch(async (err) => ({ ok: false, key: 'bfu', err })),
            )
          }
        }
        if (tasks.length === 0) {
          if (!cancelled) {
            setErr(
              'No valid page numbers on this row (Page A / Page B). Re-run the comparison after uploading PDFs, or check that this row has page_a / page_b set.',
            )
          }
          return
        }
        const results = await Promise.all(tasks)
        if (cancelled) return
        const next = {
          a: { focus: null, full: null },
          b: { focus: null, full: null },
        }
        const parts = []
        for (const r of results) {
          if (!r.ok) {
            const msg = await formatAxiosErrorAsync(r.err, 'snippet failed')
            const sideLabel = r.key.startsWith('a') ? 'Prior (A)' : 'Current (B)'
            const kind = r.key.endsWith('u') ? 'full page' : 'tag region'
            parts.push(`${sideLabel} (${kind}): ${msg}`)
            continue
          }
          const { key, blob } = r
          if (!(blob instanceof Blob) || !(await blobIsPng(blob))) {
            let detail = 'response was not a PNG (check API / login / file on disk)'
            if (blob instanceof Blob && blob.size < 8000) {
              const t = await textFromBlob(blob)
              try {
                const j = JSON.parse(t)
                if (j.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
              } catch {
                if (t.trim()) detail = t.length > 400 ? `${t.slice(0, 400)}…` : t
              }
            }
            const sideLabel = key.startsWith('a') ? 'Prior (A)' : 'Current (B)'
            const kind = key.endsWith('u') ? 'full page' : 'tag region'
            parts.push(`${sideLabel} (${kind}): ${detail}`)
            continue
          }
          const u = URL.createObjectURL(blob)
          if (key === 'af') next.a.focus = u
          if (key === 'afu') next.a.full = u
          if (key === 'bf') next.b.focus = u
          if (key === 'bfu') next.b.full = u
        }
        const hasAny = !!(next.a.focus || next.a.full || next.b.focus || next.b.full)
        if (parts.length && !hasAny) {
          setErr(parts.join(' · '))
          return
        }
        if (parts.length) setErr(parts.join(' · '))
        if (!cancelled) {
          revokeSnippetObjectUrls(snippetObjectUrlsRef)
          snippetObjectUrlsRef.current = {
            af: next.a.focus,
            afu: next.a.full,
            bf: next.b.focus,
            bfu: next.b.full,
          }
          setSnipUrls(next)
        }
      } catch (e) {
        if (!cancelled) setErr(await formatAxiosErrorAsync(e, 'Could not load snippets'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [
    open,
    projectId,
    idA,
    idB,
    pageA,
    pageB,
    row?.tag_x_a,
    row?.tag_y_a,
    row?.tag_x_b,
    row?.tag_y_b,
    row?.tag_number,
    drawingAId,
    drawingBId,
  ])

  if (!open) return null

  const hasAnySnippet = !!(snipUrls.a.focus || snipUrls.a.full || snipUrls.b.focus || snipUrls.b.full)
  const labelA = pageA != null ? `Prior / A · p.${pageA}` : 'Prior / A — tag not on this drawing'
  const labelB = pageB != null ? `Current / B · p.${pageB}` : 'Current / B — tag not on this drawing'

  const srcFor = (side) => {
    const s = snipUrls[side]
    const mode = viewMode[side]
    if (mode === 'full' && s.full) return s.full
    return s.focus
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{
          maxWidth: 'min(1500px, 100%)',
          width: '100%',
          height: 'min(94vh, 900px)',
          minHeight: 320,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          padding: 0,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            padding: '12px 16px',
            borderBottom: '1px solid var(--border-dim)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            flexWrap: 'wrap',
            gap: 8,
          }}
        >
          <div>
            <div style={{ fontWeight: 600, fontSize: 15, color: 'var(--text-primary)' }}>Tag: {row?.tag_number}</div>
            {summarizeComparisonChange(row) ? (
              <div
                style={{
                  fontSize: 13,
                  color: 'var(--teal-bright)',
                  fontWeight: 600,
                  marginTop: 8,
                  maxWidth: 720,
                  lineHeight: 1.4,
                }}
              >
                {summarizeComparisonChange(row)}
              </div>
            ) : null}
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4, maxWidth: 720 }}>
              Use <strong>Tag region</strong> for the zoomed crop (red box when coordinates exist). Use <strong>Full page</strong> to pan the whole sheet, then zoom and drag to inspect anywhere.
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6 }}>
              {docA && <span style={{ marginRight: 12 }}>A: {docA}</span>}
              {docB && <span>B: {docB}</span>}
            </div>
          </div>
          <button type="button" className="sm secondary" onClick={onClose}>
            Close
          </button>
        </div>
        {loading && <p style={{ padding: 24, color: 'var(--text-secondary)' }}>Loading views…</p>}
        {err && <p style={{ padding: '8px 16px', color: 'var(--red)', fontSize: 13, margin: 0 }}>{err}</p>}
        {!loading && hasAnySnippet && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 1,
              flex: 1,
              minHeight: 420,
              background: 'var(--border-dim)',
            }}
          >
            <ZoomableSnippetPanel
              src={srcFor('a')}
              label={labelA}
              emptyLabel="No image"
              viewMode={viewMode.a}
              onViewModeChange={(m) => setViewMode((vm) => ({ ...vm, a: m }))}
              hasFullPage={!!snipUrls.a.full}
            />
            <ZoomableSnippetPanel
              src={srcFor('b')}
              label={labelB}
              emptyLabel="No image"
              viewMode={viewMode.b}
              onViewModeChange={(m) => setViewMode((vm) => ({ ...vm, b: m }))}
              hasFullPage={!!snipUrls.b.full}
            />
          </div>
        )}
        <p style={{ fontSize: 11, color: 'var(--text-dim)', padding: '8px 16px', margin: 0, borderTop: '1px solid var(--border-dim)' }}>
          Tag region = cropped view. Full page = entire sheet at reduced resolution — zoom and pan to review the full drawing.
        </p>
      </div>
    </div>
  )
}

export default function ComparisonPage() {
  const { projectId, comparisonId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  /** Empty set = show all change types. Otherwise row must match one of the selected types (OR). */
  const [changeTypeFilters, setChangeTypeFilters] = useState([])
  const [actionFilter, setActionFilter] = useState('all')

  function toggleChangeType(value) {
    setChangeTypeFilters((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]))
  }
  const [viewerRow, setViewerRow] = useState(null)

  const {
    data,
    isLoading,
    isError,
    error: queryError,
    refetch,
  } = useQuery({
    queryKey: ['comparison', projectId, comparisonId],
    queryFn: () => api.get(`/drawings/${projectId}/comparisons/${comparisonId}`).then((r) => r.data),
    enabled: Boolean(projectId && comparisonId),
  })

  const deleteComparisonMut = useMutation({
    mutationFn: () => api.delete(`/drawings/${projectId}/comparisons/${comparisonId}`),
    onSuccess: () => {
      toast.success('Comparison deleted')
      qc.invalidateQueries({ queryKey: ['comparisons', projectId] })
      navigate(`/project/${projectId}/drawings`)
    },
    onError: (e) => toastAxiosError(e, 'Delete failed'),
  })

  const result = data?.result || {}
  const rows = result.rows || []
  const summary = result.summary || {}
  const storedComparisonError = result.error
  const drawingAId = data?.drawing_id_a || result.drawing_a_id
  const drawingBId = data?.drawing_id_b || result.drawing_b_id
  const docFallbackA = result.drawing_number_a || ''
  const docFallbackB = result.drawing_number_b || ''

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (search && !String(r.tag_number).toLowerCase().includes(search.toLowerCase())) return false
      if (changeTypeFilters.length > 0 && !changeTypeFilters.includes(r.change_type)) return false
      if (actionFilter !== 'all' && r.action_needed !== actionFilter) return false
      return true
    })
  }, [rows, search, changeTypeFilters, actionFilter])

  const downloadExcel = async () => {
    try {
      const res = await api.get(`/drawings/${projectId}/report`, {
        params: { comparison_id: comparisonId, format: 'excel' },
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `comparison-${comparisonId}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Export failed')
    }
  }

  const canViewSideBySide = (r) => {
    const ia = drawingAId || r.drawing_id_a
    const ib = drawingBId || r.drawing_id_b
    const pa = parsePageNumber(r.page_a)
    const pb = parsePageNumber(r.page_b)
    return !!(ia && ib && (pa != null || pb != null))
  }

  if (isLoading) {
    return (
      <div style={{ padding: 40 }}>
        <p style={{ color: 'var(--text-secondary)' }}>Loading…</p>
      </div>
    )
  }

  if (isError) {
    return (
      <div style={{ padding: '40px 28px' }}>
        <p style={{ fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>Could not load this comparison</p>
        <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginBottom: 16 }}>{formatAxiosError(queryError, 'Request failed')}</p>
        <button type="button" className="accent" onClick={() => refetch()}>
          Retry
        </button>
        <div style={{ marginTop: 20 }}>
          <Link to={`/project/${projectId}/drawings`} style={{ fontSize: 14, color: 'var(--teal-bright)' }}>
            ← Back to drawings
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div style={{ padding: '24px 28px 48px', maxWidth: 1480 }}>
      <div style={{ marginBottom: 20, display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
        <div>
          <Link to={`/project/${projectId}/drawings`} style={{ fontSize: 13, color: 'var(--teal-bright)' }}>
            ← Back to drawings
          </Link>
          <h1 style={{ fontSize: 20, fontWeight: 600, marginTop: 12, color: 'var(--text-primary)' }}>Comparison results</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>ID: {comparisonId}</p>
          {storedComparisonError ? (
            <p style={{ color: 'var(--amber)', fontSize: 13, marginTop: 10, maxWidth: 720 }}>
              Stored comparison error: {typeof storedComparisonError === 'string' ? storedComparisonError : JSON.stringify(storedComparisonError)}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          className="sm danger"
          disabled={deleteComparisonMut.isPending}
          onClick={() => {
            if (!window.confirm('Delete this comparison from history? This cannot be undone.')) return
            deleteComparisonMut.mutate()
          }}
        >
          {deleteComparisonMut.isPending ? 'Deleting…' : 'Delete comparison'}
        </button>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
          gap: 12,
          marginBottom: 20,
        }}
      >
        {[
          ['Changes listed', rows.length, 'var(--teal-bright)'],
          ['New', summary.total_new || 0, 'var(--amber)'],
          ['Removed', summary.total_removed || 0, 'var(--red)'],
          ...(typeof summary.subsystem_changed === 'number'
            ? [
                ['Subsystem changed', summary.subsystem_changed, 'var(--blue)'],
                ['Color changed', summary.color_changed ?? 0, 'var(--blue)'],
              ]
            : [['Subsystem / color Δ', summary.total_subsystem_changes || 0, 'var(--blue)']]),
          ['Unchanged (omitted)', summary.total_unchanged || 0, 'var(--green)'],
          ['X-Tags', summary.total_x_tags || 0, 'var(--teal)'],
        ].map(([label, val, color]) => (
          <div key={label} className="card" style={{ padding: 12 }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>{label}</div>
            <div style={{ fontSize: 22, fontWeight: 600, color }}>{val}</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginBottom: 16, padding: '16px 18px' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '16px 20px',
            alignItems: 'end',
          }}
        >
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Search tag</label>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="MV-3006…"
              style={{ minHeight: 40, boxSizing: 'border-box' }}
            />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Change type</label>
            <ChangeTypeFilterDropdown
              value={changeTypeFilters}
              onToggle={toggleChangeType}
              onClear={() => setChangeTypeFilters([])}
            />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Action</label>
            <select
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              style={{ minHeight: 40, boxSizing: 'border-box' }}
            >
              <option value="all">All</option>
              <option value="assign_subsystem">Assign Subsystem</option>
              <option value="review_removal">Review Removal</option>
              <option value="review_change">Review Change</option>
              <option value="x_tag">X-Tag</option>
              <option value="future">Future</option>
              <option value="none">No Action</option>
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'flex-start' }}>
            <button
              type="button"
              className="accent"
              onClick={downloadExcel}
              style={{ minHeight: 40, paddingLeft: 20, paddingRight: 20, whiteSpace: 'nowrap' }}
            >
              Export Excel
            </button>
          </div>
        </div>
        <p style={{ fontSize: 11, color: 'var(--text-dim)', margin: '12px 0 0', lineHeight: 1.4 }}>
          Tick one or more change types in the list, or leave all unchecked to show every type.
        </p>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <p style={{ fontSize: 12, color: 'var(--text-secondary)', padding: '12px 16px 0', margin: 0, lineHeight: 1.45, maxWidth: 920 }}>
          <strong>Sub A / Sub B</strong> link subsystem bubbles by <em>color</em> (distance breaks ties). The PDF is read as
          vectors, not every pixel: we sample fills near the tag, stroke colors from nearby lines/curves (often the valve /
          line color), and avoid relying on bright red at the tag text when other samples disagree (common manual markup).
          If one side shows a dash, no bubble was linked—hover a dash for detail.
        </p>
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Tag</th>
                <th>Type</th>
                <th>Doc A</th>
                <th>Doc B</th>
                <th title={TIP_SUB}>Sub A</th>
                <th title={TIP_SUB}>Sub B</th>
                <th title={TIP_COLOR}>Color A</th>
                <th title={TIP_COLOR}>Color B</th>
                <th>Change</th>
                <th>Action</th>
                <th>Page A</th>
                <th>Page B</th>
                <th>View</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => (
                <tr key={`${r.tag_number}-${i}`} style={rowStyle(r, i)}>
                  <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--teal-bright)', fontWeight: 600 }}>{r.tag_number}</td>
                  <td style={{ color: 'var(--text-primary)' }}>{r.tag_type}</td>
                  <td style={{ fontSize: 12, maxWidth: 140, wordBreak: 'break-all', color: 'var(--text-secondary)' }}>
                    {r.drawing_number_a || docFallbackA || '—'}
                  </td>
                  <td style={{ fontSize: 12, maxWidth: 140, wordBreak: 'break-all', color: 'var(--text-secondary)' }}>
                    {r.drawing_number_b || docFallbackB || '—'}
                  </td>
                  <td>
                    <MissingHint value={r.subsystem_a} tip={TIP_SUB} />
                  </td>
                  <td>
                    <MissingHint value={r.subsystem_b} tip={TIP_SUB} />
                  </td>
                  <td>
                    {r.color_a ? <span className="color-dot" style={{ background: r.color_a }} /> : null}{' '}
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: 'var(--text-dim)' }}>
                      {r.color_a ? r.color_a : <MissingHint value={null} tip={TIP_COLOR} />}
                    </span>
                  </td>
                  <td>
                    {r.color_b ? <span className="color-dot" style={{ background: r.color_b }} /> : null}{' '}
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: 'var(--text-dim)' }}>
                      {r.color_b ? r.color_b : <MissingHint value={null} tip={TIP_COLOR} />}
                    </span>
                  </td>
                  <td style={{ color: 'var(--text-primary)' }}>{r.change_type}</td>
                  <td>
                    <ActionBadge action={r.action_needed || 'none'} />
                  </td>
                  <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-secondary)' }}>{r.page_a ?? '—'}</td>
                  <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-secondary)' }}>{r.page_b ?? '—'}</td>
                  <td>
                    {canViewSideBySide(r) ? (
                      <button
                        type="button"
                        className="sm accent"
                        style={{ padding: '2px 8px', fontSize: 11 }}
                        onClick={() => setViewerRow(r)}
                      >
                        View
                      </button>
                    ) : (
                      <span style={{ color: 'var(--text-dim)' }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length === 0 && <p style={{ padding: 24, color: 'var(--text-secondary)' }}>No rows match filters.</p>}
      </div>

      <SideBySidePdfModal
        open={!!viewerRow}
        onClose={() => setViewerRow(null)}
        projectId={projectId}
        row={viewerRow}
        drawingAId={drawingAId}
        drawingBId={drawingBId}
        docA={viewerRow?.drawing_number_a || docFallbackA}
        docB={viewerRow?.drawing_number_b || docFallbackB}
      />
    </div>
  )
}
