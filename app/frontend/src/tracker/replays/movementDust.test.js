import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { dustEvents, drawDust, drawDustEffect } = await import('./movementDust.js')
const { RecordingContext } = await import('../../../../../tools/liteaudit/recording_context.mjs')
const DUST = (await import('./data/movementDust.js')).default

// the action-frame time of a fighter's first command of `kind` in `state`
function timeOf(cid, state, kind) {
  const t = DUST.fighters[cid], c = DUST.fighters.common
  let s = t && Object.hasOwn(t, state) ? t[state] : c[state]
  if (typeof s === 'number') s = t && Object.hasOwn(t, s) ? t[s] : c[s]
  const k = DUST.kinds.indexOf(kind)
  const cmd = s.find(x => (typeof x === 'number' ? x & 7 : x[1]) === k)
  return typeof cmd === 'number' ? cmd >> 3 : cmd[0]
}

// Fox (cid 1) standing (14), dashing (20) at 10 facing right, dashing back at
// 20 facing left (a dash dance: the state stays 20, its action frame restarts),
// standing again from 40, then a jump (24 -> 25) at 60 and a landing (42) at 90
function bundle() {
  const n = 120, state = [], age = [], dir = [], x = [], y = []
  for (let i = 0; i < n; i++) {
    let s = 14, a = i, d = 1, yy = 0
    if (i >= 10 && i < 20) { s = 20; a = i - 10 + 1 }
    else if (i >= 20 && i < 40) { s = 20; a = i - 20 + 1; d = -1 }
    else if (i >= 55 && i < 60) { s = 24; a = i - 55 }
    else if (i >= 60 && i < 90) { s = 25; a = i - 60; yy = 10 }
    else if (i >= 90 && i < 100) { s = 42; a = i - 90 }
    state.push(s); age.push(a); dir.push(d); x.push(5 + i * 0.1); y.push(yy)
  }
  const row = v => Array.from({ length: n }, () => v)
  return { meta: { n, stage: 32, start_frame: 0 }, frames: { cid: [row(1)], x: [x], y: [y], dir: [dir], state: [state], age: [age] }, items: [] }
}

test('a command spawns its dust once per run, when the action frame reaches its time', () => {
  const ev = dustEvents(bundle())
  const dash = timeOf(1, 20, 'dash')
  const dashes = ev.filter(e => e.kind === 'dash')
  // the dash at 10 (action frame 1 on its first frame) and the dash back at 20
  assert.deepEqual(dashes.map(e => e.idx), [10 + dash - 1, 20 + dash - 1])
  assert.deepEqual(dashes.map(e => e.facing), [1, -1], 'the dash back faces the other way')
  const jump = ev.find(e => e.kind === 'jump')
  assert.equal(jump.idx, 60 + timeOf(1, 25, 'jump'))
  const landing = ev.find(e => e.kind === 'landing')
  assert.equal(landing.idx, 90 + timeOf(1, 42, 'landing'))
  assert.deepEqual([landing.x, landing.y], [5 + landing.idx * 0.1, 0], 'where the fighter stands when it runs')
  assert.ok(!ev.some(e => e.idx < 10), 'standing spawns nothing')
})

test('every vanilla fighter dashes, jumps and lands with dust', () => {
  const has = (cid, state, kinds) => kinds.some(k => { try { return Number.isInteger(timeOf(cid, state, k)) } catch { return false } })
  for (let cid = 0; cid <= 26; cid++) {
    assert.ok(has(cid, 20, ['dash']) && has(cid, 25, ['jump']), `cid ${cid}: dash and jump`)
    // Bowser's landings shake the camera instead (0x513)
    if (cid === 5) continue
    assert.ok(has(cid, 42, ['landing', 'airlanding']) && has(cid, 43, ['airlanding']), `cid ${cid}: landings`)
  }
})

test('a puff is painted for its frames and not after', () => {
  const b = bundle()
  const view = { S: 4, ox: 320, oy: 240 }
  const fills = idx => {
    const c = new RecordingContext()
    drawDust(c, b, idx, view, 1)
    return c.calls.filter(x => x.op === 'fill' || x.op === 'fillRect').length
  }
  const landing = dustEvents(b).find(e => e.kind === 'landing')
  const fx = DUST.effects.landing
  const life = fx.frames.length
  assert.equal(fills(9), 0, 'nothing before the first dash')
  assert.ok(fills(landing.idx) > 0)
  assert.ok(fills(landing.idx + life - 1) > 0)
  assert.equal(fills(landing.idx + life), 0)
})

test('the dust is mirrored for the other facing', () => {
  // the run turn's puff, as drawn k frames after it spawned facing right and facing left
  const fx = DUST.effects.turn
  const k = fx.frames.findIndex(r => r.length)
  const view = { S: 4, ox: 320, oy: 240 }
  const at = facing => {
    const c = new RecordingContext()
    drawDustEffect(c, { kind: 'turn', x: 0, y: 0, facing }, k, view, 1)
    const t = c.calls.find(x => x.op === 'setTransform')
    return (t.args[4] - view.ox) / view.S
  }
  assert.ok(Math.abs(fx.frames[k][0][1]) > 0.5, 'the sample puff sits off its spawn point')
  assert.ok(Math.abs(at(1) + at(-1)) < 0.01, 'one side is the other mirrored')
  assert.ok(Math.abs(at(fx.facing) - fx.frames[k][0][1]) < 0.01, "the sample's own side as recorded")
})

test('the dust is our own shapes: soft ellipses and rings, no game textures', () => {
  assert.equal(DUST.textures, undefined)
  for (const [kind, fx] of Object.entries(DUST.effects)) {
    for (const row of fx.frames) for (const s of row) {
      assert.ok(s[0] === 0 || s[0] === 1, `${kind}: shape kind`)
      assert.ok(s[3] > 0 && s[4] > 0 && s[6] > 0 && s[6] <= 1, `${kind}: radii and alpha`)
      assert.ok(fx.colours[s[7]], `${kind}: colour`)
      if (s[0] === 1) assert.ok(s[8] > 0, `${kind}: ring width`)
    }
  }
  // the double jump's puff is a ring that grows
  const rings = DUST.effects.airjump.frames.map(r => r.find(s => s[0] === 1)).filter(Boolean)
  assert.ok(rings.length > 2 && rings.at(-1)[3] > rings[0][3])
})
