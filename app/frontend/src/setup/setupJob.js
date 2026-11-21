/**
 * setupJob.js — which first-run setup job the wizard shows, and which step it
 * means. The job (core/jobs.py `first_run_setup`) lives in the window's job
 * store; the wizard keeps no copy of its status.
 */
import { ACTIVE } from '../shared/jobs/jobStore.js'

export const SETUP_KIND = 'first_run_setup'

// Ended setups the wizard still shows until the user moves on (Get Started or
// Try Again marks them seen). An interrupted one is InterruptedJobsNotice's.
const SHOWN_ENDED = new Set(['done', 'failed', 'cancelled'])

/**
 * The setup job to show: the one this wizard started, else a running one (a
 * setup started before the wizard was closed), else the newest ended one the
 * user has not seen. `jobs` is the store's list, newest first.
 */
export function setupJobToShow(jobs, { startedId = null, dismissedId = null } = {}) {
  const setups = (jobs || []).filter(job => job.kind === SETUP_KIND && job.id !== dismissedId)
  if (startedId) return setups.find(job => job.id === startedId) || null
  return setups.find(job => ACTIVE.has(job.status))
    || setups.find(job => SHOWN_ENDED.has(job.status) && !job.seen)
    || null
}

/**
 * The wizard step for a setup job. Only a finished job whose result the wizard
 * has applied (the ISO path saved) is `complete`: the engine's own "complete"
 * progress phase arrives while it is still cleaning up.
 */
export function setupStep(job, appliedId = null) {
  if (!job) return null
  if (ACTIVE.has(job.status)) {
    const phase = job.extra?.phase
    if (!phase || phase === 'verifying') return 'verifying'
    return phase === 'extracting' ? 'extracting' : 'copying'
  }
  if (job.status === 'done') return appliedId === job.id ? 'complete' : 'copying'
  return 'error'
}


/** Retry submits the same auto-detected ISO the welcome screen shows. */
export function setupRetryPath(autoDetectedPaths) {
  return autoDetectedPaths?.isoPath || ''
}
