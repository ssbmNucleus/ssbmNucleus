/**
 * cloudJobs.js — what the Cloud card shows of the cloud jobs (core/jobs.py,
 * tracker/cloud/vault_jobs.py): a running sync, the last upload's outcome, and
 * an automatic run that stopped. Pure, so `node --test` covers it.
 *
 * A `cloud_sync` record's params.mode is "upload" or "metadata" (the raw
 * chain's follow-up). Each keeps its own result, so a metadata pass never hides
 * the failures of the upload before it (F-E-12).
 */
import { ACTIVE } from '../../shared/jobs/jobStore.js'
import { passView } from '../../shared/jobs/passView.js'

export const SYNC_KIND = 'cloud_sync'
export const AUTORUN_KIND = 'cloud_autorun'

// A running sync whose counters have not moved for this long is called out as
// stalled. Longer than one slow batch, shorter than the 11-minute upload-quota
// wait it most often is.
export const STALL_S = 120

const FAILED = new Set(['failed', 'interrupted'])

// The reconcile runs before any upload and, after a Patreon sign-in, checks the
// whole library against the cloud. Its own label, so that minute or two never
// reads as "Uploading… 0 games".
const STAGE_LABEL = {
  reconcile: 'Checking what your cloud library already has',
  combos: 'Uploading combo details',
  conversions: 'Uploading combo details',
}

const modeOf = (job) => job.params?.mode || 'upload'
const ended = (job) => !ACTIVE.has(job.status)
const stopped = (job) => (FAILED.has(job.status) ? job.error || 'It stopped before finishing.' : null)

/** `jobs` is the store's list, newest first; `now` is in seconds. */
export function cloudView(jobs, now = Date.now() / 1000) {
  const syncs = jobs.filter((job) => job.kind === SYNC_KIND)
  const live = syncs.find((job) => ACTIVE.has(job.status)) || null
  const upload = syncs.find((job) => ended(job) && modeOf(job) === 'upload') || null
  const metadata = syncs.find((job) => ended(job) && modeOf(job) === 'metadata') || null
  const lastSync = syncs.find(ended) || null
  const autorun = jobs.find((job) => job.kind === AUTORUN_KIND) || null

  let phase = null
  if (live) {
    const x = live.extra || {}
    phase = {
      key: 'sync',
      label: STAGE_LABEL[x.stage] || 'Syncing to your cloud library',
      unit: 'games',
      stage: x.stage || null,
      done: x.done || 0,
      total: x.total || 0,
      failed: x.failed || 0,
      idle: Math.max(0, Math.floor(now - (x.progress_at || live.started_at || now))),
    }
  } else if (autorun && ACTIVE.has(autorun.status) && autorun.extra?.phase === 'refresh') {
    phase = { key: 'refresh', label: 'Refreshing combos in your cloud library', unit: '', done: 0, total: 0 }
  }

  const result = upload?.status === 'done' ? {
    pushed: upload.result?.pushed || 0,
    skipped: upload.result?.skipped || 0,
    failed: upload.result?.failed || 0,
    // a later metadata pass adds only its own failures, said as its own
    metadataFailed: metadata?.status === 'done' && (metadata.created_at || 0) > (upload.created_at || 0)
      ? metadata.result?.failed || 0 : 0,
  } : null

  return {
    running: !!live,
    phase,
    result,
    error: lastSync ? stopped(lastSync) : null,
    autorunError: autorun ? stopped(autorun) : null,
  }
}


/** The launch chain's displayed phase: indexing, combos, then cloud work. */
export function cloudPhase(cloud, scanJob, comboJob) {
  if (scanJob) {
    const v = passView(scanJob)
    return { key: 'scan', label: 'Finding new replays', unit: 'files',
      done: v.done, total: v.total, failed: v.failed }
  }
  if (comboJob) {
    const v = passView(comboJob)
    return { key: 'combos', label: 'Finding combos', unit: 'games',
      done: v.done, total: v.total, failed: v.failed }
  }
  return cloud.phase
}

/** Refetch counts at a stage change or every hundred uploaded games. */
export function cloudStatusStep(cloud) {
  return cloud.phase?.key === 'sync' ? `${cloud.phase.stage}:${Math.floor(cloud.phase.done / 100)}` : null
}
