import test from 'node:test'
import assert from 'node:assert/strict'
import { cloudView, STALL_S } from './cloudJobs.js'

let created = 0
const job = (fields) => ({ kind: 'cloud_sync', status: 'done', params: { mode: 'upload' },
                           extra: {}, created_at: ++created, ...fields })
// the store's order: newest first
const newestFirst = (...jobs) => [...jobs].sort((a, b) => b.created_at - a.created_at)

test('nothing ran: idle, no result, no error', () => {
  assert.deepEqual(cloudView([]), { running: false, phase: null, result: null, error: null, autorunError: null })
})

test('a running sync shows its stage and counts', () => {
  const view = cloudView([job({ status: 'running', started_at: 100,
                                extra: { stage: 'reconcile', done: 7000, total: 19128, progress_at: 150 } })], 160)
  assert.equal(view.running, true)
  assert.equal(view.phase.label, 'Checking what your cloud library already has')
  assert.deepEqual([view.phase.done, view.phase.total, view.phase.idle], [7000, 19128, 10])
})

test('a sync whose counters stopped moving reads as stalled', () => {
  const view = cloudView([job({ status: 'running', started_at: 0, extra: { stage: 'upload', progress_at: 1000 } })],
                         1000 + STALL_S + 5)
  assert.ok(view.phase.idle >= STALL_S)
})

test('a metadata pass after a partly failed upload keeps the upload failures (F-E-12)', () => {
  const upload = job({ result: { mode: 'upload', pushed: 9, skipped: 2, failed: 1 } })
  const metadata = job({ params: { mode: 'metadata' }, result: { mode: 'metadata', committed: 9, failed: 0 } })
  const view = cloudView(newestFirst(upload, metadata))
  assert.deepEqual(view.result, { pushed: 9, skipped: 2, failed: 1, metadataFailed: 0 })
})

test('a metadata pass with its own failures says so beside the upload', () => {
  const upload = job({ result: { pushed: 9, skipped: 0, failed: 0 } })
  const metadata = job({ params: { mode: 'metadata' }, result: { committed: 7, failed: 2 } })
  assert.equal(cloudView(newestFirst(upload, metadata)).result.metadataFailed, 2)
})

test('the newest ended sync that failed is the error; a later success clears it', () => {
  const failed = job({ status: 'failed', error: 'invalid_token' })
  assert.equal(cloudView([failed]).error, 'invalid_token')
  const later = job({ result: { pushed: 1, skipped: 0, failed: 0 } })
  assert.equal(cloudView(newestFirst(failed, later)).error, null)
})

test('a cancelled sync (an account change) is not an error', () => {
  assert.equal(cloudView([job({ status: 'cancelled' })]).error, null)
})

test('an automatic run that stopped says why', () => {
  const autorun = job({ kind: 'cloud_autorun', status: 'failed', error: 'Finding combos was still running after 6 hours' })
  assert.match(cloudView([autorun]).autorunError, /still running/)
})

test('the slow wire-basis refresh shows while the chain runs it', () => {
  const autorun = job({ kind: 'cloud_autorun', status: 'running', extra: { phase: 'refresh' } })
  assert.equal(cloudView([autorun]).phase.key, 'refresh')
})


test('queued syncs are busy, unrelated jobs are ignored, and idle time is bounded and advances without events', () => {
  const queued = job({ status: 'queued', started_at: 100, extra: { stage: 'combos', failed: 2 } })
  const jobs = [{ kind: 'replay_watch', status: 'running' }, queued]
  const first = cloudView(jobs, 99)
  assert.equal(first.running, true); assert.equal(first.phase.idle, 0)
  assert.equal(first.phase.label, 'Uploading combo details'); assert.equal(first.phase.failed, 2)
  assert.equal(cloudView(jobs, 100 + STALL_S).phase.idle, STALL_S)
  assert.equal(cloudView([job({ status: 'queued' })], 500).phase.idle, 0)
})

test('only metadata newer than a successful upload contributes metadata failures', () => {
  const old = job({ params: { mode: 'metadata' }, result: { failed: 5 } })
  const upload = job({ result: {} })
  assert.deepEqual(cloudView(newestFirst(old, upload)).result, { pushed: 0, skipped: 0, failed: 0, metadataFailed: 0 })
  const failed = job({ status: 'failed', params: { mode: 'metadata' }, error: 'metadata refused', result: { failed: 9 } })
  const view = cloudView(newestFirst(old, upload, failed))
  assert.equal(view.result.metadataFailed, 0); assert.equal(view.error, 'metadata refused')
  assert.equal(cloudView([failed]).result, null)
  assert.equal(cloudView([job({ status: 'failed', result: { pushed: 1 } })]).result, null)
})

test('a live sync takes precedence over autorun refresh, and interruptions keep useful errors', () => {
  const auto = job({ kind: 'cloud_autorun', status: 'running', extra: { phase: 'refresh' } })
  const sync = job({ status: 'running', extra: { stage: 'conversions', done: 7, total: 10 } })
  assert.equal(cloudView(newestFirst(auto, sync)).phase.key, 'sync')
  assert.equal(cloudView([sync]).phase.label, 'Uploading combo details')
  assert.equal(cloudView([{ ...auto, status: 'done' }]).phase, null)
  assert.equal(cloudView([job({ status: 'interrupted' })]).error, 'It stopped before finishing.')
  assert.equal(cloudView([{ ...auto, status: 'interrupted', error: 'backend stopped' }]).autorunError, 'backend stopped')
})


test('the Cloud card shows scan before combos before upload, and refetches at stage/count boundaries', async () => {
  const { cloudPhase, cloudStatusStep } = await import('./cloudJobs.js')
  const sync = { phase: { key: 'sync', stage: 'upload', done: 99 } }
  const scan = job({ status: 'running', extra: { done: 2, total: 7, failed: 1 } })
  const combo = job({ status: 'queued', extra: { done: 0, total: 9 } })
  assert.deepEqual(cloudPhase(sync, scan, combo), { key: 'scan', label: 'Finding new replays', unit: 'files', done: 2, total: 7, failed: 1 })
  assert.equal(cloudPhase(sync, null, combo).key, 'combos')
  assert.equal(cloudPhase(sync, null, null), sync.phase)
  assert.equal(cloudStatusStep(sync), 'upload:0')
  assert.equal(cloudStatusStep({ phase: { ...sync.phase, done: 100 } }), 'upload:1')
  assert.equal(cloudStatusStep({ phase: { ...sync.phase, stage: 'combos' } }), 'combos:0')
  assert.equal(cloudStatusStep({ phase: { key: 'refresh' } }), null)
  assert.equal(cloudStatusStep({ phase: null }), null)
})
