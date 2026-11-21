import { useState, useEffect, useRef } from 'react'
import { api } from '../../shared/transport/api'
import { useJob } from '../../shared/jobs/useJobs'
import { jobOutcome, jobPercent } from '../../shared/jobs/jobOutcome'

/**
 * useVaultPlay - "Play" (launch in real Slippi) state for the vault.
 *
 * Shared by bundles and patches. Each Play is a backend job (`bundle_play` or
 * `patch_play`, core/jobs.py); the overlay follows that job's record, so a
 * later Play of the same bundle never shows an earlier one's outcome.
 */
export function useVaultPlay() {
  // { id: the bundle or patch, jobId, error: the request's own failure }
  const [play, setPlay] = useState(null)
  const playRef = useRef(null)
  const job = useJob(play?.jobId || null)
  const outcome = jobOutcome(job)

  const setCurrentPlay = (next) => {
    playRef.current = next
    setPlay(next)
  }

  // "Play": build the ISO if missing, (bundles) load the texture pack, then launch
  // the user's real Slippi Dolphin.
  const startPlay = async (kind, id) => {
    const slippiPath = localStorage.getItem('slippi_dolphin_path')
    const vanillaIsoPath = localStorage.getItem('vanilla_iso_path')
    if (!slippiPath) {
      alert('Slippi Dolphin path not set. Please configure it in Settings.')
      return
    }
    const attempt = { id, jobId: null, error: null }
    setCurrentPlay(attempt)
    try {
      const route = kind === 'bundle' ? `bundle/play/${id}` : `xdelta/play/${id}`
      const data = await api.post(`/${route}`, { slippiPath, vanillaIsoPath })
      if (playRef.current === attempt) setCurrentPlay({ ...attempt, jobId: data.job_id })
    } catch (err) {
      if (playRef.current !== attempt) return
      // err.data => the backend reported the failure itself
      setCurrentPlay({ ...attempt, error: err.data ? (err.message || 'Failed to start') : `Play error: ${err.message}` })
    }
  }
  const handlePlayBundle = (bundle) => startPlay('bundle', bundle.id)
  const handlePlayPatch = (patch) => startPlay('patch', patch.id)
  const dismissPlay = () => setCurrentPlay(null)

  const playLaunched = Boolean(outcome?.ok)

  // Auto-dismiss the overlay shortly after a successful launch.
  useEffect(() => {
    if (!playLaunched) return
    const launched = playRef.current
    const t = setTimeout(() => { if (playRef.current === launched) setCurrentPlay(null) }, 2500)
    return () => clearTimeout(t)
  }, [playLaunched])

  return {
    playingId: play?.id ?? null,
    playPercent: jobPercent(job) ?? 0,
    playMessage: job?.detail || 'Starting...',
    playError: play?.error || (outcome && !outcome.ok ? outcome.error : null),
    playLaunched,
    startPlay,
    handlePlayBundle,
    handlePlayPatch,
    dismissPlay
  }
}
