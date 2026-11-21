import assert from 'node:assert/strict'
import test from 'node:test'
import { sendGate } from './sending.js'

const idle = { uploading: false, loadingChat: false, ready: true, changingInput: false, busy: false, replying: false }

test('the panel sends a typed message now, queues it while Randall works, and drops it while it cannot', () => {
  assert.equal(sendGate({ ...idle, text: 'import this' }), 'send')
  assert.equal(sendGate({ ...idle, text: '   ' }), null)
  assert.equal(sendGate({ ...idle, text: 'x', busy: true, replying: true }), 'queue', 'typed while Randall works')
  for (const blocked of [{ uploading: true }, { loadingChat: true }, { ready: false }, { changingInput: true }]) {
    assert.equal(sendGate({ ...idle, ...blocked, text: 'x' }), null, JSON.stringify(blocked))
  }
  // A queued message starts while the panel is still busy with the turn it waited on, once that reply is closed.
  const queued = { id: 'q1', content: 'x' }
  assert.equal(sendGate({ ...idle, text: 'x', busy: true, queued }), 'send')
  assert.equal(sendGate({ ...idle, text: 'x', busy: true, replying: true, queued }), null)
})

test('a failed old send restores an empty draft and preserves a newer draft exactly (F-D-4)', async () => {
  const { restoreFailedDraft } = await import('./sending.js')
  assert.equal(restoreFailedDraft('', 'first message'), 'first message')
  assert.equal(restoreFailedDraft(' \n\t', 'first message'), 'first message')
  assert.equal(restoreFailedDraft('  new message \n', 'first message'), '  new message \n')
})
