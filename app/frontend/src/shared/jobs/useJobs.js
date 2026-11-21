/**
 * useJobs.js — read background jobs from the window's job store (jobs.js).
 *
 *   const job = useJob(jobId)                       // the record, or null until known
 *   const running = useActiveJob('vault_restore')   // newest queued/running of a kind
 *   const finished = useFinishedJobs('bundle_export') // changes when one more is done
 *   const last = useLatestJob('replay_scan')        // newest of a kind, in any status
 *   useJobEnd('replay_scan', (job) => reload())     // each one that ends while mounted
 *
 * jobOutcome.js turns a record into { ok, result | error } once it has ended.
 *
 * A record is { id, kind, label, status, progress, detail, error, result,
 * params, notes, extra, seen, ... }; status is queued | running | done |
 * failed | cancelled | interrupted. See core/jobs.py.
 */
import { useEffect, useRef, useSyncExternalStore } from 'react'
import { jobStore, startJobStore } from './jobs'
import { endedAfter } from './passView'

export { cancelJob, markJobSeen, refreshJob } from './jobs'

/** The record of job `id`, read from the store; one the store lacks is asked for once. With `ask: false` it is only
 * read (its events still arrive): an id this window chose itself, which the backend has not heard of yet and would
 * answer 404 (a Vault restore names its job before the upload that starts it). */
export function useJob(id, { ask = true } = {}) {
  useEffect(() => {
    startJobStore()
    if (ask && id && !jobStore.get(id)) jobStore.refresh(id).catch(() => {})
  }, [id, ask])
  return useSyncExternalStore(jobStore.subscribe, () => (id ? jobStore.get(id) : null))
}

export function useActiveJob(kind) {
  useEffect(() => { startJobStore() }, [])
  return useSyncExternalStore(jobStore.subscribe, () => jobStore.active(kind))
}

export function useLatestJob(kind) {
  useEffect(() => { startJobStore() }, [])
  return useSyncExternalStore(jobStore.subscribe, () => jobStore.latest(kind))
}

/** When the newest ended job of `kind` ended (seconds), or null. */
export function useJobEndedAt(kind) {
  useEffect(() => { startJobStore() }, [])
  return useSyncExternalStore(jobStore.subscribe, () => jobStore.lastEnded(kind)?.ended_at ?? null)
}

/** Call `onEnd(record)` once for each job of `kind` that ends while this is
 * mounted (the newest, if several end at once): a screen reloading what the
 * job changed. Jobs that ended before the screen mounted are not reported. */
export function useJobEnd(kind, onEnd) {
  const last = useSyncExternalStore(jobStore.subscribe, () => jobStore.lastEnded(kind))
  const since = useRef(Date.now() / 1000)
  const handled = useRef(null)
  const callback = useRef(onEnd)
  callback.current = onEnd
  useEffect(() => { startJobStore() }, [])
  useEffect(() => {
    if (!endedAfter(last, since.current, handled.current)) return
    handled.current = last.id
    callback.current(last)
  }, [last])
}

export function useJobList() {
  useEffect(() => { startJobStore() }, [])
  return useSyncExternalStore(jobStore.subscribe, jobStore.list)
}

/** The ids of the finished (done) jobs of `kind`, as one string that changes
 * when another one finishes: key an effect on it to refresh a list. */
export function useFinishedJobs(kind) {
  useEffect(() => { startJobStore() }, [])
  return useSyncExternalStore(jobStore.subscribe, () => jobStore.list()
    .filter((job) => job.kind === kind && job.status === 'done')
    .map((job) => job.id).join(','))
}
