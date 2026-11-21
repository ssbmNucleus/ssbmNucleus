/**
 * useBulkStageCapture
 *
 * Drives the vault-wide BULK stage-screenshot flow: pick any number of stage
 * variants across any stages, render each one's preview OFFLINE with the HSD
 * stage renderer (no test ISO build, no Dolphin boot — that is what this
 * replaced), review the grid, and save the ones you keep. The stage analog of
 * useBulkCharacterCsp.
 *
 * Phases: 'select' -> 'rendering' -> 'review'. The backend renders only (writes
 * no vault changes) and reports through the shared job store; saving reuses the single-variant
 * /storage/stages/update-screenshot endpoint (one call per kept variant), so
 * nothing is overwritten until Save.
 */
import { useEffect, useRef, useState } from 'react'
import { useJob, cancelJob } from '../../shared/jobs/useJobs'
import { discardPreviews } from '../../shared/jobs/discardPreviews'
import { backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { playSound } from '../../shared/audio/sounds'

// Vault list items key on `id`; rendered results key on `variantId`. Both are
// scoped by stage — the same variant name exists on more than one stage.
export const keyOf = (v) => `${v.stageCode}:${v.id ?? v.variantId}`

export function useBulkStageCapture({ onSaved } = {}) {
  const [phase, setPhase] = useState('select')        // select | rendering | review
  const [variants, setVariants] = useState([])        // all vault stage variants
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(() => new Set())  // keys chosen to render
  const [progress, setProgress] = useState(null)      // { done, total, message }
  const [results, setResults] = useState([])          // [{..., ok, dataUri, error }]
  const [keep, setKeep] = useState(() => new Set())   // keys to save (review)
  const [saving, setSaving] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [jobId, setJobId] = useState(null)
  const stopRequested = useRef(false)
  const requestVersion = useRef(0)
  const job = useJob(jobId)

  useEffect(() => {
    if (!job || phase !== 'rendering') return
    const items = (job.result?.items || job.extra?.items || []).map(item => ({
      ...item, dataUri: item.previewUrl ? backendMediaUrl(item.previewUrl) : null,
    }))
    setResults(items)
    setProgress({ done: job.extra?.done || 0, total: job.params.total, message: job.detail })
    if (['done', 'cancelled'].includes(job.status)) {
      setKeep(new Set(items.filter(r => r.ok).map(keyOf)))
      setPhase('review')
      setStopping(false)
      playSound(items.some(r => r.ok) ? 'achievement' : 'error')
    } else if (['failed', 'interrupted'].includes(job.status)) {
      setError(job.error || 'Bulk stage render failed')
      setPhase('select')
      setStopping(false)
      playSound('error')
    }
  }, [job, phase])

  const reset = () => {
    requestVersion.current += 1
    if (jobId) discardPreviews(jobId, `/storage/stages/render-screenshots/${jobId}`)
    setJobId(null)
    stopRequested.current = false
    setPhase('select'); setProgress(null); setResults([]); setKeep(new Set())
    setSelected(new Set()); setError(null); setSaving(false); setStopping(false)
  }

  const loadVariants = async () => {
    setLoading(true); setError(null)
    try {
      const data = await api.get('/das/storage/variants')
      setVariants(data.variants || [])
    } catch (err) {
      setError(`Failed to load variants: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  const toggle = (v) => {
    const k = keyOf(v)
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(k) ? next.delete(k) : next.add(k)
      return next
    })
  }
  const setMany = (vs, on) => setSelected((prev) => {
    const next = new Set(prev)
    vs.forEach((v) => (on ? next.add(keyOf(v)) : next.delete(keyOf(v))))
    return next
  })
  const clearSelection = () => setSelected(new Set())

  const startRender = async () => {
    const chosen = variants.filter((v) => selected.has(keyOf(v)))
    if (!chosen.length) return
    const version = ++requestVersion.current
    const payload = chosen.map((v) => ({
      stageCode: v.stageCode, variantId: v.id, name: v.name,
    }))

    playSound('start')
    setJobId(null)
    stopRequested.current = false
    setPhase('rendering'); setError(null); setResults([]); setStopping(false)
    setProgress({ done: 0, total: chosen.length, message: `Rendering 0/${chosen.length}…` })

    try {
      const data = await api.post('/storage/stages/render-screenshots', { variants: payload })
      if (version !== requestVersion.current) {
        discardPreviews(data.job_id, `/storage/stages/render-screenshots/${data.job_id}`)
        return
      }
      setJobId(data.job_id)
      if (stopRequested.current) await cancelJob(data.job_id)
    } catch (err) {
      if (version !== requestVersion.current) return
      setError(`Failed to start bulk render: ${err.message}`)
      setPhase('select'); playSound('error')
    }
  }

  // Stop after the variant currently on the renderer; everything already drawn
  // still comes back for review.
  const cancelRender = async () => {
    stopRequested.current = true
    setStopping(true)
    try {
      if (jobId) await cancelJob(jobId)
    } catch (err) {
      stopRequested.current = false
      setStopping(false)
      setError(`Failed to stop the render: ${err.message}`)
    }
  }

  const toggleKeep = (r) => setKeep((prev) => {
    const next = new Set(prev)
    const k = keyOf(r)
    next.has(k) ? next.delete(k) : next.add(k)
    return next
  })

  const saveKept = async () => {
    const toSave = results.filter((r) => r.ok && r.dataUri && keep.has(keyOf(r)))
    if (!toSave.length) return 0
    setSaving(true); setError(null)
    let saved = 0
    for (const r of toSave) {
      try {
        const fd = new FormData()
        fd.append('stageFolder', r.stageFolder)
        fd.append('variantId', r.variantId)
        fd.append('screenshot', await api.blob(r.previewUrl), `${r.variantId}.png`)
        await api.post('/storage/stages/update-screenshot', fd)
        saved++
      } catch (e) { /* keep going; reported via count */ }
    }
    setSaving(false)
    playSound(saved ? 'achievement' : 'error')
    // Never let a refresh callback error bubble up and abort the modal close.
    try { if (onSaved) onSaved(saved) } catch (e) { /* ignore */ }
    return saved
  }

  return {
    phase, variants, loading, error,
    selected, toggle, setMany, clearSelection, keyOf,
    progress, results, keep, toggleKeep, saving, stopping,
    loadVariants, startRender, cancelRender, saveKept, reset, setError,
  }
}
