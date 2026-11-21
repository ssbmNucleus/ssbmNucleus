import test from 'node:test'
import assert from 'node:assert/strict'
import { discordAfterPollFailure } from './discordState.js'

test('a failed Discord poll preserves the exact pending attempt for retry (F-K-6)', () => {
  const pending = { account: null, auth: { state: 'pending', attempt: 'new' } }
  assert.equal(discordAfterPollFailure(pending), pending)
  for (const current of [null, {}, { auth: { state: 'failed' } }, { account: { user_id: 'a' }, auth: { state: 'idle' } }])
    assert.equal(discordAfterPollFailure(current), null)
})
