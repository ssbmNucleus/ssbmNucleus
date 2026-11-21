import test from 'node:test'
import assert from 'node:assert/strict'
import { nextAccount, pairedPhoneState } from './cloudAccount.js'

test('the same token keeps the account', () => {
  const account = { token: 'a', epoch: 3 }
  assert.equal(nextAccount(account, 'a'), account)
})

test('a second Patreon linked over the first is a new account (F-E-4)', () => {
  assert.deepEqual(nextAccount({ token: 'a', epoch: 3 }, 'b'), { token: 'b', epoch: 4 })
})

test('signing out is a new account too', () => {
  const signedOut = nextAccount({ token: 'a', epoch: 0 }, '')
  assert.deepEqual(signedOut, { token: null, epoch: 1 })
  assert.equal(nextAccount(signedOut, ''), signedOut)
})

test('a fresh code waits for its phone to reach the list', () => {
  assert.equal(pairedPhoneState(7, [{ id: 1 }], false), 'waiting')
  assert.equal(pairedPhoneState(7, [{ id: 1 }, { id: 7 }], false), 'listed')
})

test('revoking the phone just paired takes its code down (F-E-11)', () => {
  assert.equal(pairedPhoneState(7, [{ id: 1 }], true), 'revoked')
})


test('an unissued pairing id cannot be mistaken for a revoked phone, and another phone cannot keep the QR alive', () => {
  assert.equal(pairedPhoneState(null, [{ id: 2 }], true), 'waiting')
  assert.equal(pairedPhoneState(1, [{ id: 2 }], true), 'revoked')
  assert.equal(pairedPhoneState(1, [{ id: 1 }], true), 'listed')
})
