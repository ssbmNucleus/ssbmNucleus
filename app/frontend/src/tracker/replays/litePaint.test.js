import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'
import { deferred } from '../../../../../tests/frontend/hookHarness.mjs'

// The same Node adapters used by the existing paint tests, with a controllable API.
register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { api } = await import('liteaudit:api')
const { getCharmaps } = await import('./litePaint.js')

test('the painter forgets a failed charmap request, coalesces callers, then caches recovery (F-J-9)', async t => {
  const requests = []
  t.mock.method(api, 'get', path => {
    assert.equal(path, '/api/nucleome/lite/charmaps')
    const reply = deferred(); requests.push(reply); return reply.promise
  })
  const first = getCharmaps(), concurrent = getCharmaps()
  assert.equal(first, concurrent); assert.equal(requests.length, 1)
  requests[0].reject(new Error('restarting'))
  await assert.rejects(first, /restarting/)
  const retried = getCharmaps(); assert.notEqual(retried, first); assert.equal(requests.length, 2)
  const charmaps = { chars: { 7: { animationMap: {} } } }
  requests[1].resolve(charmaps)
  assert.deepEqual(await retried, charmaps)
  assert.equal(getCharmaps(), retried); assert.equal(requests.length, 2)
})
