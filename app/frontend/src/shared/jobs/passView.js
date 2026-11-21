/**
 * passView.js — what a screen shows of a counting pass: the replay scan, the
 * combo scan, deep stats (core/jobs.py records whose `extra` carries done /
 * total and the pass's own counters; the final counters are its `result`).
 * Pure, so `node --test` covers it.
 */
import { ACTIVE } from './jobStore.js'
import { explainAppControl } from '../lib/appControl.js'

const FAILED = new Set(['failed', 'interrupted'])

export const IDLE = Object.freeze({ id: null, running: false, done: 0, total: 0, error: null, endedAt: null })

export function passView(job) {
  if (!job) return IDLE
  const running = ACTIVE.has(job.status)
  const counts = running ? job.extra : { ...job.extra, ...job.result }
  return {
    ...counts,
    id: job.id,
    running,
    done: counts?.done || 0,
    total: counts?.total || 0,
    error: FAILED.has(job.status) ? (explainAppControl(job.error) || 'It stopped before finishing.') : null,
    endedAt: running ? null : job.ended_at ?? null,
  }
}

/** Whether `record` is an ended job, other than `handledId`, that ended at or
 * after `since` (seconds). */
export function endedAfter(record, since, handledId) {
  return !!record && !ACTIVE.has(record.status) && record.id !== handledId
    && (record.ended_at || 0) >= since
}
