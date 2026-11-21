import test from 'node:test'
import assert from 'node:assert/strict'
import { jobOutcome, jobPercent } from './jobOutcome.js'

test('a running or unknown job has no outcome yet', () => {
  assert.equal(jobOutcome(null), null)
  assert.equal(jobOutcome({ status: 'queued' }), null)
  assert.equal(jobOutcome({ status: 'running', progress: 0.5 }), null)
})

test('a done job hands over its result', () => {
  assert.deepEqual(jobOutcome({ status: 'done', result: { path: 'a.iso' } }),
    { ok: true, result: { path: 'a.iso' } })
  assert.deepEqual(jobOutcome({ status: 'done', result: null }), { ok: true, result: {} })
})

test('a failed job is an outcome with its error, not something to keep waiting on', () => {
  assert.deepEqual(jobOutcome({ status: 'failed', error: 'MexCLI failed' }),
    { ok: false, error: 'MexCLI failed' })
  assert.equal(jobOutcome({ status: 'failed' }).ok, false)
  assert.equal(jobOutcome({ status: 'cancelled' }).error, 'Cancelled.')
  assert.match(jobOutcome({ status: 'interrupted' }).error, /Nucleus closed/)
})

test('progress reads as a whole percent, or null for a job that has none', () => {
  assert.equal(jobPercent({ progress: 0.374 }), 37)
  assert.equal(jobPercent({ progress: null }), null)
  assert.equal(jobPercent(null), null)
})


test('interruption preserves its recovery error and progress keeps zero and one', () => {
  assert.deepEqual(jobOutcome({ status: 'interrupted', error: 'Old vault restored.' }),
    { ok: false, error: 'Old vault restored.' })
  assert.equal(jobOutcome({ status: 'failed' }).error, 'Something went wrong.')
  assert.equal(jobPercent({ progress: 0 }), 0)
  assert.equal(jobPercent({ progress: 1 }), 100)
  assert.equal(jobPercent({ progress: '0.5' }), null)
})
