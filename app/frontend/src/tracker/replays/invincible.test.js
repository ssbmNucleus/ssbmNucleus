import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { invincibleAt, invincibleOutline, OUTLINE } = await import('./invincible.js')
const { createRenderer } = await import('./meleeRender.js')
const { paintFrame } = await import('./litePaint.js')
const KO = (await import('./data/koEffects.js')).default
const F = KO.flash

const row = (n, at) => Array.from({ length: n }, (_, i) => at(i))
const on = (states, from, to) => row(to - from, k => invincibleAt(states, from + k))

// dead (2) until 5, asleep (11) until 20, Rebirth (12) from 20, RebirthWait
// (13) from 80, falling (29) from 150, dead again at 400
const states = row(420, i => (i < 5 ? 2 : i < 20 ? 11 : i < 80 ? 12 : i < 150 ? 13 : i < 400 ? 29 : 1))

test('the timers come from the game', () => {
  assert.equal(F.enter[253], 30, 'CliffWait')
  assert.equal(F.enter[219], 8, 'a throw')
  assert.equal(F.leave[13], 120, 'leaving the respawn platform')
  assert.equal(F.enter[202], 14, 'a wall tech')
  assert.equal(F.enter[247], 15, 'tumbling into a wall')
  assert.equal(F.leave[277], 14, "leaving Yoshi's egg: Yoshi's 14 frames")
  assert.equal(F.colours, undefined, 'the flicker is not drawn, so its colours do not ship')
})

test('on the platform and for 120 frames after it, steadily, then not', () => {
  assert.deepEqual(on(states, 0, 20), row(20, () => false), 'dead or asleep')
  assert.ok(on(states, 20, 150).every(Boolean), 'Rebirth and RebirthWait')
  assert.ok(on(states, 150, 270).every(Boolean), 'the 120 frames after leaving it, from the frame it leaves')
  assert.ok(on(states, 270, 420).every(v => !v), 'then nothing, and nothing once dead again')
})

test('an input held as Rebirth ends drops the fighter straight out: the same 120 frames', () => {
  // Rebirth (12) from 20 straight to falling (29) at 80: RebirthWait began and ended in one frame
  // (ftCo_RebirthWait_IASA), so the replay never shows 13 (RAM: invulnerable 120 frames from 80)
  const dropped = row(300, i => (i < 20 ? 11 : i < 80 ? 12 : 29))
  assert.equal(F.leave[12], F.leave[13])
  assert.ok(on(dropped, 20, 200).every(Boolean), 'on the platform, then the 120 frames')
  assert.ok(on(dropped, 200, 300).every(v => !v))
})

test('doubles: every player and Nana get the outline, in team colours too (paintFrame, 4 players)', () => {
  // four players in a team game, each respawning at its own time; two drop straight out of
  // Rebirth (12 -> 29), one waits on the platform (12 -> 13 -> 29), one is Ice Climbers whose
  // Nana respawns with Popo
  const n = 400, life = at => row(n, i => (i < at ? 11 : i < at + 60 ? 12 : 29))
  const waited = row(n, i => (i < 40 ? 11 : i < 100 ? 12 : i < 160 ? 13 : 29))
  const state = [life(10), life(30), waited, life(50)]
  const fill = v => state.map(() => row(n, () => v))
  const b = {
    meta: { stage: 31, start_frame: 0, n, teams: true, players: [0, 0, 1, 1].map((team, i) => ({ team, physical_port: i })) },
    frames: { x: state.map((_, i) => row(n, () => -60 + 40 * i)), y: fill(10), air: fill(1), state, cat: fill(0),
      cid: [fill(0)[0], fill(0)[0], fill(0)[0], row(n, () => 14)], age: fill(0), dir: fill(1),
      fol: [{ of: 3, x: row(n, () => 70), y: row(n, () => 10), state: life(50), cid: row(n, () => 10), age: row(n, () => 0), dir: row(n, () => 1) }] },
  }
  const ctx = new Proxy({ canvas: { width: 640, height: 480 }, globalAlpha: 1 }, {
    get: (t, k) => (k in t ? t[k] : k.startsWith('create') ? () => ({ addColorStop() {} }) : () => {}),
    set: (t, k, v) => { t[k] = v; return true },
  })
  const outlined = (idx) => {
    const drawn = []
    paintFrame(ctx, b, {}, { draw: (c, a, o) => { drawn.push([o.x, !!o.outline, o.fill]); return true } }, idx, { S: 2, ox: 320, oy: 300 }, 1)
    return drawn.sort((p, q) => p[0] - q[0])
  }
  // idx 150: players 1, 2 and 4 (and Nana) are 60-90 frames out of Rebirth, player 3 waits on the platform
  const at150 = outlined(150)
  assert.deepEqual(at150.map(d => d[1]), [true, true, true, true, true], JSON.stringify(at150))
  assert.equal(new Set(at150.slice(0, 4).map(d => d[2])).size, 2, 'two team colours')
  // idx 215: players 1 and 2 are past their 120 frames (from 70 and 90); player 3 (out of RebirthWait
  // at 160) and player 4 with Nana (out at 110) are not
  assert.deepEqual(outlined(215).map(d => d[1]), [false, false, true, true, true])
  // idx 300: everyone's are over (player 3 left RebirthWait at 160: until 279)
  assert.deepEqual(outlined(300).map(d => d[1]), [false, false, false, false, false])
})

test('a ledge grab: 30 frames from the first frame of CliffWait', () => {
  // falling (29), CliffCatch (252) at 10, CliffWait (253) from 17
  const ledge = row(80, i => (i < 10 ? 29 : i < 17 ? 252 : 253))
  assert.ok(on(ledge, 0, 17).every(v => !v))
  assert.ok(on(ledge, 17, 47).every(Boolean))
  assert.ok(on(ledge, 47, 80).every(v => !v))
})

test('a throw: the thrower for 8 frames; a wall tech for 14', () => {
  const thrower = row(40, i => (i < 10 ? 212 : 219))
  assert.ok(!invincibleAt(thrower, 9) && on(thrower, 10, 18).every(Boolean) && !invincibleAt(thrower, 18))
  const tech = row(40, i => (i < 10 ? 38 : i < 30 ? 202 : 29))
  assert.ok(on(tech, 10, 24).every(Boolean) && on(tech, 24, 40).every(v => !v))
})

test('a new trigger restarts the timer and the longer one wins', () => {
  // off the platform at 150, grabbing the ledge at 200 (CliffWait at 205), dying at 300
  const s = states.map((v, i) => (i >= 200 && i < 205 ? 252 : i >= 205 && i < 300 ? 253 : i >= 300 ? 1 : v))
  assert.ok(invincibleAt(s, 260) && !invincibleAt(s, 270), "the respawn's 120 frames outlast the ledge's 30")
  const late = states.map((v, i) => (i >= 260 && i < 265 ? 252 : i >= 265 && i < 330 ? 253 : v))
  assert.ok(invincibleAt(late, 290) && !invincibleAt(late, 295), 'a ledge grab late in them runs its own 30')
})

test('the outline is the same steady one throughout, and none without a row', () => {
  assert.equal(invincibleOutline(states, 30), OUTLINE)
  assert.equal(invincibleOutline(states, 200), OUTLINE)
  assert.equal(invincibleOutline(states, 300), null)
  assert.equal(invincibleOutline(undefined, 3), null)
  assert.ok(/^#[0-9a-f]{6}$/i.test(OUTLINE.colour) && OUTLINE.px > 0)
})

test('the renderer strokes the outline under the fill, OUTLINE.px screen pixels outside it', () => {
  globalThis.Path2D ??= class { constructor(d) { this.d = d } }
  const charmaps = { actionNameById: ['Wait'], chars: { 1: { scale: 1.5, animationMap: {}, specialsMap: {} } } }
  const r = createRenderer(charmaps)
  const record = () => {
    const ops = []
    return { ops, save() {}, restore() {}, setTransform() {}, translate() {}, scale() {},
      stroke() { ops.push(['stroke', this.lineWidth, this.strokeStyle]) }, fill() { ops.push(['fill', this.fillStyle]) } }
  }
  const o = { cid: 1, state: 0, age: 0, x: 0, y: 0, facing: 1, fill: '#ff7a66', view: { S: 4, ox: 200, oy: 150 }, dpr: 2 }
  const anims = { 1: { Wait: ['M0 0L10 0L10 10Z'] } }
  const ctx = record()
  assert.equal(r.draw(ctx, anims, { ...o, outline: OUTLINE }), true)
  assert.deepEqual(ctx.ops.map(op => op[0]), ['stroke', 'fill'])
  // path units are S x dpr x scale / 10 device pixels; the line is 2 x px x dpr
  // device pixels wide, so px x dpr of it shows outside the fill
  assert.ok(Math.abs(ctx.ops[0][1] * 4 * 2 * 1.5 * 0.1 - 2 * OUTLINE.px * 2) < 1e-9)
  assert.equal(ctx.ops[0][2], OUTLINE.colour)
  const plain = record()
  r.draw(plain, anims, o)
  assert.deepEqual(plain.ops, [['fill', '#ff7a66']])
})
