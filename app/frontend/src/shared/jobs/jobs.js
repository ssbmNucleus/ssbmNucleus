/**
 * jobs.js — the one job store for the window, wired to the shared socket and
 * the /api/jobs routes. Screens use the hooks in useJobs.js; this file is the
 * plumbing.
 */
import api from '../transport/api'
import { subscribe } from '../transport/socket'
import { createJobStore } from './jobStore'

export const jobStore = createJobStore({
  fetchJobs: async () => {
    const reply = await api.get('/api/jobs')
    return { jobs: reply.jobs || [], owner: reply.owner }
  },
  fetchJob: async (id) => {
    try {
      return (await api.get(`/api/jobs/${encodeURIComponent(id)}`)).job
    } catch (err) {
      if (err?.status === 404) return null
      throw err
    }
  },
})

let started = false

/** Listen for `job` events and resync on every (re)connect. Safe to call often. */
export function startJobStore() {
  if (started) return
  started = true
  subscribe({
    job: (record) => jobStore.receive(record),
    connect: () => { jobStore.resync().catch(() => {}) },
  })
}

/** Ask the backend for one job now (a job this window just started). */
export function refreshJob(id) {
  return jobStore.refresh(id)
}

export function cancelJob(id) {
  return api.post(`/api/jobs/${encodeURIComponent(id)}/cancel`)
}

export async function markJobSeen(id) {
  await api.post(`/api/jobs/${encodeURIComponent(id)}/seen`)
  jobStore.patch(id, { seen: true })
}
