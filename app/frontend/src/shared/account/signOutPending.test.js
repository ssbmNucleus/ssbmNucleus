import test from 'node:test'
import assert from 'node:assert/strict'
import { markSignOutPending, clearSignOutPending, signOutPending } from './signOutPending.js'

test('only an explicit pending marker owes a backend clear and it survives a new reader', () => {
  const values = new Map(), storage = {
    getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key),
  }
  assert.equal(signOutPending(storage), false)
  markSignOutPending(storage); assert.equal(signOutPending({ ...storage }), true)
  clearSignOutPending(storage); assert.equal(signOutPending(storage), false)
  storage.setItem('nucleus.patreon.signOutPending', 'false'); assert.equal(signOutPending(storage), false)
})

test('unavailable or full storage does not break sign out', () => {
  const storage = Object.fromEntries(['getItem', 'setItem', 'removeItem'].map(key => [key, () => { throw Error('blocked') }]))
  for (const value of [null, storage]) {
    assert.doesNotThrow(() => markSignOutPending(value))
    assert.doesNotThrow(() => clearSignOutPending(value))
    assert.equal(signOutPending(value), false)
  }
})
