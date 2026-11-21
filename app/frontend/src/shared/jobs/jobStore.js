/**
 * jobStore.js — the window's copy of the backend's background jobs (core/jobs.py).
 *
 * The backend emits one `job` socket event per change, carrying the whole
 * record, and answers the same records at GET /api/jobs. The store keeps the
 * newest record per id (by `seq`) and asks again on load and on every
 * reconnect, so a screen that mounts late or a socket that dropped never shows
 * a job in the wrong state. Screens read it through useJobs.js; none keeps its
 * own copy of a job's status.
 */

export const ACTIVE = new Set(['queued', 'running'])

// Ended records kept per kind. A kind the backend runs every few minutes (the
// replay scan the cloud loop starts) would otherwise grow the store for the
// life of the window.
export const KEEP_ENDED = 20

const sameOwner = (a, b) => a?.pid === b?.pid && a?.created === b?.created

/** Whether `next` should replace `prev`: a later seq from the same backend. */
export function isNewer(next, prev) {
  if (!prev) return true
  if (!sameOwner(next.owner, prev.owner)) return true
  return (next.seq ?? 0) > (prev.seq ?? 0)
}

export function createJobStore({ fetchJobs, fetchJob }) {
  let jobs = new Map()
  let list = []
  const listeners = new Set()

  const notify = () => {
    list = [...jobs.values()].sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
    for (const listener of listeners) listener()
  }

  const put = (record, force = false) => {
    if (!record?.id) return false
    if (!force && !isNewer(record, jobs.get(record.id))) return false
    jobs = new Map(jobs)
    jobs.set(record.id, record)
    if (!ACTIVE.has(record.status)) forgetOld(record.kind)
    return true
  }

  const forgetOld = (kind) => {
    const ended = [...jobs.values()].filter((job) => job.kind === kind && !ACTIVE.has(job.status))
    if (ended.length <= KEEP_ENDED) return
    ended.sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
    for (const job of ended.slice(KEEP_ENDED)) jobs.delete(job.id)
  }

  const store = {
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    get: (id) => jobs.get(id) ?? null,
    list: () => list,
    /** The newest queued/running job of `kind`, or null. */
    active: (kind) => list.find((job) => job.kind === kind && ACTIVE.has(job.status)) ?? null,
    /** The newest job of `kind` in any status, or null. */
    latest: (kind) => list.find((job) => job.kind === kind) ?? null,
    /** The newest job of `kind` that has ended, or null. */
    lastEnded: (kind) => list.find((job) => job.kind === kind && !ACTIVE.has(job.status)) ?? null,
    receive(record) {
      if (put(record)) notify()
    },
    /** Change a record locally (a seen flag the backend did not re-emit). */
    patch(id, fields) {
      const record = jobs.get(id)
      if (record && put({ ...record, ...fields }, true)) notify()
    },
    /**
     * Take the backend's list. A queued/running job of an earlier backend process
     * that the list leaves out died with that process without a record on disk
     * (a kind kept in memory only), so it ends here as interrupted, quietly.
     */
    async resync() {
      const reply = await fetchJobs()
      const records = reply?.jobs || []
      let changed = false
      for (const record of records) changed = put(record) || changed
      if (reply?.owner) {
        const listed = new Set(records.map((record) => record.id))
        for (const record of [...jobs.values()]) {
          if (!ACTIVE.has(record.status) || listed.has(record.id) || sameOwner(record.owner, reply.owner)) continue
          changed = put({ ...record, status: 'interrupted', seen: true }, true) || changed
        }
      }
      if (changed) notify()
    },
    async refresh(id) {
      const record = await fetchJob(id)
      if (record) store.receive(record)
      return store.get(id)
    },
  }
  return store
}
