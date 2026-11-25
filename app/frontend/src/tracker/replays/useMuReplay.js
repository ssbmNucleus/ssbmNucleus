import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../shared/transport/api'
import { useJob } from '../../shared/jobs/useJobs'
import { appAlert } from '../../shared/ui/appDialogs'

/**
 * useMuReplay - "Watch in Nucleus Unlocked" for a Tracker replay row (Play builds only).
 *
 * GET /api/play/replay says whether a replay can start now ({available, reason}: the Melee
 * Unlocked folder, its SysPlayback folder, the processor, the user's disc). POST
 * /api/play/replay {path} starts the game's replay viewer as a play_launch job; the backend
 * takes only a replay Tracker indexed. When the viewer ends badly (it could not open the
 * replay, crashed), the job's message is shown.
 *
 * Returns null when Play is off (the action is not offered), else
 * { available, reason, watch(game), refresh() }.
 */
const QUIET = new Set(['quit', 'started', 'unwatched'])

export function endedBadly(record) {
  if (!record) return null
  if (record.status === 'failed') return record.error || 'Nucleus Unlocked could not play that replay.'
  if (record.status === 'done' && record.result && !QUIET.has(record.result.outcome)) {
    return record.result.message || 'Nucleus Unlocked could not play that replay.'
  }
  return null
}

export function useMuReplay(enabled) {
  const [status, setStatus] = useState(null)
  const [jobId, setJobId] = useState(null)
  const told = useRef(null)
  const job = useJob(jobId)

  const refresh = useCallback(() => {
    if (!enabled) return
    api.get('/api/play/replay')
      .then((data) => setStatus({ available: Boolean(data.available), reason: data.reason || null }))
      .catch(() => setStatus(null))          // Play is not in this backend: nothing to offer
  }, [enabled])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {
    const problem = endedBadly(job)
    if (problem && told.current !== jobId) {
      told.current = jobId
      appAlert(problem)
    }
  }, [job, jobId])

  const watch = useCallback(async (game) => {
    try {
      const data = await api.post('/api/play/replay', { path: game.path })
      setJobId(data.job_id || null)
    } catch (err) {
      appAlert(err.message || 'Nucleus Unlocked could not play that replay.')
      refresh()
    }
  }, [refresh])

  if (!enabled || !status) return null
  return { ...status, watch, refresh }
}
