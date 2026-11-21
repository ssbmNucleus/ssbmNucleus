import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule, deferred, flush } from '../../../../../tests/frontend/hookHarness.mjs'
import * as pending from './signOutPending.js'

function fixture() {
  const values = new Map(), posts = [], events = []
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const entitlement = loadModule(new URL('./entitlement.js', import.meta.url), {
    '../transport/api': { api: { post: (path, body) => { const reply = deferred(); posts.push({ path, body, ...reply }); return reply.promise } } },
    './signOutPending': {
      markSignOutPending: () => pending.markSignOutPending(storage),
      clearSignOutPending: () => pending.clearSignOutPending(storage),
    },
    './patreonLinkGuard': { startPatreonLink: () => 'synthetic-state' },
  }, { localStorage: storage, window: { dispatchEvent: event => events.push(event.type) } })
  return { ...entitlement, storage, posts, events, pending: () => pending.signOutPending(storage) }
}

test('sign out forgets identity and notifies immediately; a failed backend clear remains owed', async () => {
  const f = fixture(); f.setPatreonToken('old'); f.clearPatreonToken()
  assert.equal(f.getPatreonToken(), ''); assert.equal(f.pending(), true)
  assert.deepEqual(f.events, [f.ENTITLEMENT_EVENT, f.ENTITLEMENT_EVENT])
  assert.equal(f.posts[0].path, '/api/nucleome/vault/token'); assert.deepEqual(f.posts[0].body, { token: null })
  f.posts[0].reject(new Error('backend down')); await flush()
  assert.equal(f.pending(), true)
  assert.deepEqual(await f.getEntitlement(), { linked: false, active: false })
})

test('an acknowledged clear settles the debt; a new token clears it without waiting', async () => {
  const f = fixture(); f.setPatreonToken('old'); f.clearPatreonToken()
  f.posts[0].resolve({}); await flush(); assert.equal(f.pending(), false)
  f.clearPatreonToken(); assert.equal(f.pending(), true)
  f.setPatreonToken('new'); assert.equal(f.pending(), false); assert.equal(f.getPatreonToken(), 'new')
  // The old clear reply must not remove the replacement credential or a clear owed by its new owner.
  pending.markSignOutPending(f.storage)
  f.posts[1].resolve({}); await flush()
  assert.equal(f.getPatreonToken(), 'new'); assert.equal(f.pending(), true)
})
