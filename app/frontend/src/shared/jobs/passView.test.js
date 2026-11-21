import test from 'node:test'
import assert from 'node:assert/strict'
import { endedAfter, IDLE, passView } from './passView.js'

const scan = (fields) => ({ id: 's', kind: 'replay_scan', status: 'running', extra: {}, ...fields })

test('a running pass shows its live counters', () => {
  const view = passView(scan({ extra: { done: 5, total: 20, found: 3 } }))
  assert.deepEqual([view.running, view.done, view.total, view.found, view.error], [true, 5, 20, 3, null])
})

test('an ended pass shows its result and when it ended', () => {
  const view = passView(scan({ status: 'done', ended_at: 9, extra: { done: 19, total: 20 }, result: { done: 20, total: 20, added: 4 } }))
  assert.deepEqual([view.running, view.done, view.added, view.endedAt], [false, 20, 4, 9])
})

test('a pass that failed before counting anything still says why', () => {
  const view = passView(scan({ status: 'failed', error: 'unable to open database file', ended_at: 3 }))
  assert.equal(view.running, false)
  assert.equal(view.error, 'unable to open database file')
  assert.equal(passView(null), IDLE)
})

test('only a job that ended after the screen mounted, once, counts as ending', () => {
  const ended = scan({ status: 'done', ended_at: 10 })
  assert.equal(endedAfter(ended, 5, null), true)
  assert.equal(endedAfter(ended, 11, null), false)
  assert.equal(endedAfter(ended, 5, 's'), false)
  assert.equal(endedAfter(scan({ ended_at: null }), 0, null), false)
  assert.equal(endedAfter(null, 0, null), false)
})


test('queued counters cannot borrow results, and result counters override live counters only after ending', () => {
  const queued = passView(scan({ status: 'queued', result: { done: 99, total: 99 }, ended_at: 7 }))
  assert.deepEqual([queued.running, queued.done, queued.total, queued.endedAt], [true, 0, 0, null])
  const ended = passView(scan({ status: 'done', extra: { done: 8, total: 10, found: 3 }, result: { done: 0 } }))
  assert.deepEqual([ended.done, ended.total, ended.found], [0, 10, 3])
})

test('interrupted passes report a fallback, while cancellations have no error', () => {
  assert.equal(passView(scan({ status: 'interrupted' })).error, 'It stopped before finishing.')
  assert.equal(passView(scan({ status: 'cancelled', error: 'cancelled' })).error, null)
  assert.equal(endedAfter(scan({ status: 'cancelled', ended_at: 10 }), 10, null), true)
  assert.equal(endedAfter(scan({ status: 'queued', ended_at: 10 }), 10, null), false)
})
