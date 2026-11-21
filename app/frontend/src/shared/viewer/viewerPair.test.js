import test from 'node:test'
import assert from 'node:assert/strict'
import { launchPreviewSession, previewPairMembers } from './viewerPair.js'

const members = [{ memberId: 'popo', datFile: 'popo.dat', ajFile: 'popo-aj.dat' },
  { memberId: 'nana', datFile: 'custom-nana.dat', ajFile: 'nana-aj.dat' }]

function fixture() {
  let listener, cleanup, current = true
  const messages = [], sent = [], stopped = []
  const options = {
    paths: { viewerSessionId: 'viewer-1', datFile: 'custom-nana.dat', members },
    isCurrent: () => current, onSubscribe: value => { cleanup = value },
    onMessage: message => messages.push(message),
    electron: {
      onViewerMessage: callback => { listener = callback; return () => {} },
      viewerStart: async () => ({ connected: true, streaming: false }),
      viewerSend: async command => { sent.push(command); return true },
      viewerStop: async id => { stopped.push(id) }
    }
  }
  return { options, messages, sent, stopped,
    emit: message => listener({ viewerSessionId: 'viewer-1', ...message }),
    close: () => { current = false; cleanup() } }
}

test('pair paths are complete, independent, and keep each animation archive', () => {
  assert.deepEqual(previewPairMembers({ members }).map(m => [m.memberId, m.datFile, m.ajFile]), members.map(m => [m.memberId, m.datFile, m.ajFile]))
  assert.equal(previewPairMembers({ datFile: 'fox.dat' }), null)
  assert.throws(() => previewPairMembers({ members: members.slice(0, 1) }), /both/)
  assert.throws(() => previewPairMembers({ members: [members[0], members[0]] }), /both/)
})

test('early ready sends exactly one pair load, preserves Nana selection, waits for correlated acknowledgement', async () => {
  const f = fixture()
  const pending = launchPreviewSession(f.options)
  let complete = false
  pending.then(() => { complete = true })
  f.emit({ type: 'ready' }); f.emit({ type: 'ready' })
  await Promise.resolve()
  assert.equal(f.sent.length, 1)
  assert.equal(f.sent[0].primaryMemberId, 'nana')
  assert.deepEqual(f.sent[0].members.map(m => m.datFile), ['popo.dat', 'custom-nana.dat'])
  assert.equal(complete, false)
  assert.equal(f.messages.length, 0)
  f.emit({ type: 'paintPairLoaded', success: true, sessionId: 'old', requestId: 'old' })
  assert.equal(f.messages.length, 0)
  f.emit({ ...f.sent[0], type: 'paintPairLoaded', success: true })
  assert.equal((await pending).connected, true)
  assert.equal(f.messages[0].type, 'ready')
})

test('failed pair load stops its own viewer instead of displaying a lone climber', async () => {
  const f = fixture()
  const pending = launchPreviewSession(f.options)
  f.emit({ type: 'ready' })
  f.emit({ ...f.sent[0], type: 'paintPairLoaded', success: false, error: 'Nana model invalid' })
  await assert.rejects(pending, /Nana model invalid/)
  assert.deepEqual(f.stopped, ['viewer-1'])
})

test('closing while pair is loading cancels the wait and ignores a late reply', async () => {
  const f = fixture()
  const pending = launchPreviewSession(f.options)
  f.emit({ type: 'ready' })
  f.close()
  f.emit({ ...f.sent[0], type: 'paintPairLoaded', success: true })
  assert.equal(await pending, null)
  assert.deepEqual(f.messages, [])
})

test('non-IC viewer uses the ordinary startup with no pair command', async () => {
  const f = fixture()
  delete f.options.paths.members
  const pending = launchPreviewSession(f.options)
  f.emit({ type: 'ready' })
  assert.equal((await pending).connected, true)
  assert.equal(f.sent.length, 0)
  assert.equal(f.messages[0].type, 'ready')
})


test('connected host without a ready event cannot leave pair startup waiting forever', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const f = fixture()
  const pending = launchPreviewSession(f.options)
  const rejected = assert.rejects(pending, /timed out/)
  await Promise.resolve()
  t.mock.timers.tick(30000)
  await rejected
  assert.deepEqual(f.stopped, ['viewer-1'])
  assert.deepEqual(f.sent, [])
})
