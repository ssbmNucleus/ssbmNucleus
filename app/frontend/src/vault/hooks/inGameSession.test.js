import test from 'node:test'
import assert from 'node:assert/strict'
import { createInGameSession, IN_GAME_SESSION_KEY } from './inGameSession.js'

const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function fixture({ store = new Map(), registry = new Map(), post, get, paths, refresh } = {}) {
  const states = [], posts = [], gets = [], sockets = [], timers = new Map()
  let id = 0, timerId = 0
  const f = { states, posts, gets, sockets, timers, store, registry,
    state: () => states.at(-1), snapshot: { running: true, status: { stage: 'building', message: 'Building' } } }
  // The window's job store: records by id, a listener per follower.
  const records = new Map(), listeners = new Set()
  f.jobs = { listeners, refreshes: [],
    get: id => records.get(id) ?? null,
    subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn) },
    receive: record => { records.set(record.id, record); for (const fn of [...listeners]) fn() },
    refresh: async id => {
      f.jobs.refreshes.push(id)
      const record = refresh ? refresh(id) : null
      if (record) f.jobs.receive(record)
      return records.get(id) ?? null
    } }
  f.session = createInGameSession({
    jobs: f.jobs,
    api: {
      post: async (url, body, options) => { posts.push({ url, body }); return post ? post(url, body, options) : { success: true } },
      get: async (url, options) => { gets.push({ url, options }); return get ? get(url, options) : { success: true, sessionId: options.query.sessionId, ...f.snapshot } },
    },
    channel: () => { const handlers = new Map(); const socket = { handlers, disconnected: false,
      on: (name, fn) => handlers.set(name, fn), disconnect() { this.disconnected = true },
      emit: (name, data) => handlers.get(name)?.(data) }; sockets.push(socket); return socket },
    onState: s => states.push(s), ownerRegistry: registry,
    storage: { getItem: key => store.get(key), setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) },
    readPaths: () => paths || { vanillaIsoPath: 'fixture.iso', slippiDolphinPath: 'fixture-dolphin' },
    randomId: () => `session-${++id}`,
    setTimer: (fn, ms) => { timers.set(++timerId, { fn, ms }); return timerId }, clearTimer: key => timers.delete(key),
  })
  f.session.mount()
  return f
}
const begin = f => f.session.start('/test-in-game/costume', { character: 'Fox', skinId: 'blue' })
const payload = (sequence, extra = {}) => ({ sessionId: 'session-1', sequence, ...extra })

test('interactive start sends identity, paths and client session UUID; listens before POST', async () => {
  const f = fixture({ post: () => { assert.equal(f.sockets.length, 1); return {} } })
  await begin(f)
  assert.deepEqual(f.posts[0].body, { character: 'Fox', skinId: 'blue', vanillaIsoPath: 'fixture.iso',
    slippiDolphinPath: 'fixture-dolphin', interactive: true, sessionId: 'session-1' })
  assert.equal(f.state().testMode, 'test'); assert.equal(f.store.get(IN_GAME_SESSION_KEY), 'session-1')
  f.session.unmount()
})

test('events must match the session and newer sequence; terminal cannot be overwritten', async () => {
  const f = fixture(); await begin(f); const socket = f.sockets[0]
  socket.emit('test_progress', payload(5, { stage: 'playing', controllerPort: 1 }))
  socket.emit('test_progress', payload(4, { stage: 'building' }))
  socket.emit('test_error', { sessionId: 'other', sequence: 6, error: 'unrelated' })
  assert.equal(f.state().testStatus.stage, 'playing')
  socket.emit('test_complete', payload(6, { interactive: true, success: true, verdict: 'stopped' }))
  socket.emit('test_progress', payload(7, { stage: 'building' }))
  assert.equal(f.state().testingInGame, false); assert.equal(f.state().testResult.verdict, 'stopped')
  assert.equal(f.store.has(IN_GAME_SESSION_KEY), false); assert.equal(f.timers.size, 0)
})

test('Stop during pending start cancels the same UUID immediately, including a queued kickoff', async () => {
  const request = deferred(); const f = fixture({ post: url => url.endsWith('/costume') ? request.promise : {} })
  const running = begin(f); await f.session.stop()
  assert.equal(f.posts.length, 2); assert.equal(f.state().stoppingTest, true)
  request.resolve({}); await running
  assert.deepEqual(f.posts[1], { url: '/test-in-game/stop', body: { sessionId: 'session-1', cancelPending: true } })
  assert.equal(f.state().testingInGame, true)
  assert.equal(f.posts.length, 2)
  f.session.unmount()
})

test('Stop failure preserves live controls and permits retry', async () => {
  let failed = false
  const f = fixture({ post: url => { if (url.endsWith('/stop') && !failed) { failed = true; throw new Error('offline') } return {} } })
  await begin(f); await f.session.stop()
  assert.equal(f.state().testingInGame, true); assert.equal(f.state().stoppingTest, false)
  assert.match(f.state().stopError, /Retry Stop/)
  await f.session.stop(); assert.equal(f.state().stoppingTest, true); assert.equal(f.state().stopError, null)
  f.session.unmount()
})

test('closing the UI detaches events without Stop; remount recovers a missed terminal', async () => {
  const first = fixture(); await begin(first); first.session.reset()
  assert.equal(first.state().testingInGame, true)
  first.session.unmount()
  assert.equal(first.posts.length, 1); assert.equal(first.sockets[0].disconnected, true)
  const next = fixture({ store: first.store, registry: first.registry,
    get: (_url, opts) => ({ success: true, running: false, sessionId: opts.query.sessionId,
      lastEvent: { event: 'test_complete', payload: payload(9, { interactive: true, success: true, verdict: 'closed' }) } }) })
  await flush()
  assert.equal(next.posts.length, 0); assert.equal(next.state().testResult.verdict, 'closed')
  assert.equal(next.store.has(IN_GAME_SESSION_KEY), false)
})

test('another mounted hook cannot steal session ownership or issue duplicate Stop', async () => {
  const first = fixture(); await begin(first)
  const other = fixture({ store: first.store, registry: first.registry }); await flush(); await other.session.stop()
  assert.equal(other.gets.length, 0); assert.equal(other.posts.length, 0)
  await begin(other); assert.match(other.state().testError, /already open/)
  first.session.unmount(); other.session.unmount()
})

test('old snapshot cannot regress playing after a newer live event', async () => {
  const response = deferred(); const f = fixture({ get: () => response.promise })
  const running = begin(f); await flush()
  f.sockets[0].emit('test_progress', payload(5, { stage: 'playing' }))
  response.resolve({ success: true, running: true, sessionId: 'session-1',
    lastEvent: { event: 'test_progress', payload: payload(4, { stage: 'building' }) } })
  await running; assert.equal(f.state().testStatus.stage, 'playing'); f.session.unmount()
})

test('reconnect and polling share one scoped status request and recover terminal', async () => {
  const f = fixture(); await begin(f)
  f.snapshot = { running: false, lastEvent: { event: 'test_complete', payload: payload(3, { interactive: true, success: true, verdict: 'stopped' }) } }
  f.sockets[0].emit('connect'); f.sockets[0].emit('connect'); await flush()
  assert.equal(f.gets.length, 2); assert.equal(f.state().testingInGame, false)
  assert.ok(f.gets.every(g => g.options.query.sessionId === 'session-1'))
})

test('unknown recovered session retains cancellation control until backend Stop acknowledgement', async () => {
  const f = fixture({ store: new Map([[IN_GAME_SESSION_KEY, 'expired']]),
    get: (_url, opts) => ({ success: true, running: false, sessionId: opts.query.sessionId, lastEvent: null }),
    post: () => ({ success: true, running: false }) })
  await flush(); assert.equal(f.state().testingInGame, true); assert.equal(f.store.size, 1); assert.equal(f.posts.length, 0)
  await f.session.stop(); assert.equal(f.state().testingInGame, false); assert.equal(f.store.size, 0)
})

test('a lost start response recovers running ownership instead of abandoning the backend session', async () => {
  const f = fixture({ post: () => { throw new Error('connection lost') } }); await begin(f)
  assert.equal(f.state().testingInGame, true); assert.equal(f.store.get(IN_GAME_SESSION_KEY), 'session-1')
  f.session.unmount()
})

test('an explicit preflight refusal releases local ownership and shows start error', async () => {
  const f = fixture({ post: () => { throw Object.assign(new Error('Close Dolphin'), { status: 409 }) } })
  await begin(f); assert.equal(f.state().testingInGame, false); assert.match(f.state().testError, /Close Dolphin/)
  assert.equal(f.registry.size, 0); assert.equal(f.store.size, 0)
})

test('an automated capture names its job, follows only that job, and never sends interactive or Stop', async () => {
  const f = fixture()
  await f.session.start('/test-in-game/capture-stage-screenshot', { variantId: 'blue' }, {
    interactive: false, result: d => ({ captured: true, success: true, screenshot: d.screenshot }) })
  assert.equal(f.posts[0].body.interactive, undefined); assert.equal(f.posts[0].body.sessionId, undefined)
  assert.equal(f.posts[0].body.jobId, 'session-1'); assert.equal(f.sockets.length, 0)
  assert.equal(f.state().testMode, 'capture'); await f.session.stop(); assert.equal(f.posts.length, 1)
  f.jobs.receive({ id: 'session-1', status: 'running', progress: 0.4, detail: 'Capturing', extra: { stage: 'capturing' } })
  assert.deepEqual(f.state().testStatus, { stage: 'capturing', percentage: 40, message: 'Capturing' })
  // Another capture's result cannot finish this one.
  f.jobs.receive({ id: 'other', status: 'done', result: { screenshot: 'other.png' } })
  assert.equal(f.state().testingInGame, true)
  f.jobs.receive({ id: 'session-1', status: 'done', result: { screenshot: 'fixture.png' } })
  assert.deepEqual(f.state().testResult, { captured: true, success: true, screenshot: 'fixture.png' })
  assert.equal(f.jobs.listeners.size, 0)
})

test('a capture whose events were missed gets its result from the job store, even after a lost start response', async () => {
  const f = fixture({ post: () => { throw new Error('connection reset') },
    refresh: id => ({ id, status: 'running', progress: 0, extra: {} }) })
  await f.session.start('/capture', {}, { interactive: false })
  assert.equal(f.state().testingInGame, true); assert.equal(f.state().testError, null)
  assert.deepEqual(f.jobs.refreshes, ['session-1'])
  // The socket was down when it ended; the store's resync on reconnect brings the record.
  f.jobs.receive({ id: 'session-1', status: 'failed', error: 'Dolphin closed' })
  assert.equal(f.state().testingInGame, false); assert.equal(f.state().testError, 'Dolphin closed')
})

test('a capture the backend never started shows the start failure', async () => {
  const f = fixture({ post: () => { throw new Error('connection refused') } })
  await f.session.start('/capture', {}, { interactive: false })
  assert.equal(f.state().testingInGame, false)
  assert.match(f.state().testError, /Failed to start capture: connection refused/)
})

test('late capture records after reset/unmount do not update state', async () => {
  const f = fixture(); await f.session.start('/capture', {}, { interactive: false })
  f.session.reset(); const count = f.states.length
  f.jobs.receive({ id: 'session-1', status: 'failed', error: 'late' }); assert.equal(f.states.length, count)
  f.session.unmount(); assert.equal(f.posts.length, 1)
})

test('missing configured paths never creates a session or request', async () => {
  const f = fixture({ paths: { vanillaIsoPath: null, slippiDolphinPath: 'fixture' } }); await begin(f)
  assert.match(f.state().testError, /Settings/); assert.equal(f.posts.length, 0); assert.equal(f.sockets.length, 0)
})

test('a healthy unchanged snapshot clears reconnect errors without clearing Stop errors', async () => {
  let fail = false
  const f = fixture({ get: (_url, opts) => {
    if (fail) throw new Error('offline')
    return { success: true, running: true, sessionId: opts.query.sessionId,
      lastEvent: { event: 'test_progress', payload: payload(4, { stage: 'playing' }) } }
  }, post: url => { if (url.endsWith('/stop')) throw new Error('stop failed'); return {} } })
  await begin(f); await f.session.stop(); assert.ok(f.state().stopError)
  fail = true; f.sockets[0].emit('connect'); await flush(); assert.ok(f.state().testError)
  fail = false; f.sockets[0].emit('connect'); await flush()
  assert.equal(f.state().testError, null); assert.ok(f.state().stopError); f.session.unmount()
})

test('remount restores an already requested Stop while the build finishes', async () => {
  const f = fixture({ store: new Map([[IN_GAME_SESSION_KEY, 'session-1']]),
    get: () => ({ success: true, sessionId: 'session-1', running: true, stopRequested: true,
      lastEvent: { event: 'test_progress', payload: payload(3, { stage: 'building' }) } }) })
  await flush(); assert.equal(f.state().stoppingTest, true); await f.session.stop()
  assert.equal(f.posts.length, 0); f.session.unmount()
})

test('a timed-out Stop releases its busy state so the user can retry', async () => {
  const f = fixture({ post: (url, _body, opts) => url.endsWith('/stop')
    ? new Promise((_resolve, reject) => opts.signal.addEventListener('abort', () => reject(new DOMException('Timed out', 'AbortError')))) : {} })
  await begin(f); const stop = f.session.stop(); await flush()
  for (const [key, timer] of f.timers) if (timer.ms === 10000) { f.timers.delete(key); timer.fn() }
  await stop; assert.equal(f.state().stoppingTest, false); assert.equal(f.state().testingInGame, true)
  assert.match(f.state().stopError, /Retry Stop/); f.session.unmount()
})

test('lost startup plus unknown status remains cancellable, then terminal cancellation clears recovery', async () => {
  const f = fixture({ post: url => {
    if (!url.endsWith('/stop')) throw new Error('response lost')
    return { success: true, running: false }
  }, get: (_url, opts) => ({ success: true, running: false, sessionId: opts.query.sessionId, lastEvent: null }) })
  await begin(f); assert.equal(f.state().testingInGame, true); assert.equal(f.store.size, 1)
  await f.session.stop(); assert.equal(f.state().testResult.verdict, 'stopped'); assert.equal(f.store.size, 0)
})

test('a cancelled kickoff response before the Stop response cannot display a start failure', async () => {
  const kickoff = deferred(), stopping = deferred()
  const f = fixture({ post: url => url.endsWith('/stop') ? stopping.promise : kickoff.promise })
  const running = begin(f), stop = f.session.stop()
  kickoff.reject(Object.assign(new Error('Session cancelled'), { status: 409 })); await running
  assert.equal(f.state().testingInGame, true); assert.equal(f.state().testError, null)
  f.snapshot = { running: false, lastEvent: { event: 'test_complete', payload: payload(7,
    { interactive: true, success: true, verdict: 'stopped', reason: 'Cancelled before launch.' }) } }
  stopping.resolve({ success: true, running: false }); await stop
  assert.equal(f.state().testResult.verdict, 'stopped'); assert.equal(f.state().testError, null)
})


test('capture completion before the start reply is final and does not schedule a refresh', async () => {
  const reply = deferred(), f = fixture({ post: () => reply.promise })
  const starting = f.session.start('/capture', {}, { interactive: false })
  f.jobs.receive({ id: 'session-1', status: 'done', result: { screenshot: 'early.png' } })
  const count = f.states.length
  reply.resolve({}); await starting
  assert.equal(f.state().testResult.screenshot, 'early.png')
  assert.equal(f.states.length, count); assert.deepEqual(f.jobs.refreshes, [])
  assert.equal(f.jobs.listeners.size, 0); f.session.unmount()
})

test('all non-success capture endings release the follower and a refused start is not recovered as accepted', async () => {
  for (const status of ['failed', 'cancelled', 'interrupted']) {
    const f = fixture(); await f.session.start('/capture', {}, { interactive: false })
    f.jobs.receive({ id: 'session-1', status })
    assert.equal(f.state().testingInGame, false); assert.equal(f.state().testError, 'Capture failed')
    assert.equal(f.jobs.listeners.size, 0); f.session.unmount()
  }
  const f = fixture({ post: () => { throw Object.assign(new Error('busy'), { status: 409 }) } })
  await f.session.start('/capture', {}, { interactive: false })
  assert.match(f.state().testError, /Failed to start capture: busy/)
  assert.deepEqual(f.jobs.refreshes, []); assert.equal(f.jobs.listeners.size, 0); f.session.unmount()
})

test('unmount during a lost-response recovery cannot publish the returned capture', async () => {
  const reply = deferred(), f = fixture({ post: () => { throw new Error('offline') } })
  f.jobs.refresh = () => reply.promise
  const starting = f.session.start('/capture', {}, { interactive: false })
  await flush(); f.session.unmount(); const count = f.states.length
  reply.resolve({ id: 'session-1', status: 'done' }); await starting
  assert.equal(f.states.length, count); assert.equal(f.jobs.listeners.size, 0)
})
