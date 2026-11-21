import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { impactEvents, drawImpactEffects } = await import('./impactEffects.js')
const { RecordingContext } = await import('../../../../../tools/liteaudit/recording_context.mjs')
const IFX = (await import('./data/impactEffects.js')).default
await import('./meleeStages.js')   // hydrates the stage tables floorAngle reads

// Fox (port 0) tumbles and misses his tech at 10 (DownBoundU), lies down, is
// knocked into tumble again and misses at 60 (DownBoundD). Falco (port 1)
// shields from 20; his shield breaks at 30 and he is held in hitlag for 4
// frames (action frame 1 on 30-33), then flies up 1 unit a frame.
function bundle(stage = 32) {
  const n = 80, row = v => Array.from({ length: n }, () => v)
  const fox = Array.from({ length: n }, (_, i) => (i < 10 ? 38 : i < 30 ? 183 : i < 50 ? 184 : i < 60 ? 38 : 191))
  const falco = Array.from({ length: n }, (_, i) => (i < 20 ? 14 : i < 30 ? 179 : 205))
  const falcoAge = Array.from({ length: n }, (_, i) => (i < 30 ? 1 : i < 34 ? 1 : i - 32))
  const falcoY = Array.from({ length: n }, (_, i) => (i < 34 ? 0 : i - 33))
  return {
    meta: { n, stage, start_frame: 0, players: [{}, {}] },
    frames: {
      cid: [row(1), row(22)], x: [row(10), row(-20)], y: [row(0), falcoY], dir: [row(1), row(-1)],
      state: [fox, falco], age: [row(1), falcoAge], shield: [row(60), row(1)],
    },
    items: [],
  }
}

test('a missed tech and a shield break spawn their effects once, where the game puts them', () => {
  const ev = impactEvents(bundle())
  assert.deepEqual(ev.map(e => [e.idx, e.kind]), [[10, 'bounce'], [30, 'shieldBreak'], [60, 'bounce']])
  const [bounce, brk] = ev
  assert.deepEqual([bounce.x, bounce.y, bounce.angle, bounce.dust], [10, 0, 0, true], 'on the fighter, on flat Final Destination')
  // the bursts start on action frames 1, 3 and 7 (the script's), on TopN where it is then:
  // hitlag holds action frame 1 for 4 frames, so the second waits until 35. With no
  // recorded seed, at the script's offsets' mean: 4 x the model scale (Falco 1.1) ahead
  assert.deepEqual(IFX.shieldBreak.emit, [1, 3, 7])
  assert.deepEqual(brk.bursts.map(b => [b.idx, +b.x.toFixed(2), b.y, b.z]), [[30, -24.4, 0, 0], [35, -24.4, 2, 0], [39, -24.4, 6, 0]])
})

test("a recorded seed gives each burst the script's random offset, within its range", () => {
  const b = bundle()
  b.frames.frame_seed = [Array.from({ length: 80 }, (_, i) => (((i + 123) << 16) | 0x3e5c) >>> 0)]
  const [, brk] = impactEvents(b)
  for (const [k, burst] of brk.bursts.entries()) {
    const y0 = [0, 2, 6][k]
    assert.ok(Math.abs(burst.x - -24.4) <= 7.7 + 1e-9 && Math.abs(burst.y - y0) <= 7.7 + 1e-9 && Math.abs(burst.z) <= 7.7 + 1e-9, JSON.stringify(burst))
  }
  assert.ok(brk.bursts.some(x => Math.abs(x.z) > 0.5), 'offsets in depth too')
})

test('a burst behind the stage with its heart inside the floor is hidden, as the floor hides it in the game', () => {
  const pick = (want) => {
    for (let s = 1; s < 5000; s++) {
      const b = bundle()
      b.frames.frame_seed = [Array.from({ length: 80 }, () => Math.imul(s, 2654435761) >>> 0)]
      const burst = impactEvents(b)[1].bursts[0]
      if (want(burst)) return burst
    }
  }
  assert.equal(pick(x => x.z < -0.5 && x.y < -1).hidden, true, 'behind, under the floor')
  assert.equal(pick(x => x.z < -0.5 && x.y > 1).hidden, false, 'behind, above the floor')
  assert.equal(pick(x => x.z > 0.5 && x.y < -1).hidden, false, 'in front of the stage')
})

test('Fountain of Dreams floors show no dust', () => {
  const [bounce] = impactEvents(bundle(2))
  assert.equal(bounce.dust, false)
})

test('the effects are painted for their frames and not after', () => {
  const b = bundle()
  const view = { S: 4, ox: 320, oy: 240 }
  const paints = idx => {
    const c = new RecordingContext()
    drawImpactEffects(c, b, idx, view, 1)
    return c.calls.filter(x => x.op === 'fill' || x.op === 'stroke').length
  }
  assert.equal(paints(9), 0)
  assert.ok(paints(10) > 0, 'the crown and the dust on the bounce frame')
  const last = Math.max(IFX.crown.rings[0].a.length, IFX.dust.alpha.length + IFX.dust.births.length - 1) - 1
  assert.ok(paints(10 + last) > 0)
  assert.equal(paints(10 + last + 1), 0, 'the bounce is over before the shield break')
  assert.ok(paints(30) > 0 && paints(31) > 0, 'the shield break')
  assert.equal(paints(59), 0)
})

test('the data is numbers only: no traced art', () => {
  const text = JSON.stringify(IFX)
  assert.ok(!/regions|textures|frames/.test(text))
  assert.ok(text.length < 4000, `${text.length} characters`)
})
