/**
 * watchJob.js — what the Watch popups show of the watch job (a `replay_watch`
 * record from the job store, core/jobs.py). Pure, so `node --test` covers it;
 * WatchPlayback.jsx's useWatchJob wires it to the store.
 */
import { ACTIVE } from '../../shared/jobs/jobStore.js'

export const WATCH_KIND = 'replay_watch'

// Shown while a Start request is out and until its job's record arrives.
export const STARTING = Object.freeze({
  id: null, state: 'starting', busy: true, detail: 'Starting…', error: null,
  capture_session_id: null, widescreen: false, batch_total: 0, recordings: [],
  last_recording: null, seen: false,
})

const FAILED = new Set(['failed', 'interrupted'])

/** The popup's view of one watch record: `state` is its step while it runs
 * (extra.phase), else its final status. */
export function watchView(job) {
  if (!job) return null
  const extra = job.extra || {}
  const params = job.params || {}
  const result = job.result || {}
  const busy = ACTIVE.has(job.status)
  const recordings = result.recordings || extra.recordings || []
  return {
    id: job.id,
    state: busy ? (extra.phase || 'starting') : job.status,
    busy,
    detail: job.detail || (busy ? 'Starting…' : ''),
    error: job.error || null,
    capture_session_id: busy ? (extra.capture_session_id || null) : null,
    widescreen: !!params.widescreen,
    batch_total: params.batch_total || 0,
    recordings,
    last_recording: result.last_recording || extra.last_recording
      || recordings[recordings.length - 1] || null,
    seen: !!job.seen,
  }
}

/** The watch a popup shows: the newest watch job in the store (`jobs`, newest
 * first). While its own Start is out, or its job's record has not arrived yet,
 * it shows STARTING, so the popup counts as busy from the click on. */
export function currentWatch({ jobs, pending = false, startedId = null }) {
  if (pending) return STARTING
  const watches = (jobs || []).filter((job) => job.kind === WATCH_KIND)
  if (startedId && !watches.some((job) => job.id === startedId)) return STARTING
  return watchView(watches[0] || null)
}

/** A failed (or interrupted) watch whose error the user has not dismissed. */
export function watchFailed(view) {
  return !!view && FAILED.has(view.state) && !view.seen
}

/** Which part a Watch popup shows: the running watch, its failure, the
 * options still loading or failed to load (`error` with no `options`), or
 * the form. */
export function popupPart({ options, error, job }) {
  if (job?.busy) return 'watch'
  if (watchFailed(job)) return 'failed'
  if (!options) return error ? 'load-error' : 'loading'
  return 'form'
}
