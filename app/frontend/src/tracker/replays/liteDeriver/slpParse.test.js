import test from 'node:test'
import assert from 'node:assert/strict'
import { parseSlp, parseHeaderOnly, SlpError } from './slpParse.js'

// All fixtures are fabricated here. Offsets count the command byte, like SPEC.md,
// so the test builder does not share the parser's payload-offset arithmetic.
const defaults = { 0x36: 0x2F8, 0x37: 0x42, 0x38: 0x54, 0x39: 6,
  0x3A: 12, 0x3B: 44, 0x3C: 8, 0x3F: 9, 0x41: 8, 0x10: 516, 0x50: 0 }
function event(cmd, size, fields = []) {
  const bytes = new Uint8Array(size + 1), view = new DataView(bytes.buffer)
  bytes[0] = cmd
  for (const [type, offset, value] of fields) view[`set${type}`](offset, value)
  return bytes
}
function join(parts) {
  const bytes = new Uint8Array(parts.reduce((n, part) => n + part.length, 0))
  let pos = 0
  for (const part of parts) { bytes.set(part, pos); pos += part.length }
  return bytes
}
function fixture(events = [], { version = [3, 18, 0], sizes = {}, players = [0, 2], teams = false,
  rawLength, footer = new Uint8Array(), startEdit } = {}) {
  const table = { ...defaults, ...sizes }
  const gs = event(0x36, table[0x36])
  gs.set(version, 1)
  gs[0xD] = +teams
  new DataView(gs.buffer).setUint16(0x13, 31)
  for (let port = 0; port < 4; port++) {
    const p = 0x65 + port * 0x24
    gs[p] = 10 + port; gs[p + 1] = players.includes(port) ? port % 3 : 3
    gs[p + 3] = 4 + port; gs[p + 9] = port % 2
  }
  startEdit?.(gs)
  const entries = Object.entries(table).filter(([, size]) => size !== null)
  const sizesEvent = event(0x35, 1 + entries.length * 3)
  sizesEvent[1] = 1 + entries.length * 3
  const sv = new DataView(sizesEvent.buffer)
  entries.forEach(([cmd, size], i) => { sizesEvent[2 + i * 3] = +cmd; sv.setUint16(3 + i * 3, size) })
  const raw = join([sizesEvent, gs, ...events])
  const head = new Uint8Array([123, 85, 3, 114, 97, 119, 91, 36, 85, 35, 108, 0, 0, 0, 0])
  new DataView(head.buffer).setInt32(11, rawLength ?? raw.length)
  return join([head, raw, footer])
}
const fs = f => event(0x3A, defaults[0x3A], [['Int32', 1, f]])
const fe = f => event(0x3C, defaults[0x3C], [['Int32', 1, f], ['Int32', 5, f]])
function pre(f, port = 0, follower = 0, change = 0, size = defaults[0x37]) {
  return event(0x37, size, [ ['Int32', 1, f], ['Uint8', 5, port], ['Uint8', 6, follower],
    ['Float32', 0x19, 0.125 + change], ['Float32', 0x1D, -0.25], ['Float32', 0x21, 0.5],
    ['Float32', 0x25, -0.75], ['Float32', 0x29, 0.625], ['Uint32', 0x2D, 0xDEADBEEF],
    ['Uint16', 0x31, 0x8190], ['Float32', 0x33, 0.9375], ['Float32', 0x37, 0.0625] ])
}
function post(f, port = 0, follower = 0, change = 0, size = defaults[0x38]) {
  const fields = [['Int32', 1, f], ['Uint8', 5, port], ['Uint8', 6, follower],
    ['Uint8', 7, 7 + change], ['Uint16', 8, 300 + change], ['Float32', 0xA, 1.25 + change],
    ['Float32', 0xE, -23.5], ['Float32', 0x12, -1], ['Float32', 0x16, 42.125],
    ['Float32', 0x1A, 54.25], ['Uint8', 0x1E, 13], ['Uint8', 0x21, 3]]
  if (size >= 37) fields.push(['Float32', 0x22, 7.75])
  if (size >= 47) fields.push(['Uint8', 0x2F, 1])
  if (size >= 51) fields.push(['Uint8', 0x33, 2])
  return event(0x38, size, fields)
}
function item(f, spawn = 1, { type = 54, x = 1.25, owner = 2, dir = -1, size = 44 } = {}) {
  const fields = [['Int32', 1, f], ['Uint16', 5, type], ['Uint8', 7, 8],
    ['Float32', 8, dir], ['Float32', 0xC, 3.125], ['Float32', 0x10, -0.625],
    ['Float32', 0x14, x], ['Float32', 0x18, 27.5], ['Uint32', 0x22, spawn]]
  if (size >= 42) fields.push(['Int8', 0x2A, owner])
  return event(0x3B, size, fields)
}
const fod = (f, platform, height) => event(0x3F, 9, [['Int32', 1, f], ['Uint8', 5, platform], ['Float32', 6, height]])
const stadium = (f, ev, id) => event(0x41, 8, [['Int32', 1, f], ['Uint16', 5, ev], ['Uint16', 7, id]])
const arr = a => Array.from(a)

test('GameStart seed is unsigned at SPEC command offset 0x13D, since 0.1.0', () => {
  const startEdit = gs => new DataView(gs.buffer).setUint32(0x13D, 0xfedcba98)
  for (const version of [[0,1,0],[2,0,0],[3,19,1]]) {
    const bytes = fixture([], {version,startEdit})
    assert.equal(parseHeaderOnly(bytes).start.seed,0xfedcba98)
    assert.equal(parseSlp(bytes).start.seed,0xfedcba98)
  }
  assert.equal(parseHeaderOnly(fixture([],{version:[0,0,0],startEdit})).start.seed,null)
  assert.equal(parseHeaderOnly(fixture()).start.seed,0)
})

test('RNG records retain final emission order including Nana, independently of posts', () => {
  const seedPre = (port, follower, seed, state) => {
    const b=pre(-123,port,follower),v=new DataView(b.buffer)
    v.setUint32(7,seed);v.setUint16(11,state);return b
  }
  const start=fs(-123),v=new DataView(start.buffer)
  v.setUint32(5,0xdeadbeef);v.setUint32(9,0x10001)
  const p=parseSlp(fixture([fs(-123),seedPre(2,1,9,14),post(-123,2,1),fe(-123),
    start,seedPre(2,0,20,18),post(-123,2),seedPre(0,0,30,40),post(-123),seedPre(2,1,0,212),fe(-123)]))
  const a=p.ports[0].leader,b=p.ports[1].leader,n=p.ports[1].follower
  assert.ok(n.seedOrder[0]>a.seedOrder[0]&&a.seedOrder[0]>b.seedOrder[0])
  assert.equal(n.seed[0],0);assert.equal(n.preState[0],212)
  assert.deepEqual(p.frameSeeds,[0xdeadbeef]);assert.deepEqual(p.sceneFrames,[0x10001])
  const stale=parseSlp(fixture([fs(-123),seedPre(2,1,9,14),post(-123,2,1),fe(-123),fs(-123),fe(-123)]))
  assert.equal(stale.ports[1].follower.seedOrder[0],0)
  assert.deepEqual(parseSlp(fixture([start],{version:[3,9,0]})).sceneFrames,[null])
})

test('header decodes sparse ports, teams, Shift JIS strings, and an ArrayBuffer/view offset', () => {
  const bytes = fixture([], { teams: true, startEdit: gs => {
    // Fullwidth A and #, plus Japanese hiragana a. Embedded NUL ends the name.
    gs.set([0x82, 0x60, 0x82, 0xA0, 0, 65], 0x1A5)
    gs.set([65, 66, 0x81, 0x94, 49, 0], 0x221)
  } })
  const h = parseHeaderOnly(bytes.buffer)
  assert.deepEqual(h.version, [3, 18, 0])
  assert.equal(h.rawLength, bytes.length - 15)
  assert.equal(h.start.stage, 31)
  assert.deepEqual(h.start.players, [
    { port: 0, extChar: 10, costume: 4, team: 0, type: 0, code: 'AB＃1', name: 'Ａあ' },
    { port: 2, extChar: 12, costume: 6, team: 0, type: 2, code: null, name: null },
  ])
  const padded = join([new Uint8Array(9), bytes, new Uint8Array(5)])
  assert.deepEqual(parseHeaderOnly(padded.subarray(9, -5)), h)
  assert.equal(parseSlp(bytes).n, 0)
  assert.equal(parseSlp(bytes).lastFrame, -1)
})

test('every FrameArrays field has the contracted type and exact float32 value', () => {
  const parsed = parseSlp(fixture([fs(-123), pre(-123), post(-123), fe(-123)]))
  const a = parsed.ports[0].leader
  const expected = { present: 1, state: 300, cid: 7, x: 1.25, y: -23.5, dir: -1,
    pct: 42.125, shield: 54.25, stocks: 3, lastAttack: 13, age: 7.75, airborne: 1,
    lcancel: 2, joyX: 0.125, joyY: -0.25, cX: 0.5, cY: -0.75, trigger: 0.625, buttons: 0x8190 }
  for (const [key, value] of Object.entries(expected)) {
    const Type = key === 'dir' ? Int8Array : ['state', 'buttons'].includes(key) ? Uint16Array :
      ['present', 'cid', 'stocks', 'lastAttack', 'airborne', 'lcancel'].includes(key) ? Uint8Array : Float32Array
    assert.ok(a[key] instanceof Type, key)
    assert.deepEqual(arr(a[key]), [value], key)
  }
  assert.equal(parsed.firstFrame, -123); assert.equal(parsed.n, 1)
  assert.deepEqual(parsed.warnings, [])
})

test('pre and post overwrite independently; rows retain all rollback emissions', () => {
  const parsed = parseSlp(fixture([
    fs(-123), pre(-123), post(-123), fe(-123), fs(-122), pre(-122), post(-122), fe(-122),
    fs(-123), pre(-123, 0, 0, 2), post(-123, 0, 0, 3), fe(-123), post(-123, 0, 0, 4),
  ]))
  assert.deepEqual(arr(parsed.rowFids), [-123, -122, -123])
  assert.equal(parsed.rows, 3); assert.equal(parsed.n, 2)
  assert.deepEqual(arr(parsed.ports[0].leader.x), [5.25, 1.25])
  assert.deepEqual(arr(parsed.ports[0].leader.joyX), [2.125, 0.125])
})

test('four ports preserve slot order, teams and independent leader/follower keys', () => {
  const events = [fs(0)]
  for (let port = 0; port < 4; port++) events.push(pre(0, port, 0, port), post(0, port, 0, port))
  events.push(pre(0, 3, 1, 8), post(0, 3, 1, 8), fe(0))
  const parsed = parseSlp(fixture(events, { players: [0, 1, 2, 3], teams: true }))
  assert.deepEqual(parsed.start.players.map(p => p.team), [0, 1, 0, 1])
  assert.deepEqual(parsed.ports.map(p => p.port), [0, 1, 2, 3])
  assert.deepEqual(parsed.ports.map(p => p.leader.x[0]), [1.25, 2.25, 3.25, 4.25])
  assert.equal(parsed.ports[3].follower.x[0], 9.25)
  assert.equal(parsed.ports[3].follower.joyX[0], 8.125)
  assert.equal(parsed.rows, 1)
})

test('gaps carry values with present=0, including followers and inputs', () => {
  const parsed = parseSlp(fixture([fs(-3), pre(-3), post(-3), pre(-3, 0, 1), post(-3, 0, 1), fe(-3),
    fs(-1), pre(-1), post(-1, 0, 0, 2), fe(-1)]))
  assert.deepEqual(arr(parsed.ports[0].leader.present), [1, 0, 1])
  assert.deepEqual(arr(parsed.ports[0].leader.x), [1.25, 1.25, 3.25])
  const fol = parsed.ports[0].follower
  assert.deepEqual(arr(fol.present), [1, 0, 0])
  assert.deepEqual(arr(fol.joyX), [0.125, 0.125, 0.125])
  assert.equal(parsed.ports[1].follower, null)
})

test('frame pages support earlier frames, gaps and frames across page boundaries', () => {
  const parsed = parseSlp(fixture([post(1025), post(-1, 0, 0, 1), post(0, 0, 0, 2)]))
  assert.equal(parsed.firstFrame, -1); assert.equal(parsed.lastFrame, 1025)
  assert.deepEqual(arr(parsed.rowFids), [1025, -1, 0])
  assert.equal(parsed.ports[0].leader.x[1026], 1.25)
  assert.equal(parsed.ports[0].leader.x[1025], 3.25)
})

test('Ice Climbers retains an all-absent follower when Nana never emits', () => {
  const parsed = parseSlp(fixture([post(0), post(1)], { startEdit: gs => { gs[0x65] = 14 } }))
  assert.deepEqual(arr(parsed.ports[0].follower.present), [0, 0])
  assert.deepEqual(arr(parsed.ports[0].follower.x), [0, 0])
})

test('without Frame Start, rowFids uses the first present port even if other ports emit first', () => {
  const parsed = parseSlp(fixture([post(0, 2), post(0), post(1), post(1, 2), post(0)], { version: [2, 1, 0] }))
  assert.deepEqual(arr(parsed.rowFids), [0, 1, 0])
  assert.equal(parsed.rows, 3)
})

test('items use last complete block, including empty corrections, and preserve later frames', () => {
  const parsed = parseSlp(fixture([
    fs(0), item(0, 1), item(0, 2), fe(0), fs(1), item(1, 1, { x: 9 }), fe(1),
    fs(0), fe(0), fs(2), item(2, 1, { x: 10 }), fe(2),
  ]))
  assert.equal(parsed.items.length, 1)
  const t = parsed.items[0]
  assert.deepEqual([t.spawn, t.type, t.owner, t.start], [1, 54, 2, 1])
  assert.deepEqual(arr(t.x), [9, 10]); assert.deepEqual(arr(t.vx), [3.125, 3.125])
  assert.deepEqual(arr(t.vy), [-0.625, -0.625]); assert.deepEqual(arr(t.dir), [-1, -1])
  assert.ok(t.x instanceof Float32Array); assert.ok(t.state instanceof Uint8Array)
})

test('spawn reuse splits on gaps and type changes; NaN/zero item facing is zero', () => {
  const parsed = parseSlp(fixture([
    fs(0), item(0, 0xFFFFFFFF, { dir: NaN }), fe(0), fs(1), fe(1),
    fs(2), item(2, 0xFFFFFFFF, { dir: 0 }), fe(2),
    fs(3), item(3, 0xFFFFFFFF, { type: 55, dir: 1 }), fe(3),
  ]))
  assert.deepEqual(parsed.items.map(t => [t.spawn, t.start, t.type, t.dir[0]]),
    [[0xFFFFFFFF, 0, 54, 0], [0xFFFFFFFF, 2, 54, 0], [0xFFFFFFFF, 3, 55, 1]])
})

test('no-Frame-Start item fallback keeps last event per spawn, without losing other items', () => {
  const parsed = parseSlp(fixture([item(0, 1), item(0, 2), item(0, 1, { x: 8 }), item(1, 1)]))
  assert.equal(parsed.items.length, 2)
  assert.deepEqual(arr(parsed.items.find(t => t.spawn === 1).x), [8, 1.25])
})

test('stage events dedupe per key and sort by frame; they preserve float32s', () => {
  const parsed = parseSlp(fixture([fod(3, 1, 2.125), fod(0, 0, 3.5), fod(3, 1, 4.75),
    stadium(4, 3, 6), stadium(2, 2, 9), stadium(4, 5, 3)]))
  assert.deepEqual(parsed.stage, { fod: [[0, 0, 3.5], [3, 1, 4.75]], stadium: [[2, 2, 9], [4, 5, 3]] })
})

test('version gates ignore newer bytes even when the payload contains them', () => {
  for (const version of [[0, 1, 0], [0, 2, 0], [1, 9, 9], [2, 0, 0], [3, 0, 0], [3, 5, 9], [3, 6, 0], [3, 17, 9]]) {
    const parsed = parseSlp(fixture([pre(0), post(0), item(0), fod(0, 0, 8), stadium(0, 2, 3),
      event(0x39, 6, [['Uint8', 1, 7], ['Int8', 2, 2]])], { version, startEdit: gs => {
      gs.set([65, 0], 0x1A5); gs.set([66, 0], 0x221)
    } }))
    const a = parsed.ports[0].leader
    assert.equal(a.age[0], version[0] === 0 && version[1] === 1 ? 0 : 7.75)
    assert.equal(a.airborne[0], version[0] < 2 ? 0 : 1)
    assert.equal(a.lcancel[0], version[0] < 2 ? 0 : 2)
    assert.equal(parsed.end.lrasInitiator, version[0] < 2 ? null : 2)
    assert.equal(parsed.items.length, version[0] < 3 ? 0 : 1)
    if (parsed.items.length) assert.equal(parsed.items[0].owner, version[1] < 6 ? -1 : 2)
    assert.deepEqual(parsed.stage, { fod: [], stadium: [] })
    assert.equal(parsed.start.players[0].code, version[0] === 3 && version[1] >= 9 ? 'B' : null)
  }
})

test('short legacy post/item/start/end payloads gate optional fields by size', () => {
  const parsed = parseSlp(fixture([post(0, 0, 0, 0, 33), item(0, 1, { size: 37 }), event(0x39, 1, [['Uint8', 1, 2]])],
    { sizes: { 0x36: 0x140, 0x38: 33, 0x3B: 37, 0x39: 1 } }))
  const a = parsed.ports[0].leader
  assert.deepEqual([a.age[0], a.airborne[0], a.lcancel[0]], [0, 0, 0])
  assert.equal(parsed.items[0].owner, -1)
  assert.equal(parsed.start.players[0].name, null)
  assert.deepEqual(parsed.end, { method: 2, lrasInitiator: null })
})

test('each pre field is independently bounded by payload size', () => {
  const full = pre(0)
  for (const size of [6, 27, 28, 32, 36, 40, 44, 49, 50]) {
    const parsed = parseSlp(fixture([full.slice(0, size + 1), post(0)], { sizes: { 0x37: size } }))
    const a = parsed.ports[0].leader
    for (const [key, end, val] of [['joyX', 28, 0.125], ['joyY', 32, -0.25], ['cX', 36, 0.5],
      ['cY', 40, -0.75], ['trigger', 44, 0.625], ['buttons', 50, 0x8190]]) assert.equal(a[key][0], size >= end ? val : 0)
  }
})

test('post facing zero is +1; absent LRAS is null and present initiator is zero-based', () => {
  const p = post(0); new DataView(p.buffer).setFloat32(0x12, 0)
  const parsed = parseSlp(fixture([p, event(0x39, 6, [['Uint8', 1, 7], ['Int8', 2, 0]])]))
  assert.equal(parsed.ports[0].leader.dir[0], 1)
  assert.equal(parsed.end.lrasInitiator, 0)
  assert.equal(parseSlp(fixture([event(0x39, 6, [['Int8', 2, -1]])])).end.lrasInitiator, null)
})

test('splitters and declared unknown/zero-length commands are skipped', () => {
  const parsed = parseSlp(fixture([event(0x10, 516), event(0x50, 0), post(0)]))
  assert.equal(parsed.n, 1); assert.deepEqual(parsed.warnings, [])
})

test('zero raw length recovers at the final footer marker without walking metadata', () => {
  const footer = new Uint8Array([85, 8, 109, 101, 116, 97, 100, 97, 116, 97, 123, 125, 125])
  const bytes = fixture([post(0)], { rawLength: 0, footer })
  assert.equal(parseHeaderOnly(bytes).rawLength, bytes.length - footer.length - 15)
  const parsed = parseSlp(bytes)
  assert.equal(parsed.n, 1); assert.equal(parsed.warnings.length, 1)
  const unfinished = parseSlp(fixture([post(0)], { rawLength: 0 }))
  assert.equal(unfinished.n, 1); assert.match(unfinished.warnings[0], /unfinished/)
})

test('unknown command, truncated event and short event retain clean prefix with warnings', () => {
  for (const bytes of [fixture([post(0), new Uint8Array([0xFE]), post(1)]),
    fixture([post(0), post(1)]).slice(0, -7), fixture([post(0), event(0x3F, 2)], { sizes: { 0x3F: 2 } })]) {
    const parsed = parseSlp(bytes)
    assert.equal(parsed.n, 1); assert.ok(parsed.warnings.length > 0)
  }
})

test('an incomplete corrected item block preserves the previous completed one', () => {
  const parsed = parseSlp(fixture([fs(0), item(0, 1), fe(0), fs(0), item(0, 2)]))
  assert.deepEqual(parsed.items.map(t => t.spawn), [1])
  assert.match(parsed.warnings[0], /incomplete item block/)
})

test('corrupt frame spans cannot force enormous dense allocations', () => {
  const parsed = parseSlp(fixture([post(0), post(2147483647)]))
  assert.equal(parsed.n, 1); assert.match(parsed.warnings[0], /unreasonable frame span/)
})

test('invalid ports, followers and platforms do not contaminate the frame range', () => {
  for (const bad of [post(100, 4), post(100, 1), post(100, 0, 2), fod(100, 2, 3)]) {
    const parsed = parseSlp(fixture([post(0), bad]))
    assert.equal(parsed.n, 1); assert.match(parsed.warnings[0], /invalid/)
  }
})

test('post version/size boundaries gate age, airborne and lcancel separately', () => {
  for (const size of [33, 36, 37, 46, 47, 50, 51]) {
    const p = post(0).slice(0, size + 1)
    const a = parseSlp(fixture([p], { sizes: { 0x38: size } })).ports[0].leader
    assert.equal(a.age[0], size >= 37 ? 7.75 : 0)
    assert.equal(a.airborne[0], size >= 47 ? 1 : 0)
    assert.equal(a.lcancel[0], size >= 51 ? 2 : 0)
  }
})

test('item owner, stage events, and netplay strings honor introduction version boundaries', () => {
  for (const version of [[3, 8, 9], [3, 9, 0], [3, 17, 9], [3, 18, 0], [4, 0, 0]]) {
    const parsed = parseSlp(fixture([fod(0, 0, 1.5), stadium(0, 2, 9)], {
      version, startEdit: gs => { gs.set([65, 0], 0x1A5); gs.set([66, 0], 0x221) },
    }))
    assert.equal(parsed.start.players[0].name, version[0] > 3 || version[1] >= 9 ? 'A' : null)
    assert.equal(parsed.start.players[0].code, version[0] > 3 || version[1] >= 9 ? 'B' : null)
    assert.equal(parsed.stage.fod.length, version[0] > 3 || version[1] >= 18 ? 1 : 0)
    assert.equal(parsed.stage.stadium.length, parsed.stage.fod.length)
  }
  for (const size of [41, 42]) {
    const parsed = parseSlp(fixture([item(0, 1, { size })], { sizes: { 0x3B: size } }))
    assert.equal(parsed.items[0].owner, size >= 42 ? 2 : -1)
  }
})

test('signed zero and non-round float32 inputs survive without rounding', () => {
  const p = post(0), r = pre(0)
  new DataView(p.buffer).setFloat32(0xA, -0)
  new DataView(p.buffer).setFloat32(0xE, 1 / 3)
  new DataView(r.buffer).setFloat32(0x29, 0.123456789)
  const a = parseSlp(fixture([r, p])).ports[0].leader
  assert.ok(Object.is(a.x[0], -0))
  assert.equal(a.y[0], Math.fround(1 / 3))
  assert.equal(a.trigger[0], Math.fround(0.123456789))
})

test('unusable headers/tables throw SlpError; header-only ignores corrupt frame tails', () => {
  const good = fixture([post(0)])
  for (const input of [null, new Uint8Array(), good.slice(0, 20), (() => {
    const b = good.slice(); b[0] = 0; return b
  })(), (() => { const b = good.slice(); b[16] = 2; return b })(), (() => {
    const b = good.slice(); new DataView(b.buffer).setInt32(11, -1); return b
  })()]) assert.throws(() => parseSlp(input), SlpError)
  const bytes = fixture([new Uint8Array([0xFE])])
  assert.equal(parseHeaderOnly(bytes).start.stage, 31)
  assert.match(parseSlp(bytes).warnings[0], /unknown command/)
})

test('every truncation after GameStart is recoverable and preserves array shapes', () => {
  const headLength = fixture().length
  const bytes = fixture([fs(0), pre(0), post(0), item(0), fe(0), fs(1), pre(1), post(1), fe(1)])
  for (let end = headLength; end < bytes.length; end++) {
    const parsed = parseSlp(bytes.subarray(0, end))
    assert.ok(parsed.warnings.length)
    for (const p of parsed.ports) for (const value of Object.values(p.leader)) assert.equal(value.length, parsed.n)
  }
})
