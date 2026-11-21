import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'
import { readFile } from 'node:fs/promises'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
// A stageData of its own (the hit table cache must start empty) and swordTrails
// bound to it, as hitSparks.test.js builds its runtime.
const fresh = new URL(`./stageData.js?trails=${Date.now()}`, import.meta.url).href
const sd = await import(fresh)
const source = (await readFile(new URL('./swordTrails.js', import.meta.url), 'utf8'))
  .replace(/from '(\.\/[^']+)'/g, (_, rel) => `from ${JSON.stringify(rel === './stageData.js' ? fresh : new URL(rel, import.meta.url).href)}`)
const { trailSamples, trailStrip, drawSwordTrails } = await import(`data:text/javascript,${encodeURIComponent(source)}`)
const { RecordingContext } = await import('../../../../../tools/liteaudit/recording_context.mjs')
sd.registerHitDataLoader(async id => JSON.parse(await readFile(new URL(`./data/hits/${id}.json`, import.meta.url), 'utf8')))

const MARTH = 18, JAB = 44
await sd.ensureHitData(MARTH)
const T = sd.hitDataFor(MARTH).trail
const jab = T.states[JAB][0]                 // [first, last, rows]

// one fighter row; every channel a function of the frame index
function bundle(n, row) {
  const keys = ['cid', 'x', 'y', 'dir', 'state', 'age']
  const frames = Object.fromEntries(keys.map(k => [k, [Array.from({ length: n }, (_, i) => (typeof row[k] === 'function' ? row[k](i) : row[k]))]]))
  return { meta: { n, stage: 32, start_frame: 0 }, frames, items: [] }
}
const marth = (patch = {}) => bundle(30, { cid: MARTH, x: 10, y: 0, dir: 1, state: JAB, age: i => i, ...patch })
const samples = (b, idx) => {
  const f = b.frames
  return trailSamples(f.cid[0][idx], f.state[0], f.age[0], f.x[0], f.y[0], f.dir[0], idx)
}

test('Marth, Link, Young Link and Roy have the game\'s trail colours; nobody else has a trail', async () => {
  const want = { 6: ['00ffff', 'ffffff'], 18: ['00ffff', 'ffffff'], 20: ['00ffff', 'ffffff'], 26: ['eb7850', 'ffffff'] }
  for (let cid = 0; cid < 27; cid++) {
    await sd.ensureHitData(cid)
    assert.deepEqual(sd.hitDataFor(cid).trail?.color, want[cid], `cid ${cid}`)
  }
  assert.deepEqual(T.alpha, [1, 0])
})

test('the ring: none on the start frame, then the newest three action frames, gone once it stops', () => {
  const b = marth()
  const [first, last] = jab
  assert.equal(samples(b, first), null, 'one sample draws nothing')
  assert.equal(samples(b, first + 1).length, 2)
  const s = samples(b, first + 3)
  assert.equal(s.length, 3)
  // newest first: the joint at action frames first+3, first+2, first+1, around x 10
  for (const [k, fr] of [[0, first + 3], [1, first + 2], [2, first + 1]]) {
    const r = jab[2][fr - first]
    assert.deepEqual(s[k].b, [10 + r[0], r[1], r[2]])
    assert.deepEqual(s[k].a, r.slice(3))
  }
  assert.equal(samples(b, last + 1), null, 'the stop command ends it')
  assert.equal(samples(bundle(30, { cid: 2, x: 0, y: 0, dir: 1, state: JAB, age: i => i }), first + 3), null, 'no table, no trail')
})

test('facing left mirrors the joint and its axis (x and z)', () => {
  const r = jab[2][3]
  const s = samples(marth({ dir: -1 }), jab[0] + 3)
  assert.deepEqual(s[0].b, [10 - r[0], r[1], -r[2]])
  assert.deepEqual(s[0].a, [-r[3], r[4], -r[5]])
})

test('hitlag freezes the ring: frames whose action frame stands still push nothing', () => {
  const hit = jab[0] + 3
  // the action frame counter stops for 4 frames after the hit frame
  const b = marth({ age: i => (i <= hit ? i : i <= hit + 4 ? hit : i - 4) })
  const atHit = samples(b, hit)
  for (let i = hit + 1; i <= hit + 4; i++) assert.deepEqual(samples(b, i), atHit, `frame ${i}`)
  assert.deepEqual(samples(b, hit + 5).map(s => s.b), [samples(marth(), hit + 1)[0].b, ...atHit.slice(0, 2).map(s => s.b)])
})

test('a new run of the same move starts its own ring', () => {
  const again = 12
  const b = marth({ age: i => (i < again ? i : i - again) })
  // the second jab's start frame: one sample of its own, none of the first jab's
  assert.equal(samples(b, again + jab[0]), null)
  assert.equal(samples(b, again + jab[0] + 1).length, 2)
})

test('the strip: the blade from inner to outer, turned in 5 degree steps, tapering and fading', () => {
  const t = { inner: 2, outer: 10, old: [0.5, 1], alpha: [1, 0], color: ['00ffff', 'ffffff'] }
  // the blade turns 90 degrees about the camera axis while its joint stays put
  const rows = trailStrip(t, [{ b: [0, 0, 0], a: [1, 0, 0] }, { b: [0, 0, 0], a: [0, 1, 0] }])
  assert.equal(rows.length, 2 + 18)
  assert.deepEqual(rows[0], { i: [2, 0, 0], o: [10, 0, 0], a: 1 })
  const last = rows.at(-1)
  assert.ok(Math.abs(Math.hypot(...last.i) - 6) < 1e-9 && Math.abs(last.i[0]) < 1e-9 && last.a === 0, 'the oldest inner edge has moved out to half the blade')
  for (const r of rows) assert.ok(Math.abs(Math.hypot(...r.o) - 10) < 1e-9 && r.o[2] === 0, 'the outer edge sweeps the circle')
  for (let k = 1; k < rows.length; k++) assert.ok(rows[k].a < rows[k - 1].a)
})

test('the fade follows the game\'s distances, which carry the first step\'s difference', () => {
  const t = { inner: 0, outer: 1, old: [0, 1], alpha: [1, 0], color: ['ffffff', 'ffffff'] }
  const ring = [{ b: [100, 0, 0], a: [1, 0, 0] }, { b: [97, 0, 0], a: [1, 0, 0] }, { b: [94, 0, 0], a: [1, 0, 0] }]
  const rows = trailStrip(t, ring)
  // tips 101, 98, 95: steps |98 - 101| = 3, then |95 - (98 - 101)| = 98
  assert.ok(Math.abs(rows[1].a - (1 - 3 / 101)) < 1e-9, `${rows[1].a}`)
  assert.equal(rows[2].a, 0)
})

test('paint: a trail is filled around the swing, mirrored with the facing, and only while it is on', () => {
  const view = { S: 2, ox: 320, oy: 240 }
  const tip = (b, idx) => { const s = samples(b, idx)[0]; return [s.b[0] + s.a[0] * T.outer, s.b[1] + s.a[1] * T.outer] }
  for (const dir of [1, -1]) {
    const b = marth({ dir }), idx = jab[0] + 3
    const ctx = new RecordingContext()
    drawSwordTrails(ctx, b, idx, view, 1)
    const fills = ctx.calls.filter(c => c.op === 'fill' && c.alpha > 0)
    assert.ok(fills.length > 3, `${fills.length} fills`)
    const pts = fills.flatMap(c => c.path.filter(p => p.point).map(p => [(p.point[0] - view.ox) / view.S, (view.oy - p.point[1]) / view.S]))
    const [tx, ty] = tip(b, idx)
    assert.ok(pts.some(([x, y]) => Math.hypot(x - tx, y - ty) < 0.5), 'the newest edge reaches the sword tip')
    assert.ok(pts.every(([x]) => dir > 0 ? x > 0 : x < 20), 'drawn on the facing side')
  }
  const off = new RecordingContext()
  drawSwordTrails(off, marth(), jab[1] + 1, view, 1)
  assert.equal(off.calls.filter(c => c.op === 'fill').length, 0)
})

test('a held Beam Sword trails in any fighter\'s swing: the item\'s colours, its blade out to the newest length', async () => {
  const MARIO = 0, SWING1 = 120
  await sd.ensureHitData(MARIO)
  const beam = sd.hitDataFor(MARIO).beam
  assert.equal(sd.hitDataFor(MARIO).trail, undefined)
  assert.deepEqual(beam.color, ['ff40ff', 'ffffff'])
  assert.deepEqual(beam.old, [0, 1])
  const [first, last, rows] = beam.states[SWING1][0]
  const b = bundle(30, { cid: MARIO, x: 0, y: 0, dir: 1, state: SWING1, age: i => i })
  const f = b.frames, at = first + 4
  const s = trailSamples(MARIO, f.state[0], f.age[0], f.x[0], f.y[0], f.dir[0], at, 'beam')
  assert.equal(s.length, 3)
  assert.deepEqual(s.map(q => q.o), [at, at - 1, at - 2].map(fr => rows[fr - first][6]))
  assert.equal(trailSamples(MARIO, f.state[0], f.age[0], f.x[0], f.y[0], f.dir[0], at), null, 'no sword of his own')
  const ctx = new RecordingContext()
  drawSwordTrails(ctx, b, at, { S: 2, ox: 320, oy: 240 }, 1)
  const fills = ctx.calls.filter(c => c.op === 'fill' && c.alpha > 0)
  // a context with linear gradients gets pink -> white across the blade, one without
  // gets the flat middle colour
  const pinkToWhite = s => s === 'rgb(255,159,255)' || (s?.type === 'linear'
    && JSON.stringify(s.stops) === JSON.stringify([[0, 'rgb(255,64,255)'], [1, 'rgb(255,255,255)']]))
  assert.ok(fills.length > 1 && fills.every(c => pinkToWhite(c.fillStyle)), 'pink to white')
  const pts = fills.flatMap(c => c.path.filter(p => p.point).map(p => [(p.point[0] - 320) / 2, (240 - p.point[1]) / 2]))
  const r = rows[at - first], tip = [r[0] + r[3] * r[6], r[1] + r[4] * r[6]]
  assert.ok(pts.some(([x, y]) => Math.hypot(x - tip[0], y - tip[1]) < 0.5), 'out to the blade\'s tip')
  assert.ok(last >= first)
})
