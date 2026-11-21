import { ACTIVE } from '../shared/jobs/jobStore.js'

/** The restore's terminal message; a merge report or recovery copy prevents auto-reload. */
export function restoreOutcome(job) {
  if (!job || ACTIVE.has(job.status)) return null
  if (job.status === 'done') {
    const result = job.result || {}
    if (result.report) return { outcome: { message: result.message, report: result.report } }
    if (result.recovery_path) return { outcome: { message: result.message, recoveryPath: result.recovery_path } }
    return { outcome: { message: result.message || 'Done!', reloading: true } }
  }
  const text = job.status === 'failed' ? `Restore failed: ${job.error || 'Unknown error'}`
    : job.status === 'cancelled' ? 'Restore cancelled.'
      : 'The restore stopped when Nucleus closed. Check the Vault before starting another.'
  return { message: { text, type: 'error' } }
}

/** A backup's expiry timer owns only the message it created. */
export function clearBackupMessage(current, created) {
  return current === created ? { text: '', type: '' } : current
}
