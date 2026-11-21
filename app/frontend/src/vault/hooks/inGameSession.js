import { ACTIVE } from '../../shared/jobs/jobStore.js'

export const IN_GAME_SESSION_KEY = 'nucleus:interactive-test-session'
export const initialTestState = () => ({ testingInGame: false, testStatus: null,
  testResult: null, testError: null, testMode: null, stoppingTest: false, stopError: null })
const owners = new Map()

// Lifecycle without React: one live UI owner, scoped events and resumable Stop.
// An automated capture is an `ingame` job (core/jobs.py) whose id is chosen
// here and followed in the window's job store (`jobs`: get/subscribe/refresh),
// so a lost response or a dropped socket still reaches its result.
export function createInGameSession({ api, channel, jobs, onState, readPaths,
  randomId = () => crypto.randomUUID(), storage, playSound = () => {},
  setTimer = setTimeout, clearTimer = clearTimeout, ownerRegistry = owners }) {
  let alive = false, current = null, state = initialTestState()
  const owner = {}
  const publish = patch => { state = { ...state, ...patch }; if (alive) onState(state) }
  const savedId = () => { try { return storage?.getItem(IN_GAME_SESSION_KEY) } catch { return null } }
  const save = id => { try { storage?.setItem(IN_GAME_SESSION_KEY, id) } catch { /* optional recovery */ } }
  const forget = id => { try { if (savedId() === id) storage?.removeItem(IN_GAME_SESSION_KEY) } catch { /* optional */ } }
  const active = op => alive && current === op && !op.finished

  function detach(op) {
    op.socket?.disconnect()
    op.unsubscribe?.()
    for (const request of op.requests) { request.controller.abort(); clearTimer(request.timer) }
    if (op.timer != null) clearTimer(op.timer)
    if (ownerRegistry.get(op.id) === owner) ownerRegistry.delete(op.id)
  }
  async function bounded(op, request) {
    const controller = new AbortController()
    const pending = { controller, timer: setTimer(() => controller.abort(), 10000) }
    op.requests.add(pending)
    try { return await request(controller.signal) }
    finally { clearTimer(pending.timer); op.requests.delete(pending) }
  }
  function finish(op, patch, sound) {
    if (!active(op)) return
    op.finished = true
    detach(op)
    if (op.interactive) forget(op.id)
    publish({ testingInGame: false, stoppingTest: false, stopError: null, ...patch })
    if (sound) playSound(sound)
  }
  // An interactive session's scoped test_* event.
  function event(op, name, data) {
    if (!active(op) || data?.sessionId !== op.id) return
    if (Number.isInteger(data.sequence)) {
      if (data.sequence <= op.sequence) return
      op.sequence = data.sequence
    }
    op.revision++
    if (name === 'test_progress') publish({ testStatus: data, testError: null })
    else if (name === 'test_error') finish(op, { testError: data.error || 'Test failed' }, 'error')
    else finish(op, { testResult: data, testError: null })
  }
  // A capture's job record, from the store.
  function follow(op) {
    const record = jobs.get(op.id)
    if (!record || !active(op)) return
    if (ACTIVE.has(record.status)) {
      publish({ testStatus: { stage: record.extra?.stage || 'starting',
        percentage: Math.round((record.progress || 0) * 100), message: record.detail || '' }, testError: null })
    } else if (record.status === 'done') {
      const data = record.result || {}
      finish(op, { testResult: op.result ? op.result(data) : data, testError: null },
        data.success === false ? 'error' : 'achievement')
    } else {
      finish(op, { testError: record.error || 'Capture failed' }, 'error')
    }
  }
  function schedule(op) {
    if (!active(op) || !op.accepted || op.timer != null) return
    op.timer = setTimer(() => { op.timer = null; recover(op) }, 5000)
  }
  async function recover(op) {
    if (!active(op) || !op.accepted) return null
    if (op.recovering) return op.recovering
    const revision = op.revision
    op.recovering = bounded(op, signal => api.get('/test-in-game/status', {
      query: { sessionId: op.id }, signal,
    })).then(snapshot => {
      if (!active(op) || revision !== op.revision || snapshot.sessionId !== op.id) return snapshot
      if (state.testError) publish({ testError: null })
      if (snapshot.stopRequested) { op.stopRequested = true; publish({ stoppingTest: true, stopError: null }) }
      const last = snapshot.lastEvent
      if (Number.isInteger(last?.payload?.sequence) && last.payload.sequence <= op.sequence) return snapshot
      if (last && ['test_progress', 'test_complete', 'test_error'].includes(last.event)) {
        event(op, last.event, last.payload)
      } else if (snapshot.running && snapshot.status) {
        publish({ testStatus: snapshot.status, testError: null })
      }
      if (active(op) && !snapshot.running) {
        // An unknown UUID is not proof that a lost start POST cannot arrive.
        // Keep its control until the backend acknowledges cancellation.
        publish({ testError: 'This session has not been found. Retry Stop to cancel a pending start, or wait for it to reconnect.' })
      }
      return snapshot
    }).catch(error => {
      if (active(op)) {
        publish({ testError: 'Connection to the test was interrupted. Reconnecting; you can retry Stop.' })
      }
      return null
    }).finally(() => { op.recovering = null; schedule(op) })
    return op.recovering
  }
  function attach(id, interactive, { accepted = false, result } = {}) {
    if (interactive && ownerRegistry.has(id) && ownerRegistry.get(id) !== owner) return null
    if (current) detach(current)
    const op = { id, interactive, accepted, result, revision: 0, sequence: -1, finished: false,
      stopRequested: false, requests: new Set() }
    current = op
    if (!interactive) {
      // Only this capture's job has this id.
      op.unsubscribe = jobs.subscribe(() => follow(op))
      return op
    }
    ownerRegistry.set(id, owner)
    op.socket = channel()
    for (const name of ['test_progress', 'test_complete', 'test_error']) {
      op.socket.on(name, data => event(op, name, data))
    }
    op.socket.on('connect', () => recover(op))
    return op
  }
  async function resume() {
    const id = savedId()
    if (!id || current && active(current)) return false
    const op = attach(id, true, { accepted: true })
    if (!op) return false
    publish({ ...initialTestState(), testingInGame: true, testMode: 'test',
      testStatus: { stage: 'recovering', message: 'Reconnecting to your in-game session…' } })
    await recover(op)
    return true
  }
  async function sendStop(op) {
    if (!active(op) || op.stopSending) return
    op.stopSending = true
    try {
      const response = await bounded(op, signal => api.post('/test-in-game/stop',
        { sessionId: op.id, cancelPending: true }, { signal }))
      op.stopAcknowledged = true
      if (active(op)) await recover(op)
      if (active(op) && response.running === false) finish(op, { testError: null,
        testResult: { interactive: true, success: true, verdict: 'stopped', reason: 'Session ended.' } })
    } catch (error) {
      if (active(op)) {
        op.stopRequested = false
        publish({ stoppingTest: false, stopError: `Could not stop the session: ${error.message}. Retry Stop.` })
      }
    } finally { op.stopSending = false }
  }
  async function start(endpoint, body, { interactive = true, result, message } = {}) {
    if (!alive || state.testingInGame) return
    if (savedId()) {
      if (await resume()) return
      if (ownerRegistry.has(savedId())) {
        publish({ testError: 'An in-game session is already open. Return to its test panel to stop it.' })
        return
      }
    }
    const { vanillaIsoPath, slippiDolphinPath } = readPaths()
    if (!vanillaIsoPath || !slippiDolphinPath) {
      publish({ testError: `No ${!vanillaIsoPath ? 'vanilla Melee ISO' : 'Slippi Dolphin'} path set. Set it in Settings first.` })
      return
    }
    const id = randomId()
    const op = attach(id, interactive, { result })
    if (!op) return
    if (interactive) save(id)
    publish({ ...initialTestState(), testingInGame: true, testMode: interactive ? 'test' : 'capture',
      testStatus: { stage: 'starting', percentage: 0, message: message || 'Starting in-game session…' } })
    playSound('start')
    try {
      const request = signal => api.post(endpoint, { ...body, vanillaIsoPath, slippiDolphinPath,
        ...(interactive ? { interactive: true, sessionId: id } : { jobId: id }) }, { signal })
      await (interactive ? bounded(op, request) : request())
      if (!active(op)) return
      op.accepted = true
      if (interactive) {
        if (op.stopRequested && !op.stopAcknowledged) await sendStop(op)
        else await recover(op)
      } else {
        follow(op)
        jobs.refresh(id).catch(() => {})
      }
    } catch (error) {
      if (!active(op)) return
      // A lost response may still have started the capture: ask for its job.
      if (!interactive && !error.status) {
        const record = await jobs.refresh(id).catch(() => null)
        if (!active(op)) return
        if (record) {
          op.accepted = true
          follow(op)
          return
        }
      }
      // Cancellation can win on the backend before the Stop HTTP reply arrives.
      // Its rejected kickoff must not turn a normal requested Stop into failure.
      if (interactive && op.stopRequested) {
        op.accepted = true
        await recover(op)
        return
      }
      // A lost HTTP response may still have started the backend session.
      if (interactive && !error.status) {
        op.accepted = true
        await recover(op)
        if (active(op) && op.stopRequested && !op.stopAcknowledged) await sendStop(op)
        return
      }
      finish(op, { testError: `Failed to start ${interactive ? 'test' : 'capture'}: ${error.message}` }, 'error')
    }
  }
  return {
    mount() { alive = true; resume() },
    unmount() { alive = false; if (current) detach(current); current = null },
    start,
    stop() {
      const op = current
      if (!op || !active(op) || !op.interactive || op.stopRequested) return
      op.stopRequested = true
      publish({ stoppingTest: true, stopError: null })
      return sendStop(op)
    },
    reset() {
      // Closing an editor neither stops nor loses the controls for a live test.
      if (current && active(current) && current.interactive) return
      if (current) detach(current)
      current = null
      publish(initialTestState())
    },
  }
}
