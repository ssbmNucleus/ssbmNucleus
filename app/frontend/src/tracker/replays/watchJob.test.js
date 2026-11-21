import { test } from 'node:test'
import assert from 'node:assert/strict'

import { createJobStore } from '../../shared/jobs/jobStore.js'
import { STARTING, WATCH_KIND, currentWatch, popupPart, watchFailed, watchView } from './watchJob.js'

const owner = { pid: 1, created: 1 }
const watch = (fields) => ({ kind: WATCH_KIND, owner, params: {}, extra: {}, seq: 1, ...fields })

test('a running watch shows its step, capture session and options', () => {
  const view = watchView(watch({
    id: 'w1', status: 'running', detail: 'Playing',
    params: { widescreen: true, batch_total: 3 },
    extra: { phase: 'playing', capture_session_id: 's1', recordings: ['a.mp4'] },
  }))
  assert.equal(view.state, 'playing')
  assert.equal(view.busy, true)
  assert.equal(view.capture_session_id, 's1')
  assert.equal(view.widescreen, true)
  assert.equal(view.batch_total, 3)
  assert.deepEqual(view.recordings, ['a.mp4'])
  assert.equal(view.last_recording, 'a.mp4')
})

test('an ended watch shows its status and result, and no capture', () => {
  const view = watchView(watch({
    id: 'w1', status: 'done', extra: { phase: 'cleaning', capture_session_id: 's1' },
    result: { last_recording: 'b.mp4', recordings: ['b.mp4'] },
  }))
  assert.equal(view.state, 'done')
  assert.equal(view.busy, false)
  assert.equal(view.capture_session_id, null)
  assert.equal(view.last_recording, 'b.mp4')
})

test('the popup is busy from the Start click until its job record arrives', () => {
  const old = watch({ id: 'w0', status: 'done', created_at: 1 })
  assert.equal(currentWatch({ jobs: [old], pending: true }), STARTING)
  // the response came back before the record: still starting, not the old watch
  assert.equal(currentWatch({ jobs: [old], startedId: 'w1' }), STARTING)
  const fresh = watch({ id: 'w1', status: 'queued', created_at: 2 })
  assert.equal(currentWatch({ jobs: [fresh, old], startedId: 'w1' }).id, 'w1')
})

test('a reopened popup finds the watch that is still running', () => {
  const running = watch({ id: 'w2', status: 'running', extra: { phase: 'exporting' } })
  const view = currentWatch({ jobs: [running, { id: 'r1', kind: 'vault_restore', status: 'running' }] })
  assert.equal(view.id, 'w2')
  assert.equal(view.busy, true)
  assert.equal(currentWatch({ jobs: [] }), null)
})

test('an older record never replaces a newer watch', () => {
  const store = createJobStore({ fetchJobs: async () => [], fetchJob: async () => null })
  store.receive(watch({ id: 'a', status: 'running', seq: 5, created_at: 1 }))
  store.receive(watch({ id: 'a', status: 'done', seq: 9, created_at: 1 }))
  store.receive(watch({ id: 'b', status: 'running', seq: 12, created_at: 2, extra: { phase: 'playing' } }))
  // a late copy of watch a, from before it ended
  store.receive(watch({ id: 'a', status: 'running', seq: 7, created_at: 1 }))
  assert.equal(store.get('a').status, 'done')
  const view = currentWatch({ jobs: store.list(), startedId: 'b' })
  assert.equal(view.id, 'b')
  assert.equal(view.state, 'playing')
})

test('a failure shows until the user has seen it', () => {
  const failed = watchView(watch({ id: 'w', status: 'failed', error: 'boom' }))
  assert.equal(watchFailed(failed), true)
  assert.equal(watchFailed({ ...failed, seen: true }), false)
  assert.equal(watchFailed(watchView(watch({ id: 'w', status: 'interrupted' }))), true)
  assert.equal(watchFailed(watchView(watch({ id: 'w', status: 'cancelled' }))), false)
  assert.equal(watchFailed(null), false)
})

test('options that failed to load show their error, not an empty popup', () => {
  assert.equal(popupPart({ options: null, error: null, job: null }), 'loading')
  assert.equal(popupPart({ options: null, error: 'Backend unavailable', job: null }), 'load-error')
  assert.equal(popupPart({ options: {}, error: 'start failed', job: null }), 'form')
  // a running or failed watch still comes first
  assert.equal(popupPart({ options: null, error: 'Backend unavailable', job: STARTING }), 'watch')
  const failed = watchView(watch({ id: 'w', status: 'failed', error: 'boom' }))
  assert.equal(popupPart({ options: null, error: 'Backend unavailable', job: failed }), 'failed')
  assert.equal(popupPart({ options: null, error: 'Backend unavailable',
    job: { ...failed, seen: true } }), 'load-error')
})


test('queued watches show defaults; a terminal result wins over intermediate recordings and relinquishes capture', () => {
  const queued = watchView(watch({ id: 'q', status: 'queued' }))
  assert.equal(queued.busy, true); assert.equal(queued.state, 'starting'); assert.equal(queued.detail, 'Starting…')
  const failed = watchView(watch({ id: 'w', status: 'failed', error: 'Dolphin crashed',
    extra: { recordings: ['partial.mp4'], capture_session_id: 'stale' }, result: { recordings: [], last_recording: null } }))
  assert.deepEqual(failed.recordings, []); assert.equal(failed.capture_session_id, null)
  assert.equal(failed.error, 'Dolphin crashed'); assert.equal(failed.last_recording, null)
})
