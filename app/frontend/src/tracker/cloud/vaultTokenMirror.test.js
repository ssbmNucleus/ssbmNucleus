import test from 'node:test'
import assert from 'node:assert/strict'
import { createVaultTokenMirror } from './vaultTokenMirror.js'

function fixture({ token = 'tok', entitlement = { linked: true, active: true, source: 'patreon' }, post,
                   pending = false } = {}) {
  const state = { token, pending }
  const posts = []
  const mirror = createVaultTokenMirror({
    getToken: () => state.token,
    checkEntitlement: async () => {
      if (entitlement instanceof Error) throw entitlement
      return typeof entitlement === 'function' ? entitlement(state) : entitlement
    },
    post: post || (async (body) => { posts.push(body) }),
    signOutPending: () => state.pending,
    clearSignOutPending: () => { state.pending = false },
  })
  return { state, posts, mirror }
}

test('a sign-out whose clear never landed is sent again, once (F-E-5)', async () => {
  const f = fixture({ token: '', pending: true })
  await f.mirror()
  await f.mirror()
  assert.deepEqual(f.posts, [{ token: null }])
  assert.equal(f.state.pending, false)
})

test('a clear that fails again stays pending for the next try', async () => {
  const f = fixture({ token: '', pending: true, post: async () => { throw new Error('backend down') } })
  await f.mirror()
  assert.equal(f.state.pending, true)
})

test('a stored token reaches the backend with the pledge', async () => {
  const f = fixture()
  await f.mirror()
  assert.deepEqual(f.posts, [{ token: 'tok', active: true }])
})

test('no token sends nothing: a window without one never signs the backend out', async () => {
  const f = fixture({ token: '' })
  await f.mirror()
  assert.deepEqual(f.posts, [])
})

test('a failed entitlement check still sends the token but not a pledge', async () => {
  const f = fixture({ entitlement: new Error('offline') })
  await f.mirror()
  assert.deepEqual(f.posts, [{ token: 'tok' }])
})

test('a lapsed pledge is mirrored as false', async () => {
  const f = fixture({ entitlement: { linked: true, active: false } })
  await f.mirror()
  assert.deepEqual(f.posts, [{ token: 'tok', active: false }])
})

test('AI free mode is not a pledge: a $0 member stays unpaid for the upload', async () => {
  const f = fixture({ entitlement: { linked: true, active: true, source: 'free', membership_class: 'free' } })
  await f.mirror()
  assert.deepEqual(f.posts, [{ token: 'tok', active: false }])
})

test('AI paused with no word on the pledge leaves the stored one alone', async () => {
  const f = fixture({ entitlement: { linked: true, active: false, paused: true, membership_class: 'none', patron_status: 'former_patron' } })
  await f.mirror()
  assert.deepEqual(f.posts, [{ token: 'tok' }])
})

test('AI paused is not a lapse: a paying patron keeps the upload', async () => {
  const f = fixture({ entitlement: { linked: true, active: false, paused: true, membership_class: 'paid' } })
  await f.mirror()
  assert.deepEqual(f.posts, [{ token: 'tok', active: true }])
})

test('a token signed out during the check (invalid_token) is not resent', async () => {
  const f = fixture({
    entitlement: (state) => { state.token = ''; return { linked: false, active: false } },
  })
  await f.mirror()
  assert.deepEqual(f.posts, [])
})

test('a backend that refuses the post does not throw out of the mirror', async () => {
  const f = fixture({ post: async () => { throw new Error('HTTP 404') } })
  await f.mirror()
})
