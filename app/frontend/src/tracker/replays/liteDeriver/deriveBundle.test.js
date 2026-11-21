import test from 'node:test'
import assert from 'node:assert/strict'
import { deriveBundle, deriveFromSlp, parseSlp, parseHeaderOnly, SlpError,
  frameWindow, windowBundle, MAX_CLIP_FRAMES } from './index.js'

function fighter(n, patch = {}) {
  const floats = ['x', 'y', 'pct', 'shield', 'age', 'joyX', 'joyY', 'cX', 'cY', 'trigger']
  const bytes = ['present', 'cid', 'stocks', 'lastAttack', 'airborne', 'lcancel']
  const out = Object.fromEntries(floats.map(k => [k, new Float32Array(n)]))
  for (const k of bytes) out[k] = new Uint8Array(n)
  out.state = new Uint16Array(n).fill(14)
  out.buttons = new Uint16Array(n)
  out.dir = new Int8Array(n).fill(1)
  out.present.fill(1)
  for (const [k, v] of Object.entries(patch)) {
    if (v === null) out[k] = null
    else if (typeof v === 'number') out[k].fill(v)
    else out[k].set(v)
  }
  return out
}

function parsed(n = 6, chars = [2, 9]) {
  const players = chars.map((extChar, i) => ({ port: i * 2, extChar, costume: i,
    team: null, type: 0, code: i ? null : 'TEST#1', name: i ? null : 'Test' }))
  return { version: [3, 19, 1], start: { stage: 31, isTeams: false, players },
    firstFrame: -123, lastFrame: n - 124, n, rows: n,
    rowFids: Int32Array.from({ length: n }, (_, i) => i - 123),
    ports: players.map(p => ({ port: p.port, leader: fighter(n), follower: null })),
    items: [], stage: { fod: [], stadium: [] }, end: null, warnings: [] }
}

function item(start, xs, type = 54, owner = 2) {
  return { spawn: 17, start, type, owner, x: Float32Array.from(xs),
    y: Float32Array.from(xs, x => x + 0.125), dir: new Int8Array(xs.length).fill(-1),
    state: new Uint8Array(xs.length).fill(8), vx: new Float32Array(xs.length).fill(1.75),
    vy: new Float32Array(xs.length).fill(-0.25) }
}

test('setup and leader/follower RNG channels survive direct and repeated windowing', () => {
  const p=parsed(4,[14]);p.start.seed=0xffffffff
  p.frameSeeds=[0,1,2,3];p.sceneFrames=[5,6,7,8]
  const a=p.ports[0].leader
  a.seed=Uint32Array.from([10,11,12,13]);a.seedOrder=Uint32Array.from([100,200,300,400]);a.preState=Uint16Array.from([14,15,16,17])
  const f=p.ports[0].follower=fighter(4,{present:[1,0,1,0]})
  f.seed=Uint32Array.from([20,0,22,0]);f.seedOrder=Uint32Array.from([150,0,350,0]);f.preState=Uint16Array.from([18,0,20,0])
  const full=deriveBundle(p),clip=deriveBundle(p,{lo:1,hi:2})
  assert.equal(full.meta.start_seed,0xffffffff)
  assert.deepEqual(full.frames.fol[0].seed,[20,null,22,null])
  assert.deepEqual(clip.frames.seed,[[11,12]])
  assert.deepEqual(clip.frames.seed_order,[[200,300]])
  assert.deepEqual(clip.frames.pre_state,[[15,16]])
  assert.deepEqual(clip.frames.frame_seed,[[1,2]])
  assert.deepEqual(clip.frames.scene_frame,[[6,7]])
  assert.deepEqual(windowBundle(full,-122,-121,0),clip)
})

test('v5 shape, unrounded channels, compact player indices, and JSON arrays', () => {
  const p = parsed(2)
  p.ports[0].leader = fighter(2, { cid: 1, x: [1.234567, -2.345678], y: 9.123,
    pct: 42.125, stocks: 3, lastAttack: 13, age: 2.75, airborne: 1,
    joyX: 0.125, joyY: -0.25, cX: 0.5, cY: -0.75, buttons: 0x8190, shield: 54.25, dir: -1 })
  const b = deriveBundle(p)
  assert.deepEqual(Object.keys(b).sort(), ['conversions', 'frames', 'items', 'meta'])
  assert.deepEqual(b.meta, { v: 5, finalized: true, deriver: 'lite-js-1', slp_version: '3.19.1',
    file: '', stage: 31, stage_name: 'BF', stage_edge: 68.4, start_frame: -123, start_seed: null, n: 2, fps: 60,
    players: [
      { port_index: 0, physical_port: 0, cpu: false, char: 2, char_name: 'Fox', css_char: 'Fox', costume: 0,
        transforms: false, team: null, code: 'TEST#1', tag: 'Test' },
      { port_index: 1, physical_port: 2, cpu: false, char: 9, char_name: 'Marth', css_char: 'Marth', costume: 1,
        transforms: false, team: null, code: null, tag: null },
    ], teams: false, attack_names: b.meta.attack_names })
  assert.equal(b.meta.attack_names[21], 'down-B')
  assert.equal(b.meta.attack_names[53], 'fthrow')
  const map = { x: 'x', y: 'y', pct: 'pct', stk: 'stocks', air: 'airborne', state: 'state',
    move: 'lastAttack', dir: 'dir', joyx: 'joyX', joyy: 'joyY', cstickx: 'cX',
    csticky: 'cY', btn: 'buttons', shield: 'shield', cid: 'cid', age: 'age' }
  for (const [key, source] of Object.entries(map)) assert.deepEqual(b.frames[key][0], [...p.ports[0].leader[source]], key)
  assert.deepEqual(b.frames.cat, [[1, 1], [0, 0]])
  assert.deepEqual(b.frames.form, [null, null])
  assert.deepEqual(b.conversions, {})
  assert.deepEqual(JSON.parse(JSON.stringify(b)), b)
})

test('category boundaries include tech states and exclude escape/rebound states', () => {
  const p = parsed(401)
  p.ports[0].leader.state = Uint16Array.from({ length: 401 }, (_, i) => i)
  p.ports[1].leader.state.set(p.ports[0].leader.state)
  p.ports[1].leader.airborne.fill(1)
  const b = deriveBundle(p)
  const captured = s => s === 38 || (s >= 75 && s <= 91) || (s >= 183 && s <= 201)
    || (s >= 223 && s <= 232) || (s >= 239 && s <= 243)
  for (let s = 0; s <= 400; s++) for (let air = 0; air < 2; air++) {
    const want = s <= 10 ? 6 : captured(s) ? 4 : s >= 178 && s <= 182 ? 3
      : s >= 252 && s <= 263 ? 5 : (s >= 44 && s <= 74) || s >= 341 ? 2 : air
    assert.equal(b.frames.cat[air][s], want, `state ${s}, air ${air}`)
  }
})

test('forms and dominant name use the full game, with first-seen tie breaking', () => {
  const p = parsed(6, [18, 19])
  p.ports[0].leader.cid.set([19, 7, 7, 7, 19, 0])
  p.ports[1].leader.cid.set([19, 7, 0, 0, 7, 19])
  const b = deriveBundle(p, { lo: 4, hi: 5 })
  assert.deepEqual(b.frames.form, ['Z.', 'SZ'])
  assert.equal(b.meta.players[0].char_name, 'Sheik')
  assert.equal(b.meta.players[0].css_char, 'Zelda')
  assert.equal(b.meta.players[1].char_name, 'Zelda')
  assert.ok(b.meta.players.every(p => p.transforms))
  p.ports[0].leader.cid.fill(7)
  const single = deriveBundle(p)
  assert.equal(single.frames.form[0], null)
  assert.equal(single.meta.players[0].char_name, 'Zelda')
  assert.equal(single.meta.players[0].transforms, false)
})

test('lightshield restarts from 0 at a fresh guard and is not read right after shieldstun', () => {
  const p = parsed(8)
  // depth 50 before the guard; a digital press (trigger 0) at GuardOn keeps 0, not 50
  p.ports[0].leader.trigger.set([0.65, 0, 0, 0, 1, 0, 0.65, 0.65])
  p.ports[0].leader.state.set([14, 14, 178, 179, 179, 181, 181, 179])
  assert.deepEqual(deriveBundle(p).frames.lt[0], [50, 50, 0, 0, 100, 100, 100, 100])
})

test('lightshield holds across the full prefix, clamps, and supports absent triggers', () => {
  const p = parsed(8)
  p.ports[0].leader.trigger.set([0, 0.65, 0.1, 0, 2, 0.2, 0.5625, 0])
  p.ports[1].leader.trigger = null
  assert.deepEqual(deriveBundle(p).frames.lt, [[0, 50, 50, 50, 100, 100, 38, 38], null])
  assert.deepEqual(deriveBundle(p, { lo: 2, hi: 7 }).frames.lt, [[50, 50, 100, 100, 38, 38], null])
})

test('CSS/internal fallback maps and missing optional channels match the exporter', () => {
  const mapping = [2, 3, 1, 24, 4, 5, 6, 17, 0, 18, 16, 8, 9, 12, 10, 15, 13, 14, 19, 7, 22, 20, 21, 26, 23, 25]
  for (const ext of [...mapping.keys(), 99]) {
    const p = parsed(2, [ext])
    for (const k of ['cid', 'dir', 'joyX', 'joyY', 'cX', 'cY', 'shield', 'age', 'trigger']) p.ports[0].leader[k] = null
    const b = deriveBundle(p)
    assert.deepEqual(b.frames.cid[0], [mapping[ext] ?? ext, mapping[ext] ?? ext])
    assert.deepEqual(b.frames.dir[0], [1, 1])
    for (const k of ['joyx', 'joyy', 'cstickx', 'csticky', 'shield', 'age']) assert.deepEqual(b.frames[k][0], [0, 0])
    assert.equal(b.frames.lt[0], null)
    if (ext === 99) assert.equal(b.meta.players[0].char_name, 'ext99')
  }
})

test('Nana absent rows stay null in every channel, including fallback channels', () => {
  const p = parsed(4, [2, 14])
  p.ports[1].follower = fighter(4, { present: [0, 1, 0, 1], cid: 11, x: 12.125, state: 44, age: 3.5 })
  p.ports[1].follower.shield = null
  const b = deriveBundle(p)
  const f = b.frames.fol[0]
  assert.equal(f.of, 1)
  assert.deepEqual(Object.keys(f).sort(), ['age', 'air', 'cid', 'dir', 'hitby', 'of', 'pct', 'pre_state', 'seed', 'seed_order', 'shield', 'state', 'x', 'y'])
  for (const [k, v] of Object.entries(f)) if (k !== 'of') {
    assert.equal(v[0], null, k); assert.equal(v[2], null, k)
  }
  assert.deepEqual(f.x, [null, 12.125, null, 12.125])
  assert.deepEqual(f.shield, [null, 0, null, 0])
  assert.deepEqual(deriveBundle(p, { lo: 1, hi: 2 }).frames.fol[0].cid, [11, null])
  assert.equal(b.meta.players.length, 2)
})

test('items keep raw owner ports and clip all six arrays to relative indices', () => {
  const p = parsed(7)
  p.items = [item(-125, [0, 1, 2, 3, 4, 5]), item(-120, [7, 8, 9, 10], 99), item(-116, [11])]
  const b = deriveBundle(p, { lo: 2, hi: 5 })
  assert.deepEqual(b.items, [
    { t: 54, o: 2, f: 0, born: -4, x: [4, 5], y: [4.125, 5.125], d: [-1, -1], s: [8, 8], vx: [1.75, 1.75], vy: [-0.25, -0.25] },
    { t: 99, o: 2, f: 1, x: [7, 8, 9], y: [7.125, 8.125, 9.125], d: [-1, -1, -1], s: [8, 8, 8], vx: [1.75, 1.75, 1.75], vy: [-0.25, -0.25, -0.25] },
  ])
})

test('stage deltas carry in independently, before events exactly at clip start', () => {
  const p = parsed(10)
  p.stage = { fod: [[-125, 1, 8], [-124, 0, 10], [-122, 1, 20], [-120, 0, 30], [-118, 1, 40], [-114, 0, 50]],
    stadium: [[-124, 1, 3], [-121, 2, 3], [-120, 1, 4], [-118, 2, 4], [-114, 1, 5]] }
  assert.deepEqual(deriveBundle(p, { lo: 3, hi: 5 }).stage_state, {
    fod: [[0, 0, 10], [0, 1, 20], [0, 0, 30], [2, 1, 40]],
    stadium: [[0, 2, 3], [0, 1, 4], [2, 2, 4]],
  })
  assert.deepEqual(deriveBundle(p, { lo: 6, hi: 7 }).stage_state, {
    fod: [[0, 0, 30], [0, 1, 40]], stadium: [[0, 2, 4]],
  })
  assert.equal('stage_state' in deriveBundle(parsed()), false)
})

test('frame windows use true frames, clamp, and apply the 1500 cap before padding', () => {
  const p = parsed(5000)
  p.rows = 9000
  assert.equal(MAX_CLIP_FRAMES, 1500)
  assert.deepEqual(frameWindow(p, 100, 10000), { lo: 178, hi: 1768 })
  assert.deepEqual(frameWindow(p, -500, -400, 0), { lo: 0, hi: 0 })
  assert.deepEqual(frameWindow(p, 10000, 20000, 0), { lo: 4999, hi: 4999 })
  assert.deepEqual(frameWindow(p, 200, 100, 0), { lo: 323, hi: 323 })
  assert.deepEqual(frameWindow(p, 0, 0, 0), { lo: 123, hi: 123 })
  const whole = deriveBundle(p)
  assert.equal(whole.meta.n, 5000)
  const clip = windowBundle(whole, 100, 10000)
  assert.equal(clip.meta.start_frame, 55)
  assert.equal(clip.meta.n, 1591)
  assert.deepEqual(clip, deriveBundle(p, frameWindow(p, 100, 10000)))
})

test('direct derivation equals windowing, without mutating the source', () => {
  const p = parsed(9, [18, 14])
  p.ports[0].leader.cid.set([7, 7, 7, 7, 19, 19, 19, 0, 0])
  p.ports[0].leader.trigger[0] = 0.65
  p.ports[1].follower = fighter(9, { present: [1, 0, 1, 0, 1, 0, 1, 0, 1], cid: 11 })
  p.items = [item(-123, [1, 2, 3, 4, 5, 6, 7]), item(-118, [1, 2, 3])]
  p.stage = { fod: [[-123, 0, 20], [-122, 1, 30], [-120, 0, 40]], stadium: [[-123, 1, 3], [-119, 2, 3]] }
  const b = deriveBundle(p), before = JSON.stringify(b)
  for (const [start, end, pad] of [[-121, -119, 0], [-120, -118, 1], [-900, 9000, 45], [-118, -120, 0]]) {
    assert.deepEqual(windowBundle(b, start, end, pad), deriveBundle(p, frameWindow(p, start, end, pad)))
  }
  assert.equal(JSON.stringify(b), before)
  const clipped = windowBundle(b, -121, -117, 0)
  assert.deepEqual(windowBundle(clipped, -119, -118, 0), deriveBundle(p, { lo: 4, hi: 5 }))
})

test('windowBundle supports typed tracks and keeps overlapping sidecar conversions absolute', () => {
  const b = deriveBundle(parsed(6))
  b.frames.x[0] = Float32Array.from([0, 1, 2, 3, 4, 5])
  b.frames.lt[1] = null
  const convs = [
    { start_frame: -123, end_frame: -122 }, { start_frame: -122, end_frame: -121 },
    { start_frame: -121, end_frame: -119 }, { start_frame: -119, end_frame: -117 },
    { start_frame: -118, end_frame: -117 },
  ]
  b.conversions = { 0: convs, 1: [] }
  const clip = windowBundle(b, -121, -119, 0)
  assert.deepEqual(clip.frames.x[0], Float32Array.from([2, 3, 4]))
  assert.equal(clip.frames.lt[1], null)
  assert.deepEqual(clip.conversions, { 0: convs.slice(1, 4), 1: [] })
  assert.equal(b.frames.x[0].length, 6)
})

test('teams, all ports, unknown stage, and empty timelines remain usable', () => {
  const p = parsed(2, [0, 2, 20, 99])
  p.start.stage = 999; p.start.isTeams = true
  p.start.players.forEach((player, i) => { player.port = i; player.team = i % 2 })
  const b = deriveBundle(p)
  assert.equal(b.meta.stage_name, 'stage 999'); assert.equal(b.meta.stage_edge, 70)
  assert.equal(b.meta.teams, true)
  assert.deepEqual(b.meta.players.map(p => p.team), [0, 1, 0, 1])
  assert.deepEqual(b.conversions, {})
  const empty = parsed(0)
  empty.firstFrame = 0; empty.lastFrame = -1
  const e = deriveBundle(empty)
  assert.equal(e.meta.n, 0); assert.deepEqual(e.frames.x, [[], []])
  assert.deepEqual(frameWindow(empty, 0, 100), { lo: 0, hi: -1 })
  assert.equal(windowBundle(e, 0, 100), e)
})

test('derive clamps index bounds and rejects pre-2.0 with the public SlpError', () => {
  const p = parsed(6)
  assert.equal(deriveBundle(p, { lo: -50, hi: 90 }).meta.n, 6)
  assert.equal(deriveBundle(p, { lo: 50, hi: -90 }).meta.n, 1)
  p.version = [1, 9, 9]
  assert.throws(() => deriveBundle(p), e => e instanceof SlpError && e.message === 'unsupported: pre-2.0')
})

// Minimal fabricated Slippi bytes exercise the public composition API without
// borrowing replay data or sharing the parser's fixture implementation.
function syntheticBytes(version = [2, 0, 0]) {
  const sizes = [[0x36, 0x140], [0x38, 51]], chunks = []
  const table = new Uint8Array(8)
  table.set([0x35, 7, 0x36, 1, 0x40, 0x38, 0, 51]); chunks.push(table)
  const start = new Uint8Array(0x141)
  start[0] = 0x36; start.set(version, 1)
  new DataView(start.buffer).setUint16(0x13, 32)
  for (let port = 0; port < 4; port++) {
    start[0x65 + port * 0x24] = 2
    start[0x66 + port * 0x24] = port < 2 ? 0 : 3
  }
  chunks.push(start)
  for (let frame = -123; frame <= -120; frame++) for (let port = 0; port < 2; port++) {
    const post = new Uint8Array(sizes[1][1] + 1), v = new DataView(post.buffer)
    post[0] = 0x38; v.setInt32(1, frame); post[5] = port; post[7] = 1
    v.setUint16(8, 14); v.setFloat32(0xA, frame + port * 0.125); v.setFloat32(0x12, 1)
    chunks.push(post)
  }
  const rawSize = chunks.reduce((n, c) => n + c.length, 0)
  const bytes = new Uint8Array(15 + rawSize)
  bytes.set([123, 85, 3, 114, 97, 119, 91, 36, 85, 35, 108])
  new DataView(bytes.buffer).setInt32(11, rawSize)
  let offset = 15
  for (const c of chunks) { bytes.set(c, offset); offset += c.length }
  return bytes
}

test('public API composes bytes to whole games and true-frame clips', () => {
  const bytes = syntheticBytes()
  assert.equal(parseHeaderOnly(bytes).start.stage, 32)
  assert.deepEqual(deriveFromSlp(bytes.buffer), deriveBundle(parseSlp(bytes)))
  const b = deriveFromSlp(bytes, { start: -122, end: -121, pad: 0 })
  assert.equal(b.meta.start_frame, -122); assert.equal(b.meta.n, 2)
  assert.deepEqual(b.frames.x, [[-122, -121], [-121.875, -120.875]])
  assert.deepEqual(deriveFromSlp(bytes, { start: -121, pad: 0 }).frames.x[0], [-121, -120])
  assert.deepEqual(deriveFromSlp(bytes, { end: -122, pad: 0 }).frames.x[0], [-123, -122])
  assert.throws(() => deriveFromSlp(syntheticBytes([1, 9, 0])), SlpError)
})

test('windowBundle slices the additive item channels with the item track', () => {
  const t = [0, 1, 2, 3, 4, 5]
  const item = { f: 1, k: 54, x: t, y: t, d: t, s: t, vx: t, vy: t,
    lifetime: [9, 8, 7, 6, 5, 4], subtype: t, face: t, launched: t, charge: t, owner: t, port: t }
  const b = { meta: { start_frame: -123, n: 10 }, frames: {}, items: [item] }
  const clip = windowBundle(b, -120, -118, 0)
  assert.equal(clip.items.length, 1)
  assert.equal(clip.items[0].f, 0)
  for (const k of ['x', 'lifetime', 'subtype', 'face', 'launched', 'charge', 'owner', 'port']) {
    assert.equal(clip.items[0][k].length, clip.items[0].x.length, k)
  }
  assert.deepEqual(clip.items[0].lifetime, [7, 6, 5])
})
