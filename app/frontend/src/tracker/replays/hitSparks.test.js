import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'
import { readFile } from 'node:fs/promises'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
// A stageData of its own (the hit table cache must start empty) and hitSparks
// bound to it, as stageData.test.js builds its fresh runtimes.
const fresh = new URL(`./stageData.js?hits=${Date.now()}`, import.meta.url).href
const sd = await import(fresh)
const source = (await readFile(new URL('./hitSparks.js', import.meta.url), 'utf8'))
  .replace(/from '(\.\/[^']+)'/g, (_, rel) => `from ${JSON.stringify(rel === './stageData.js' ? fresh : new URL(rel, import.meta.url).href)}`)
const { hitEvents, hitShake, drawHitSparks, shieldStun } = await import(`data:text/javascript,${encodeURIComponent(source)}`)
const { RecordingContext } = await import('../../../../../tools/liteaudit/recording_context.mjs')
const FX = (await import('./data/hitEffects.js')).default
sd.registerHitDataLoader(async id => JSON.parse(await readFile(new URL(`./data/hits/${id}.json`, import.meta.url), 'utf8')))

// Fox (internal 1) attacks Falco (22). Every channel is a function of the row index.
function bundle(n, rows) {
  const keys = ['cid', 'x', 'y', 'dir', 'state', 'age', 'pct', 'shield', 'hitlag', 'hitstun', 'hitby', 'air']
  const frames = Object.fromEntries(keys.map(k => [k, rows.map(r =>
    Array.from({ length: n }, (_, i) => (typeof r[k] === 'function' ? r[k](i) : r[k] ?? 0)))]))
  return { meta: { n, stage: 32, start_frame: 0 }, frames, items: [] }
}
const HIT = 5
const fox = (patch = {}) => ({ cid: 1, x: 0, y: 0, dir: 1, state: 44, age: 2, hitby: -1, ...patch })
const falco = (patch = {}) => ({ cid: 22, x: 12, y: 0, dir: -1, state: 14, pct: i => (i >= HIT ? 3 : 0),
  shield: 60, hitlag: i => (i === HIT ? 4 : 0), hitstun: i => (i === HIT ? 10 : 0), hitby: i => (i >= HIT ? 0 : -1), ...patch })

test('no sparks until every fighter table is in, then the hit is found and cached', async () => {
  const b = bundle(12, [fox(), falco()])
  assert.deepEqual(hitEvents(b), [])
  assert.equal(await sd.ensureReplayHitData(b), true)
  const events = hitEvents(b)
  assert.equal(events.length, 1)
  assert.equal(hitEvents(b), events)
  const [e] = events
  assert.equal(e.idx, HIT); assert.equal(e.victim, 1); assert.equal(e.kind, 'normal')
  // 3 damage: 0.3 + 0.04 x 3 (ftColl_80078538)
  assert.ok(Math.abs(e.scale - 0.42) < 1e-9)
  // from the jab hitbox nearest Falco's middle (6, 9) r 3.3 toward (12, 8), half its radius
  assert.ok(Math.hypot(e.x - 6, e.y - 9) <= 1.65 + 1e-6 && e.x > 6, `${e.x}, ${e.y}`)
})

test('the element picks the effect; hard hits, throws and shields have their own rule', async () => {
  const strong = bundle(12, [fox(), falco({ hitstun: i => (i === HIT ? 80 : 0) })])
  const shine = bundle(12, [fox({ state: 360, age: 1 }), falco()])
  const thrown = bundle(12, [fox({ state: 219, age: 15 }), falco({ state: i => (i < HIT ? 239 : 88) })])
  const shield = bundle(12, [fox(), falco({ pct: 0, state: i => (i < HIT ? 179 : 181), shield: i => (i < HIT ? 60 : 55) })])
  const big = bundle(12, [fox(), falco({ pct: i => (i >= HIT ? 40 : 0) })])
  for (const b of [strong, shine, thrown, shield, big]) await sd.ensureReplayHitData(b)
  assert.equal(hitEvents(strong)[0].kind, 'strong')
  assert.equal(hitEvents(shine)[0].kind, 'electric')
  assert.deepEqual(hitEvents(thrown), [], 'a throw spawns no spark (RAM-checked)')
  assert.equal(hitEvents(shield)[0].kind, 'shield')
  assert.equal(hitEvents(big)[0].scale, 1.5, 'the scale is clamped at 1.5')
})

test('the victim shakes through 1.3 x hitlag frames: air up and down, ground along the facing', async () => {
  const air = bundle(20, [fox(), falco({ air: 1, hitlag: i => (i === HIT ? 6 : 0) })])
  const ground = bundle(20, [fox(), falco({ hitlag: i => (i === HIT ? 6 : 0) })])
  await sd.ensureReplayHitData(air)
  assert.deepEqual(FX.shake.patterns[0][0], [0, -3])
  assert.equal(hitShake(air, 0, HIT), null, 'the attacker does not shake')
  assert.equal(hitShake(air, 1, HIT - 1), null)
  assert.deepEqual(hitShake(air, 1, HIT), FX.shake.patterns[0][0])
  assert.deepEqual(hitShake(air, 1, HIT + 1), FX.shake.patterns[0][1])
  const frames = Math.floor(FX.shake.mul * 6 + FX.shake.add)
  assert.notEqual(hitShake(air, 1, HIT + frames - 1), null)
  assert.equal(hitShake(air, 1, HIT + frames), null)
  const [gx, gy] = FX.shake.patterns[1][0]
  assert.deepEqual(hitShake(ground, 1, HIT), [-gx, gy], 'Falco faces left')
})

test('a spark is painted for its effect frames and not after', async () => {
  const b = bundle(40, [fox(), falco()])
  await sd.ensureReplayHitData(b)
  const view = { S: 4, ox: 320, oy: 240 }
  const fills = idx => {
    const c = new RecordingContext()
    drawHitSparks(c, b, idx, view, 1)
    return c.calls.filter(x => x.op === 'fill').length
  }
  assert.equal(fills(HIT - 1), 0)
  assert.ok(fills(HIT) > 0)
  const last = HIT + FX.effects.normal.frames.length - 1
  assert.ok(fills(last) > 0)
  assert.equal(fills(last + 1), 0)
})

test('shield stun tears the bubble from the frame its shield is hit, and starts over on the next hit', () => {
  // guarding, hit at 3 (stun), hit again at 6, out of stun at 12
  const states = [179, 179, 179, 181, 181, 181, 181, 181, 181, 181, 181, 181, 179]
  const shield = [60, 60, 60, 55, 55, 55, 50, 50, 50, 50, 50, 50, 50]
  const n = FX.shieldStun.frames.length
  assert.equal(shieldStun(states, shield, 2), null, 'not in shield stun')
  const first = shieldStun(states, shield, 3)
  assert.notEqual(shieldStun(states, shield, 5), first)
  assert.equal(shieldStun(states, shield, 6), first, 'a new hit starts the flipbook over')
  assert.equal(shieldStun(states, shield, 6 + n), null, 'then the plain bubble')
  // the bubble cut into the game's count of strips, torn past the rim only in
  // the frame's band and never further than its reach; the scribble on the
  // frames the game shows it
  for (let k = 0; k < n; k++) {
    const [outline, scribble] = shieldStun(states, shield, 6 + k)
    const [bands, white] = FX.shieldStun.frames[k]
    assert.equal(outline.length, FX.shieldStun.strips)
    let torn = 0
    for (const [x0, y0, w] of outline) {
      const y = y0 / 100, rim = 100 * Math.sqrt(Math.max(0, 1 - y * y))
      const out = Math.max(Math.abs(x0), Math.abs(x0 + w)) - rim
      if (out > 2) {
        torn++
        const ym = y + 1 / FX.shieldStun.strips
        const band = bands.find(([mid, high]) => Math.abs(ym - mid) < high)
        assert.ok(band, `frame ${k}: torn at ${y}, in no band`)
        assert.ok(out <= 100 * band[2] * 1.15 + 3, `frame ${k}: ${out} past the rim`)
      }
    }
    assert.ok(torn > 0, `frame ${k}: torn`)
    assert.equal(!!scribble, !!white)
  }
})

test('a Shy Guy knocked off or flinching gets the hit spark of the hitbox that hit it', async () => {
  // Fox's jab hitbox reaches a Shy Guy (Yoshi's Story item 210) that flinches at HIT
  const b = bundle(12, [fox()])
  b.meta.stage = 8
  b.items = [{ t: 210, o: -1, f: 0, x: Array(12).fill(8), y: Array(12).fill(9), d: Array(12).fill(1),
    s: Array.from({ length: 12 }, (_, i) => (i < HIT ? 1 : 3)) }]
  await sd.ensureReplayHitData(b)
  const [e] = hitEvents(b).filter(ev => String(ev.victim).startsWith('item'))
  assert.equal(e.idx, HIT); assert.equal(e.kind, 'normal')
  // on the Shy Guy's side facing the hitbox, not past it
  assert.ok(e.x < 8 && Math.hypot(e.x - 8, e.y - 9) <= 3.8 + 1e-6, `${e.x}, ${e.y}`)
})
