import test from 'node:test'
import assert from 'node:assert/strict'
import { resolvePaintSource, launchPaintViewerSession, viewerErrorMessage } from './viewerSession.js'

test('a viewer too old to load a stage says to update Nucleus', () => {
  // The viewer output bug report 17401c50 (0.8.15, Linux) got back from viewer:start.
  const error = new Error("Error invoking remote method 'viewer:start': Error: hsdrawviewer exited during startup\n"
    + 'Streaming server error: No JOBJ found in DAT file')
  assert.match(viewerErrorMessage(error, true), /^This viewer could not load the stage model\. Update Nucleus/)
  assert.match(viewerErrorMessage(new Error('An Application Control policy has blocked this file. (0x800711C7)')),
    /^Windows Smart App Control blocked/)
})

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('closing during source fetch never resolves pose or launches a viewer', async () => {
  const source = deferred()
  let current = true
  let poses = 0
  const result = resolvePaintSource(() => source.promise, () => { poses++; return null }, () => current)
  current = false
  source.resolve({ datFile: 'popo.dat' })
  assert.equal(await result, null)
  assert.equal(poses, 0)
})

test('a newer source selection supersedes pending pose resolution', async () => {
  const pose = deferred()
  let current = true
  const result = resolvePaintSource(async () => ({ datFile: 'popo.dat' }), () => pose.promise, () => current)
  await Promise.resolve()
  current = false
  pose.resolve({ sceneFile: 'popo.scene' })
  assert.equal(await result, null)
})

test('close during viewer startup discards late ready/export and startup completion', async () => {
  const started = deferred()
  let current = true, listener, subscribed = false, cleaned = 0
  const messages = []
  const result = launchPaintViewerSession({
    electron: {
      onViewerMessage(callback) { listener = callback; return () => { cleaned++ } },
      viewerStart: () => started.promise
    },
    paths: { datFile: 'popo.dat' },
    onMessage: message => messages.push(message),
    onSubscribe: () => { subscribed = true },
    isCurrent: () => current
  })
  assert.equal(subscribed, true)
  current = false
  listener({ type: 'ready' })
  listener({ type: 'exportDat', data: 'old-popo' })
  started.resolve({ streaming: true })
  assert.equal(await result, null)
  assert.deepEqual(messages, [])
  assert.equal(cleaned, 1)
})

test('active viewer forwards messages and reports errors, closing suppresses stale failures', async () => {
  const options = {
    electron: { onViewerMessage: () => () => {}, viewerStart: async () => { throw new Error('start failed') } },
    paths: {}, onMessage() {}, onSubscribe() {}, isCurrent: () => true
  }
  await assert.rejects(launchPaintViewerSession(options), /start failed/)
  assert.equal(await launchPaintViewerSession({ ...options, isCurrent: () => false }), null)
})

test('manager session tags reject an old viewer even when the new subscription is active', async () => {
  let listener
  const messages = []
  await launchPaintViewerSession({
    electron: {
      onViewerMessage(callback) { listener = callback; return () => {} },
      viewerStart: async () => ({ streaming: true })
    },
    paths: { viewerSessionId: 'new-viewer' }, onMessage: message => messages.push(message),
    onSubscribe() {}, isCurrent: () => true
  })
  listener({ type: 'ready', viewerSessionId: 'old-viewer' })
  listener({ type: 'disconnected', viewerSessionId: 'old-viewer' })
  listener({ type: 'ready', viewerSessionId: 'new-viewer' })
  listener({ type: 'legacy' })
  assert.deepEqual(messages.map(message => message.type), ['ready'])
})

test('subscribes to frames before start and settles an early owned frame before canvas mount', async () => {
  let frameListener, messageListener, cleanup
  const consumed = [], messages = [], removed = []
  await launchPaintViewerSession({ electron: {
    onViewerMessage(callback) { messageListener = callback; return () => removed.push('messages') },
    onViewerFrame(callback) { frameListener = callback; return () => removed.push('frames') },
    viewerFrameConsumed: metadata => consumed.push(metadata),
    async viewerStart(paths) {
      messageListener({ type: 'ready', viewerSessionId: paths.viewerSessionId })
      frameListener('jpeg', { viewerSessionId: paths.viewerSessionId, frameId: 1 })
      frameListener('foreign', { viewerSessionId: 'old', frameId: 2 })
      return { connected: true, streaming: true }
    }
  }, paths: { viewerSessionId: 'active' }, onMessage: message => messages.push(message.type),
  onSubscribe: value => { cleanup = value }, isCurrent: () => true, getCanvas: () => null })
  assert.deepEqual(consumed, [{ viewerSessionId: 'active', frameId: 1 }])
  assert.deepEqual(messages, ['ready'])
  cleanup(); cleanup()
  messageListener({ type: 'ready', viewerSessionId: 'active' })
  assert.deepEqual(messages, ['ready'])
  assert.deepEqual(removed, ['frames', 'messages'])
})

test('closing while startup is pending stops only its session when the start eventually resolves', async () => {
  const started = deferred(), stopped = []
  let cleanup
  const result = launchPaintViewerSession({ electron: {
    onViewerMessage: () => () => {}, viewerStart: () => started.promise,
    viewerStop: sessionId => stopped.push(sessionId)
  }, paths: { viewerSessionId: 'closed' }, isCurrent: () => true, onMessage() {},
  onSubscribe: value => { cleanup = value } })
  cleanup()
  started.resolve({ connected: true, streaming: true })
  assert.equal(await result, null)
  assert.deepEqual(stopped, ['closed'])
})

test('missing frame acknowledgement bridge reports an actionable error and cleans up', async () => {
  let removed = 0
  const stopped = []
  await assert.rejects(launchPaintViewerSession({ electron: {
    onViewerMessage: () => () => { removed++ }, onViewerFrame: () => () => { removed++ },
    viewerStart: async () => ({ streaming: true, connected: true }), viewerStop: id => stopped.push(id)
  }, paths: { viewerSessionId: 'needs-host-update' }, onMessage() {}, onSubscribe() {},
  isCurrent: () => true, getCanvas: () => null }), /viewerFrameConsumed.*Update the viewer host/)
  assert.equal(removed, 2)
  assert.deepEqual(stopped, ['needs-host-update'])
})
