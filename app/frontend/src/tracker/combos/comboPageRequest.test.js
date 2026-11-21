import assert from 'node:assert/strict'
import test from 'node:test'
import { createComboPageRequest } from './comboPageRequest.js'

function harness() {
  const pending = []
  const events = []
  const loader = createComboPageRequest({
    request: (url, { signal }) => new Promise((resolve, reject) => pending.push({ url, signal, resolve, reject })),
    onData: (data, page) => events.push(['data', data, page]),
    onLoading: value => events.push(['loading', value]),
    onError: value => events.push(['error', value]),
    onSettled: () => events.push(['settled']),
  })
  return { loader, pending, events }
}

test('first page is published before secondary metadata is enabled', async () => {
  const { loader, pending, events } = harness()
  const load = loader.load('/combos', 0)
  pending[0].resolve({ combos: [1], total: 1 })
  await load
  assert.deepEqual(events.slice(2), [
    ['data', { combos: [1], total: 1 }, 0], ['loading', false], ['settled'],
  ])
})

test('a replaced filter request cannot overwrite newer results or finish their loading state', async () => {
  const { loader, pending, events } = harness()
  const old = loader.load('/old', 3)
  const current = loader.load('/new', 0)
  assert.equal(pending[0].signal.aborted, true)
  pending[0].resolve({ combos: ['stale'] })
  await old
  assert.equal(events.some(event => event[0] === 'data' || event[0] === 'settled'), false)
  pending[1].resolve({ combos: ['current'] })
  await current
  assert.deepEqual(events.find(event => event[0] === 'data'), ['data', { combos: ['current'] }, 0])
})

test('errors are visible and the same page can be retried', async () => {
  const { loader, pending, events } = harness()
  const first = loader.load('/combos', 2)
  pending[0].reject(new Error('Backend unreachable'))
  await first
  assert.ok(events.some(event => event[0] === 'error' && event[1] === 'Backend unreachable'))
  const retry = loader.load('/combos', 2)
  pending[1].resolve({ combos: [] })
  await retry
  assert.deepEqual(events.find(event => event[0] === 'data'), ['data', { combos: [] }, 2])
})

test('unmount cancels pending work without updating the closed page', async () => {
  const { loader, pending, events } = harness()
  const load = loader.load('/combos', 0)
  loader.cancel()
  assert.equal(pending[0].signal.aborted, true)
  pending[0].reject(new Error('late failure'))
  await load
  assert.deepEqual(events, [['loading', true], ['error', '']])
})
