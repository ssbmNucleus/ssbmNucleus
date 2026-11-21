import test from 'node:test'
import assert from 'node:assert/strict'
import { createLatestRequest } from './latestRequest.js'

test('Stats filter changes preserve only the newest query and its completion', async () => {
  const pending = [], data = [], loading = [], errors = []
  const loader = createLatestRequest({
    request: (url, options) => new Promise((resolve, reject) => pending.push({ url, options, resolve, reject })),
    onData: (value, filters) => data.push([value, filters]),
    onLoading: value => loading.push(value), onError: value => errors.push(value),
  })
  const old = loader.load('/stats', '')
  loader.cancel() // filter effect cleanup before its debounce
  const next = loader.load('/stats?my_char=2', 'my_char=2')
  assert.equal(pending[0].options.signal.aborted, true)
  pending[0].resolve({ overview: { games: 900 } })
  await old
  assert.deepEqual(data, [])
  assert.deepEqual(loading, [true, true])
  pending[1].resolve({ overview: { games: 30 } })
  await next
  assert.deepEqual(data, [[{ overview: { games: 30 } }, 'my_char=2']])
  assert.deepEqual(loading, [true, true, false])
  assert.deepEqual(errors, ['', ''])
})

test('Stats failure is retryable and does not replace existing results with an empty library', async () => {
  let fail = true
  const data = [], errors = []
  const loader = createLatestRequest({
    request: async () => { if (fail) throw Error('Backend unreachable'); return { overview: { games: 12 } } },
    onData: value => data.push(value), onLoading() {}, onError: value => errors.push(value),
  })
  await loader.load('/stats')
  assert.deepEqual(data, [])
  assert.equal(errors.at(-1), 'Backend unreachable')
  fail = false
  await loader.load('/stats')
  assert.equal(data[0].overview.games, 12)
  assert.equal(errors.at(-1), '')
})
