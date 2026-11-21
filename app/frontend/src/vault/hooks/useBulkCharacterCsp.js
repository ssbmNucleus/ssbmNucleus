/**
 * useBulkCharacterCsp
 *
 * Drives the vault-wide BULK CSP retake flow: pick any number of costumes across
 * any characters, re-render each one's portrait with its own active pose through
 * the persistent CSP render pool, review the before/after grid, and apply the
 * ones you keep. The character analog of useBulkStageCapture.
 *
 * Phases: 'select' -> 'retaking' -> 'review'. The backend renders only (writes
 * no vault changes) and reports through the shared job store; apply reuses the single-costume /generate-csp
 * endpoint (one call per kept costume, writes SD + HD), so nothing is
 * overwritten until Apply.
 *
 * Items are `{ character, skinId }`; `selected` and `keep` hold `keyOf(item)`.
 */
import { useEffect, useRef, useState } from 'react'
import { useJob } from '../../shared/jobs/useJobs'
import { discardPreviews } from '../../shared/jobs/discardPreviews'
import { backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { playSound } from '../../shared/audio/sounds'

export const keyOf = (item) => `${item.character}:${item.skinId}`

export function useBulkCharacterCsp({ onApplied } = {}) {
  const [phase, setPhase] = useState('select')        // select | retaking | review
  const [selected, setSelected] = useState(() => new Set())  // keys chosen to retake
  const [progress, setProgress] = useState(null)      // { done, total, message }
  const [results, setResults] = useState([])          // [{ character, skinId, ok, dataUri, poseName, error }]
  const [keep, setKeep] = useState(() => new Set())   // keys to apply (review)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState(null)
  const [jobId, setJobId] = useState(null)
  const requestVersion = useRef(0)
  const job = useJob(jobId)

  useEffect(() => {
    if (!job || phase !== 'retaking') return
    const items = (job.result?.items || job.extra?.items || []).map(item => ({
      ...item, dataUri: item.previewUrl ? backendMediaUrl(item.previewUrl) : null,
    }))
    setResults(items)
    setProgress({ done: job.extra?.done || 0, total: job.params.total, message: job.detail })
    if (job.status === 'done') {
      setKeep(new Set(items.filter(r => r.ok).map(keyOf)))
      setPhase('review')
      playSound(items.some(r => r.ok) ? 'achievement' : 'error')
    } else if (['failed', 'cancelled', 'interrupted'].includes(job.status)) {
      setError(job.error || 'Bulk retake cancelled')
      setPhase('select')
      playSound('error')
    }
  }, [job, phase])

  const reset = () => {
    requestVersion.current += 1
    if (jobId) discardPreviews(jobId, `/storage/costumes/batch-retake-csp/${jobId}`)
    setJobId(null)
    setPhase('select'); setProgress(null); setResults([]); setKeep(new Set())
    setSelected(new Set()); setApplying(false); setError(null)
  }

  const toggle = (item) => setSelected((prev) => {
    const next = new Set(prev)
    const k = keyOf(item)
    next.has(k) ? next.delete(k) : next.add(k)
    return next
  })
  // Bulk select/deselect a list of items (presets + per-character toggle).
  const setMany = (items, on) => setSelected((prev) => {
    const next = new Set(prev)
    for (const it of items) on ? next.add(keyOf(it)) : next.delete(keyOf(it))
    return next
  })
  const clearSelection = () => setSelected(new Set())

  const startRetake = async (items) => {
    if (!items.length) return
    const version = ++requestVersion.current
    playSound('start')
    setJobId(null)
    setPhase('retaking'); setError(null); setResults([])
    setProgress({ done: 0, total: items.length, message: `Retaking 0/${items.length}…` })

    try {
      const data = await api.post('/storage/costumes/batch-retake-csp',
        { items: items.map(({ character, skinId }) => ({ character, skinId })) })
      if (version !== requestVersion.current) {
        discardPreviews(data.job_id, `/storage/costumes/batch-retake-csp/${data.job_id}`)
        return
      }
      setJobId(data.job_id)
    } catch (err) {
      if (version !== requestVersion.current) return
      setError(`Failed to start bulk retake: ${err.message}`)
      setPhase('select'); playSound('error')
    }
  }

  const toggleKeep = (item) => setKeep((prev) => {
    const next = new Set(prev)
    const k = keyOf(item)
    next.has(k) ? next.delete(k) : next.add(k)
    return next
  })

  const applyKept = async () => {
    const toApply = results.filter((r) => r.ok && r.dataUri && keep.has(keyOf(r)))
    if (!toApply.length) return 0
    setApplying(true); setError(null)
    let applied = 0
    for (const r of toApply) {
      try {
        // Reuse the single-costume retake's apply: derives SD + HD from the HD
        // preview and writes it to the costume's active portrait.
        const blob = await api.blob(r.previewUrl)
        const imageData = await new Promise((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result)
          reader.onerror = () => reject(reader.error)
          reader.readAsDataURL(blob)
        })
        await api.post('/storage/costumes/generate-csp',
          { character: r.character, skinId: r.skinId, apply: true, imageData })
        applied++
      } catch (e) { /* keep going; the count reflects it */ }
    }
    setApplying(false)
    playSound(applied ? 'achievement' : 'error')
    // Never let a refresh callback error bubble up and abort the modal close.
    try { if (onApplied) onApplied(applied) } catch (e) { /* ignore */ }
    return applied
  }

  return {
    phase, selected, toggle, setMany, clearSelection, keyOf,
    progress, results, keep, toggleKeep, applying, error,
    startRetake, applyKept, reset, setError,
  }
}
