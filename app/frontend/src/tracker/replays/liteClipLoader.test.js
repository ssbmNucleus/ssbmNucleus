import test from 'node:test'
import assert from 'node:assert/strict'
import { deriveFromSlp } from './liteDeriver/index.js'

// The existing transport reads Electron configuration at import time.
const oldWindow = globalThis.window
globalThis.window = { location: { search: '' }, electron: { backendToken: 'synthetic-test-token' } }
const helpers = await import('./liteClipLoader.js')
const { BACKEND_URL, BACKEND_TOKEN } = await import('../../shared/config/config.js')
if (oldWindow === undefined) delete globalThis.window
else globalThis.window = oldWindow
const { narrowAnimations, mergeConversions, pythonDeriverEnabled } = helpers

const cm = {
  actionNameById: ['Wait', 'AttackAirF', 'Fall', 'Missing'],
  chars: Object.fromEntries([1, 7, 11, 19].map(cid => [cid, {
    animationMap: { AttackAirF: 'Fair' }, specialsMap: { 1: 'WrongPrecedence', 341: 'SpecialN' },
  }])),
}
const full = { Wait: ['M0 0', 'M1 1'], Fair: ['M2 2'], Fall: ['M3 3'],
  SpecialN: ['M4 4'], Unused: ['M5 5'] }
function bundle() {
  return { meta: { v: 5, finalized: true, start_frame: 100, n: 4, players: [{}, {}] },
    frames: { cid: [[7, 19, 19, 7], [1, 1, 1, 1]], state: [[0, 1, 341, 3], [2, 2, 2, 2]],
      fol: [{ of: 0, cid: [null, 11, 11, null], state: [null, 0, 341, null] }] },
    conversions: {} }
}

test('animation narrowing shares renderer precedence, transforms and absent Nana handling', () => {
  const packs = Object.fromEntries([1, 7, 11, 19].map(cid => [cid, full]))
  assert.deepEqual(narrowAnimations(bundle(), cm, packs), {
    1: { Fall: full.Fall }, 7: { Wait: full.Wait },
    19: { Fair: full.Fair, SpecialN: full.SpecialN }, 11: { Wait: full.Wait, SpecialN: full.SpecialN },
  })
  assert.deepEqual(narrowAnimations(bundle(), cm, {}), { 1: {}, 7: {}, 11: {}, 19: {} })
  assert.equal(full.Unused[0], 'M5 5')
})

test('a star or screen KO keeps DamageFall, the pose it draws, though the replay never records it', () => {
  const names = []
  names[6] = 'DeadUpFall'; names[38] = 'DamageFall'; names[42] = 'Landing'
  const ko = { actionNameById: names, chars: { 15: { animationMap: {}, specialsMap: {} } } }
  const packs = { 15: { DamageFall: ['M6 6'], Landing: ['M7 7'] } }
  const b = (state) => ({ meta: { players: [{}] }, frames: { cid: [[15, 15]], state: [state] } })
  assert.deepEqual(narrowAnimations(b([42, 6]), ko, packs), { 15: packs[15] })
  assert.deepEqual(narrowAnimations(b([42, 42]), ko, packs), { 15: { Landing: packs[15].Landing } })
})

test('conversions overlap the actual padded window inclusively, keeping TRUE frames and evidence', () => {
  const source = bundle()
  const before = { start_frame: 90, end_frame: 99 }
  const enter = { start_frame: 95, end_frame: 100, evidence: { hits: 2 } }
  const leave = { start_frame: 103, end_frame: 110 }
  const after = { start_frame: 104, end_frame: 120 }
  const conversions = { 0: [before, enter, leave, after], 1: [] }
  const merged = mergeConversions(source, conversions)
  assert.deepEqual(merged.conversions, { 0: [enter, leave], 1: [] })
  assert.equal(merged.conversions[0][0], enter)
  assert.deepEqual(source.conversions, {})
  assert.equal(conversions[0].length, 4)
  source.meta.players.push({})
  assert.deepEqual(mergeConversions(source, conversions).conversions, {})
})

test('only the exact python override opts out, and unavailable storage is harmless', () => {
  for (const value of [null, '', 'js', 'Python', 'true']) {
    assert.equal(pythonDeriverEnabled({ getItem: () => value }), false)
  }
  assert.equal(pythonDeriverEnabled({ getItem: key => key === 'watchLite.deriver' ? 'python' : null }), true)
  assert.equal(pythonDeriverEnabled({ getItem: () => { throw new Error('blocked') } }), false)
})

const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
})
let moduleId = 0
async function setup(t, { workerBundle = bundle(), override = null, workerError, WorkerClass,
  slp = new Uint8Array([1, 2, 3]), respond } = {}) {
  const calls = [], workers = []
  class FakeWorker {
    constructor(url, options) {
      assert.ok(url.pathname.endsWith('/liteDeriver/worker.js'))
      assert.deepEqual(options, { type: 'module' })
      workers.push(this)
    }
    postMessage(message, transfer) {
      this.message = message
      assert.deepEqual(transfer, [message.bytes])
      queueMicrotask(() => this.onmessage({ data: workerError
        ? { error: workerError } : { bundle: workerBundle } }))
    }
    terminate() { this.terminated = true }
  }
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    const u = new URL(url)
    assert.equal(u.origin, BACKEND_URL)
    assert.ok(BACKEND_TOKEN)
    assert.equal(new Headers(init.headers).get('X-Nucleus-Token'), BACKEND_TOKEN)
    calls.push(u.pathname + u.search)
    const custom = respond?.(u)
    if (custom) return custom
    if (u.pathname.includes('/slp/')) return new Response(slp)
    if (u.pathname.endsWith('/resolve')) return json({ game_id: 8, start_frame: 100, end_frame: 103 })
    if (u.pathname.includes('/conversions/')) return json({ 0: [
      { start_frame: 80, end_frame: 99 }, { start_frame: 99, end_frame: 101 },
    ], 1: [] })
    if (u.pathname.endsWith('/charmaps')) return json(cm)
    if (u.pathname.includes('/pack/')) return json(full)
    if (/\/clip(?:\/|-ref\/|-share\/)/.test(u.pathname)) return json({ legacy: true })
    assert.fail(`Unexpected fetch: ${u.pathname}`)
  })
  const oldWorker = Object.getOwnPropertyDescriptor(globalThis, 'Worker')
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'Worker', { configurable: true, writable: true, value: WorkerClass || FakeWorker })
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => override } })
  t.after(() => {
    if (oldWorker) Object.defineProperty(globalThis, 'Worker', oldWorker)
    else delete globalThis.Worker
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage)
    else delete globalThis.localStorage
  })
  // A fresh loader keeps the per-view pack cache independent across tests.
  const { loadLiteClip } = await import(`./liteClipLoader.js?test=${++moduleId}`)
  return { loadLiteClip, calls, workers }
}

test('local game uses authenticated raw bytes, a worker, both forms and follower packs', async t => {
  const { loadLiteClip, calls, workers } = await setup(t)
  const result = await loadLiteClip({ gameId: 8, start: 100, end: 103 })
  assert.equal(result.bundle.meta.finalized, true)
  assert.deepEqual(result.bundle.conversions, { 0: [{ start_frame: 99, end_frame: 101 }], 1: [] })
  assert.equal(result.available, true)
  assert.deepEqual(result.anim[19], { Fair: full.Fair, SpecialN: full.SpecialN })
  assert.deepEqual(workers[0].message.options, { start: 100, end: 103 })
  assert.equal(workers[0].message.bytes.byteLength, 3)
  assert.equal(workers[0].terminated, true)
  for (const cid of [1, 7, 11, 19]) assert.ok(calls.includes(`/api/nucleome/lite/pack/${cid}`))
  assert.ok(calls.includes('/api/nucleome/lite/conversions/8?conversions=1'))
  assert.equal(calls.some(path => path.includes('/clip/')), false)
  await loadLiteClip({ gameId: 8 })
  assert.deepEqual(workers[1].message.options, {})
  assert.equal(calls.filter(path => path.includes('/pack/')).length, 4)
})

test('minted refs resolve before requesting raw bytes with the resolved window', async t => {
  const { loadLiteClip, calls, workers } = await setup(t)
  await loadLiteClip({ clipRef: 'c123', gameId: 999, start: 1, end: 2 })
  assert.equal(calls[0], '/api/nucleome/lite/clip-ref/c123/resolve')
  assert.ok(calls.includes('/api/nucleome/lite/slp/8'))
  assert.deepEqual(workers[0].message.options, { start: 100, end: 103 })
})

test('a recovered ref with null bounds loads an uncapped whole game', async t => {
  const { loadLiteClip, workers } = await setup(t, { respond: u => u.pathname.endsWith('/resolve')
    ? json({ game_id: 8, start_frame: null, end_frame: null }) : null })
  await loadLiteClip({ clipRef: 'c123' })
  assert.deepEqual(workers[0].message.options, {})
})

test('the Python override preserves legacy game and ref routes', async t => {
  const { loadLiteClip, calls, workers } = await setup(t, { override: 'python' })
  assert.deepEqual(await loadLiteClip({ gameId: 8, start: -10, end: 50 }), { legacy: true })
  await loadLiteClip({ clipRef: 'c123' })
  assert.deepEqual(calls, ['/api/nucleome/lite/clip/8?start=-10&end=50', '/api/nucleome/lite/clip-ref/c123'])
  assert.equal(workers.length, 0)
})

test('missing packs and a failed conversions parse still permit dot playback', async t => {
  const { loadLiteClip } = await setup(t, { respond: u => /\/(pack|conversions)\//.test(u.pathname)
    ? json({ error: 'unavailable' }, 404) : null })
  const result = await loadLiteClip({ gameId: 8 })
  assert.equal(result.available, false)
  assert.deepEqual(result.bundle.conversions, {})
})

test('a failed charmaps request is asked again', async t => {
  let fail = true
  const { calls } = await setup(t, { respond: u => u.pathname.endsWith('/charmaps') && fail
    ? json({ error: 'backend restarting' }, 503) : null })
  const { getCharmaps } = await import(`./liteClipLoader.js?test=${moduleId}`)
  await assert.rejects(getCharmaps(), /backend restarting/)
  fail = false
  assert.deepEqual(await getCharmaps(), cm)
  assert.deepEqual(await getCharmaps(), cm)
  assert.equal(calls.filter(path => path.endsWith('/charmaps')).length, 2)
})

test('missing charmaps permit playback without fetching geometry', async t => {
  const { loadLiteClip, calls } = await setup(t, { respond: u => u.pathname.endsWith('/charmaps')
    ? json({ error: 'missing' }, 404) : null })
  const result = await loadLiteClip({ gameId: 8 })
  assert.deepEqual(result.anim, {})
  assert.equal(result.available, false)
  assert.equal(calls.some(path => path.includes('/pack/')), false)
})

test('worker parse errors surface and terminate the worker', async t => {
  const { loadLiteClip, workers } = await setup(t, { workerError: { name: 'SlpError', message: 'bad header' } })
  await assert.rejects(loadLiteClip({ gameId: 8 }), { name: 'SlpError', message: 'bad header' })
  assert.equal(workers[0].terminated, true)
})

test('missing raw files do not create a worker or fetch packs', async t => {
  const { loadLiteClip, calls, workers } = await setup(t, { respond: u => u.pathname.includes('/slp/')
    ? json({ error: 'game not found' }, 404) : null })
  await assert.rejects(loadLiteClip({ gameId: 8 }), /404/)
  assert.equal(workers.length, 0)
  assert.equal(calls.some(path => path.includes('/pack/')), false)
})

// Two frames with a rollback emission; fabricated, never a user's replay.
function syntheticSlp() {
  const table = new Uint8Array([0x35, 7, 0x36, 0x01, 0x40, 0x38, 0, 0x54])
  const start = new Uint8Array(0x141)
  start.set([0x36, 3, 0, 0])
  new DataView(start.buffer).setUint16(0x13, 31)
  for (let p = 0; p < 4; p++) {
    start[0x65 + p * 0x24] = 2
    start[0x66 + p * 0x24] = p < 2 ? 0 : 3
  }
  const parts = [table, start]
  for (const [frame, x] of [[-123, 999], [-123, 1.5], [-122, 2.5]]) {
    for (const port of [0, 1]) {
      const post = new Uint8Array(0x55), view = new DataView(post.buffer)
      post[0] = 0x38; view.setInt32(1, frame); post[5] = port; post[7] = 1
      view.setUint16(8, 0); view.setFloat32(0xA, x); view.setFloat32(0x12, 1)
      parts.push(post)
    }
  }
  const size = parts.reduce((n, part) => n + part.length, 0)
  const bytes = new Uint8Array(15 + size)
  bytes.set([123, 85, 3, 114, 97, 119, 91, 36, 85, 35, 108])
  new DataView(bytes.buffer).setInt32(11, size)
  let offset = 15
  for (const part of parts) { bytes.set(part, offset); offset += part.length }
  return bytes
}

test('Worker construction failure falls back to real main-thread derivation', async t => {
  class BlockedWorker { constructor() { throw new Error('CSP denied') } }
  const { loadLiteClip, workers } = await setup(t, { WorkerClass: BlockedWorker, slp: syntheticSlp() })
  const { bundle: b } = await loadLiteClip({ gameId: 8 })
  assert.equal(b.meta.v, 5)
  assert.equal(b.meta.finalized, true)
  assert.equal(b.meta.n, 2)
  assert.equal(b.meta.start_frame, -123)
  assert.deepEqual(b.frames.x[0], [1.5, 2.5])
  assert.equal(workers.length, 0)
})

test('the actual worker wrapper derives v5 and serializes parse failures', async t => {
  const messages = [], oldSelf = globalThis.self
  globalThis.self = { postMessage: message => messages.push(message) }
  t.after(() => {
    if (oldSelf === undefined) delete globalThis.self
    else globalThis.self = oldSelf
  })
  await import('./liteDeriver/worker.js')
  const bytes = syntheticSlp()
  self.onmessage({ data: { bytes, options: {} } })
  assert.deepEqual(messages[0].bundle, deriveFromSlp(bytes))
  self.onmessage({ data: { bytes: new Uint8Array(), options: {} } })
  assert.equal(messages[1].error.name, 'SlpError')
})


test('a character pack absent before download is retried and then cached (F-J-8)', async t => {
  let missing = true
  const { calls, loadLiteClip } = await setup(t, { respond: u => u.pathname.endsWith('/pack/7') && missing
    ? json({ error: 'not downloaded' }, 404) : null })
  const first = await loadLiteClip({ gameId: 8, start: 100, end: 103 })
  assert.deepEqual(first.anim[7], {})
  missing = false
  const second = await loadLiteClip({ gameId: 8, start: 100, end: 103 })
  assert.ok(Object.keys(second.anim[7]).length > 0)
  await loadLiteClip({ gameId: 8, start: 100, end: 103 })
  assert.equal(calls.filter(path => path.endsWith('/pack/7')).length, 2)
})
