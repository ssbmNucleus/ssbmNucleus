import test from 'node:test'
import assert from 'node:assert/strict'
import { recoverFailedDownload } from './downloadQueueRecovery.js'

const failedState = (overrides = {}) => ({
  phase: 'error',
  recoveryAvailable: true,
  current: { name: 'failed' },
  pending: [{ name: 'next' }, { name: 'last' }],
  ...overrides
})

test('failed queue recovery returns the exact next work for retry, skip, and cancel', () => {
  const failed = { name: 'failed' }
  const pending = [{ name: 'next' }, { name: 'last' }]
  const state = failedState({ current: failed, pending })

  assert.deepEqual(recoverFailedDownload(state, 'retry'), { accepted: true, pending: [failed, ...pending] })
  assert.deepEqual(recoverFailedDownload(state, 'skip'), { accepted: true, pending })
  assert.deepEqual(recoverFailedDownload(state, 'cancel'), { accepted: true, pending: [] })
  assert.deepEqual(pending, [{ name: 'next' }, { name: 'last' }])
})

test('stale and repeated recovery actions cannot alter pending work', () => {
  const pending = [{ name: 'active-next' }]
  assert.deepEqual(
    recoverFailedDownload(failedState({ phase: 'downloading', pending }), 'retry'),
    { accepted: false, pending }
  )
  assert.deepEqual(
    recoverFailedDownload(failedState({ recoveryAvailable: false, pending }), 'skip'),
    { accepted: false, pending }
  )
})

test('last-item recovery remains bounded and invalid actions fail explicitly', () => {
  const state = failedState({ pending: [] })
  assert.deepEqual(recoverFailedDownload(state, 'retry'), {
    accepted: true,
    pending: [state.current]
  })
  assert.deepEqual(recoverFailedDownload(state, 'skip'), { accepted: true, pending: [] })
  assert.throws(() => recoverFailedDownload(state, 'unknown'), /Unknown download recovery action/)
})
