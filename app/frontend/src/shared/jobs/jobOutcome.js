/**
 * jobOutcome.js — what a job record means to a screen waiting on it.
 *
 *   jobOutcome(job)   null while it runs (or is not known yet), else
 *                     { ok: true, result } or { ok: false, error }
 *   jobPercent(job)   its progress as a whole percent, or null when it has none
 *
 * A failed job is an ordinary record with an error, never a failed request:
 * the screen shows the error and stops waiting.
 */
import { ACTIVE } from './jobStore.js'
import { explainAppControl } from '../lib/appControl.js'

export function jobOutcome(job) {
  if (!job || ACTIVE.has(job.status)) return null
  if (job.status === 'done') return { ok: true, result: job.result || {} }
  if (job.status === 'cancelled') return { ok: false, error: 'Cancelled.' }
  if (job.status === 'interrupted') {
    return { ok: false, error: explainAppControl(job.error) || 'Nucleus closed while this was running.' }
  }
  return { ok: false, error: explainAppControl(job.error) || 'Something went wrong.' }
}

export function jobPercent(job) {
  return typeof job?.progress === 'number' ? Math.round(job.progress * 100) : null
}
