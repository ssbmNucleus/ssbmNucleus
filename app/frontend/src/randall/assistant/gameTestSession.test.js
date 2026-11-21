import test from 'node:test'
import assert from 'node:assert/strict'
import { observeGameTest } from './gameTestSession.js'

const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve() }
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function fixture(options = {}) {
  const states = [], timers = new Map(); let id = 0, reads = 0, stops = 0
  const monitor = observeGameTest({
    read: async signal => { reads++; return options.read ? options.read(signal) : { running: true, status: { sequence: reads, stage: 'playing' } } },
    stop: async signal => { stops++; return options.stop?.(signal) },
    onState: patch => states.push(patch),
    setTimer: (fn, ms) => { timers.set(++id, { fn, ms }); return id },
    clearTimer: id => timers.delete(id),
  })
  return { states, timers, monitor, reads: () => reads, stops: () => stops }
}

test('opening a card only reads existing state and disposal never stops the game', async () => {
  const f = fixture(); await flush()
  assert.equal(f.reads(), 1); assert.equal(f.stops(), 0)
  assert.equal(f.states.at(-1).snapshot.status.stage, 'playing')
  f.monitor.dispose(); assert.equal(f.timers.size, 0); assert.equal(f.stops(), 0)
})

test('ended history stops polling and does not launch or stop anything', async () => {
  const f = fixture({ read: async () => ({ running: false, lastEvent: { event: 'test_complete', payload: { success: true } } }) })
  await flush(); assert.equal(f.timers.size, 0); assert.equal(f.stops(), 0)
  assert.equal(f.states.at(-1).snapshot.running, false); f.monitor.dispose()
})

test('Stop failure keeps controls and allows retry', async () => {
  let failed = false
  const f = fixture({ stop: () => { if (!failed) { failed = true; throw new Error('offline') } } })
  await flush(); await f.monitor.stop()
  assert.match(f.states.at(-1).stopError, /Retry Stop/)
  await f.monitor.stop(); assert.equal(f.stops(), 2); f.monitor.dispose()
})

test('status polling cannot enable a duplicate Stop while its request is pending', async () => {
  const pending = deferred()
  const f = fixture({ stop: () => pending.promise }); await flush()
  const stopping = f.monitor.stop()
  const poll = [...f.timers.values()].find(timer => timer.ms === 1000)
  await poll.fn(); await f.monitor.stop()
  assert.equal(f.stops(), 1); assert.equal(f.states.at(-1).stopping, true)
  pending.resolve(); await stopping; f.monitor.dispose()
})

test('late initial status cannot overwrite a stop result', async () => {
  const pending = deferred(); let reads = 0
  const f = fixture({ read: () => ++reads === 1 ? pending.promise : Promise.resolve({ running: false }) })
  await f.monitor.stop()
  pending.resolve({ running: true }); await flush()
  assert.equal(f.states.at(-1).snapshot.running, false); f.monitor.dispose()
})

test('disconnect retains recovery polling and explicit Stop', async () => {
  const f = fixture({ read: () => { throw new Error('offline') } })
  await flush(); assert.match(f.states.at(-1).error, /Reconnecting/)
  assert.ok([...f.timers.values()].some(t => t.ms === 1000))
  await f.monitor.stop(); assert.equal(f.stops(), 1); f.monitor.dispose()
})

test('unmounted cards ignore late state and abort the pending request', async () => {
  const pending = deferred(); let signal
  const f = fixture({ read: value => { signal = value; return pending.promise } })
  f.monitor.dispose(); pending.resolve({ running: true }); await flush()
  assert.equal(signal.aborted, true); assert.equal(f.states.length, 0); assert.equal(f.timers.size, 0)
})
