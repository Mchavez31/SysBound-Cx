import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api, { toastAxiosError } from '../lib/api'
import toast from 'react-hot-toast'

function ImageModal({ src, onClose, tagName }) {
  if (!src) return null

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.90)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        cursor: 'zoom-out',
        padding: 20
      }}
    >
      <div style={{ position: 'relative', maxWidth: '90vw', maxHeight: '90vh' }}>
        <button
          onClick={onClose}
          className="accent"
          style={{
            position: 'absolute',
            top: -40,
            right: 0,
            padding: '8px 12px',
            fontSize: 14
          }}
        >
          Close (ESC)
        </button>
        {tagName && (
          <div
            style={{
              position: 'absolute',
              top: -40,
              left: 0,
              color: 'var(--teal-bright)',
              fontSize: 14,
              fontWeight: 600,
              fontFamily: "'JetBrains Mono', monospace"
            }}
          >
            {tagName}
          </div>
        )}
        <img
          src={src}
          alt="Enlarged preview"
          onClick={(e) => e.stopPropagation()}
          style={{
            maxWidth: '90vw',
            maxHeight: '90vh',
            border: '2px solid var(--teal)',
            borderRadius: 4,
            display: 'block',
            cursor: 'default'
          }}
        />
      </div>
    </div>
  )
}

function TagSnippet({ projectId, drawingId, page, x, y, tagName }) {
  const [imgSrc, setImgSrc] = useState(null)
  const [largeImgSrc, setLargeImgSrc] = useState(null)
  const [error, setError] = useState(false)
  const [showModal, setShowModal] = useState(false)

  useEffect(() => {
    if (!drawingId || !page || x == null || y == null) {
      setError(true)
      return
    }

    // Load thumbnail (small margin)
    const thumbUrl = `/drawings/${projectId}/drawing/${drawingId}/snippet?page=${page}&x=${x}&y=${y}&margin=120`
    api.get(thumbUrl, { responseType: 'blob' })
      .then((response) => {
        const blob = response.data
        const objectUrl = URL.createObjectURL(blob)
        setImgSrc(objectUrl)
      })
      .catch(() => {
        setError(true)
      })

    return () => {
      if (imgSrc && imgSrc.startsWith('blob:')) {
        URL.revokeObjectURL(imgSrc)
      }
      if (largeImgSrc && largeImgSrc.startsWith('blob:')) {
        URL.revokeObjectURL(largeImgSrc)
      }
    }
  }, [projectId, drawingId, page, x, y])

  const handleClick = () => {
    if (!largeImgSrc) {
      // Load larger version with bigger margin
      const largeUrl = `/drawings/${projectId}/drawing/${drawingId}/snippet?page=${page}&x=${x}&y=${y}&margin=150`
      api.get(largeUrl, { responseType: 'blob' })
        .then((response) => {
          const blob = response.data
          const objectUrl = URL.createObjectURL(blob)
          setLargeImgSrc(objectUrl)
          setShowModal(true)
        })
        .catch(() => {
          toast.error('Failed to load enlarged image')
        })
    } else {
      setShowModal(true)
    }
  }

  useEffect(() => {
    if (!showModal) return
    
    const handleEsc = (e) => {
      if (e.key === 'Escape') {
        setShowModal(false)
      }
    }
    
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [showModal])

  if (error || (!imgSrc && !drawingId)) {
    return <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>No preview</span>
  }

  if (!imgSrc) {
    return <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Loading...</span>
  }

  return (
    <>
      <img
        src={imgSrc}
        alt="Tag preview"
        onClick={handleClick}
        style={{
          width: '100%',
          maxWidth: 220,
          height: 'auto',
          border: '1px solid var(--border-mid)',
          borderRadius: 4,
          display: 'block',
          cursor: 'pointer',
          transition: 'transform 0.1s, box-shadow 0.1s'
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'scale(1.05)'
          e.currentTarget.style.boxShadow = '0 4px 16px rgba(20,184,166,0.4)'
          e.currentTarget.style.borderColor = 'var(--teal)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'scale(1)'
          e.currentTarget.style.boxShadow = 'none'
          e.currentTarget.style.borderColor = 'var(--border-mid)'
        }}
      />
      {showModal && <ImageModal src={largeImgSrc} onClose={() => setShowModal(false)} tagName={tagName} />}
    </>
  )
}

function VerdictBadge({ verdict }) {
  const v = (verdict || '').toLowerCase()
  if (!v || v === 'none') return <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>—</span>
  const color = v === 'valid' ? 'var(--green)' : 'var(--red)'
  return (
    <span style={{ fontSize: 12, fontWeight: 600, color }}>{v === 'valid' ? 'Valid' : 'Invalid'}</span>
  )
}

export default function TagTrainingPage() {
  const { projectId } = useParams()
  const qc = useQueryClient()
  const [docRole, setDocRole] = useState('tagging_spec')
  const [uploadFile, setUploadFile] = useState(null)
  const [selected, setSelected] = useState(() => new Set())

  const { data: refs } = useQuery({
    queryKey: ['tag-training', 'refs', projectId],
    queryFn: () => api.get(`/projects/${projectId}/tag-training/reference-docs`).then((r) => r.data),
    enabled: Boolean(projectId),
  })

  const { data: candidates, refetch: refetchReview } = useQuery({
    queryKey: ['tag-training', 'candidates', projectId],
    queryFn: () => api.get(`/projects/${projectId}/tag-training/review-candidates`).then((r) => r.data),
    enabled: Boolean(projectId),
  })

  useEffect(() => {
    const tags = candidates?.tags || []
    const next = new Set()
    for (const t of tags) {
      const tagStr = typeof t === 'string' ? t : t.tag
      next.add(String(tagStr))
    }
    setSelected(next)
  }, [candidates?.comparison_id])

  const verdictMap = useMemo(() => candidates?.verdicts || {}, [candidates?.verdicts])
  const docs = refs?.documents || []
  const tagList = candidates?.tags || []
  
  // Debug: Log first tag to console
  useEffect(() => {
    if (tagList.length > 0) {
      console.log('First tag data:', tagList[0])
      console.log('Total tags:', tagList.length)
    }
  }, [tagList])

  const uploadMut = useMutation({
    mutationFn: async () => {
      const fd = new FormData()
      fd.append('file', uploadFile)
      fd.append('doc_role', docRole)
      return api.post(`/projects/${projectId}/tag-training/reference-docs`, fd, {
        timeout: 240000,
      })
    },
    onSuccess: () => {
      toast.success('File saved')
      setUploadFile(null)
      qc.invalidateQueries({ queryKey: ['tag-training', 'refs', projectId] })
    },
    onError: (e) => toastAxiosError(e, 'Upload failed'),
  })

  const deleteDocMut = useMutation({
    mutationFn: (id) => api.delete(`/projects/${projectId}/tag-training/reference-docs/${id}`),
    onSuccess: () => {
      toast.success('Removed')
      qc.invalidateQueries({ queryKey: ['tag-training', 'refs', projectId] })
    },
    onError: (e) => toastAxiosError(e, 'Remove failed'),
  })

  const verdictMut = useMutation({
    mutationFn: async (items) =>
      api.post(`/projects/${projectId}/tag-training/verdicts/bulk`, { items }),
    onSuccess: () => {
      toast.success('Labels saved')
      refetchReview()
    },
    onError: (e) => toastAxiosError(e, 'Save failed'),
  })

  function toggleOne(tag) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

  function selectAllListed() {
    const allTags = tagList.map((t) => (typeof t === 'string' ? t : t.tag))
    setSelected(new Set(allTags.map(String)))
    toast.success(tagList.length ? `Selected ${tagList.length} tag(s)` : 'Nothing to select')
  }

  function applyVerdictToSelected(verdict) {
    const items = [...selected].map((tag) => ({ tag, verdict }))
    if (!items.length) {
      toast.error('Tick at least one tag first')
      return
    }
    verdictMut.mutate(items)
  }

  return (
    <div style={{ padding: '24px 28px 48px', maxWidth: 1100 }}>
      <Link to={`/project/${projectId}`} style={{ fontSize: 13, color: 'var(--teal-bright)', fontWeight: 500, textDecoration: 'none' }}>
        ← Back to dashboard
      </Link>
      <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)', borderBottom: '1px solid var(--border-dim)', paddingBottom: 16, marginTop: 12, marginBottom: 24 }}>Tag extraction training</h1>
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 24, lineHeight: 1.6, maxWidth: 860 }}>
        Upload your tagging specification and any supplemental descriptions so reviewers know what “good” references are.
        Stored files persist until removed.         Labels you mark <strong>invalid</strong> are excluded on the{' '}
        <strong>next comparisons</strong> for this project (suppressed during PDF tag extraction).
        Tags you label <strong>valid</strong> are stored too so you can correct mistakes later; widening the parser automatically from “valid” is planned.
      </p>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, color: 'var(--teal-bright)' }}>Reference documents</h2>
        <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 14, lineHeight: 1.5 }}>
          PDFs stored on the server drive (not interpreted automatically yet — they guide humans and anchor future parsers).
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end', marginBottom: 16 }}>
          <div className="form-group" style={{ marginBottom: 0, minWidth: 200 }}>
            <label>Document type</label>
            <select
              value={docRole}
              onChange={(e) => setDocRole(e.target.value)}
            >
              <option value="tagging_spec">Tagging specification</option>
              <option value="supplemental">Supplemental / notes</option>
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>File</label>
            <input
              type="file"
              accept=".pdf,.doc,.docx,.txt,.xls,.xlsx,.csv"
              onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
            />
          </div>
          <button
            type="button"
            className="accent"
            disabled={!uploadFile || uploadMut.isPending}
            onClick={() => uploadMut.mutate()}
          >
            {uploadMut.isPending ? 'Saving…' : 'Upload'}
          </button>
        </div>

        {!docs.length ? (
          <p style={{ fontSize: 13, color: 'var(--text-dim)' }}>No reference files yet.</p>
        ) : (
          <ul style={{ listStyle: 'none', paddingLeft: 0, margin: 0 }}>
            {docs.map((d) => (
              <li key={d.id} style={{ marginBottom: 10, padding: '10px 12px', background: 'var(--bg-elevated)', border: '1px solid var(--border-dim)', borderRadius: 6, display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{d.original_filename}</span>
                  <span className="badge gray" style={{ marginLeft: 8 }}>
                    {d.doc_role === 'tagging_spec' ? 'spec' : 'supplement'}
                  </span>
                </div>
                <button
                  type="button"
                  className="sm danger"
                  disabled={deleteDocMut.isPending}
                  onClick={() => {
                    if (!window.confirm('Remove this stored file permanently?')) return
                    deleteDocMut.mutate(d.id)
                  }}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, color: 'var(--teal-bright)' }}>Review captured tags</h2>
        <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 14, lineHeight: 1.5 }}>
          The list pulls unique strings from your <strong>latest completed comparison</strong>
          {candidates?.comparison_id ? ` (${candidates.comparison_id.slice(0, 8)}…)` : ''}. Tick lines that are phantom or
          fragment tags, click <em>Invalid</em>; tick real tags incorrectly classified before, choose <em>Valid</em>. All
          selected tags share one verdict per save.
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
          <button type="button" className="sm" onClick={selectAllListed} disabled={!tagList.length}>
            Select all
          </button>
          <button
            type="button"
            className="sm"
            onClick={() => setSelected(new Set())}
          >
            Clear selection
          </button>
          <button
            type="button"
            className="danger"
            disabled={verdictMut.isPending}
            onClick={() => applyVerdictToSelected('invalid')}
          >
            Mark selected invalid
          </button>
          <button
            type="button"
            className="accent"
            disabled={verdictMut.isPending}
            onClick={() => applyVerdictToSelected('valid')}
          >
            Mark selected valid
          </button>
          <button type="button" className="sm" onClick={() => refetchReview()}>
            Refresh list
          </button>
          <Link className="sm" to={`/project/${projectId}/drawings`} style={{ display: 'inline-flex', alignItems: 'center', background: 'var(--bg-elevated)', border: '1px solid var(--border-mid)', color: 'var(--teal-bright)', textDecoration: 'none' }}>
            Run a comparison →
          </Link>
        </div>

        {!tagList.length ? (
          <p style={{ fontSize: 13, color: 'var(--text-dim)' }}>Complete a comparison first to populate suggestions.</p>
        ) : (
          <div style={{ overflowX: 'auto', borderTop: '1px solid var(--border-dim)', marginTop: 12 }}>
            <table>
              <thead><tr><th style={{ width: 48 }}>#</th><th style={{ width: 120 }}>Preview</th><th>Captured tag text</th><th>Stored label</th></tr></thead>
              <tbody>
                {tagList.map((t, idx) => {
                  const tagStr = typeof t === 'string' ? t : t.tag
                  const tagData = typeof t === 'object' ? t : null
                  
                  return (
                    <tr key={tagStr} style={{ background: idx % 2 === 0 ? 'var(--bg-card)' : 'rgba(20,184,166,0.03)' }}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selected.has(String(tagStr))}
                          onChange={() => toggleOne(String(tagStr))}
                          style={{ width: 16, height: 16, cursor: 'pointer' }}
                        />
                      </td>
                      <td>
                        <TagSnippet
                          projectId={projectId}
                          drawingId={tagData?.drawing_id}
                          page={tagData?.page}
                          x={tagData?.x}
                          y={tagData?.y}
                          tagName={tagStr}
                        />
                      </td>
                      <td style={{ fontWeight: 500, fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--teal-bright)' }}>
                        {String(tagStr)}
                      </td>
                      <td>
                        <VerdictBadge verdict={verdictMap[String(tagStr)] || ''} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.5, marginTop: 16 }}>
        Note: Parsing comes from structured PDF vectors; digit runs sometimes split visually. Prefer instrument line text
        <code style={{ padding: '0 4px', background: 'var(--bg-elevated)', borderRadius: 2, color: 'var(--teal-bright)' }}> PREFIX-digits-sheetSuffix</code>, e.g.<code style={{ padding: '0 4px', background: 'var(--bg-elevated)', borderRadius: 2, color: 'var(--teal-bright)' }}>
          2"-AI-9881719-A1V3X
        </code>
        , when spotting mis-reads — that format is prioritized when it appears intact in raw text streams.
      </p>
    </div>
  )
}
