import test from 'node:test'
import assert from 'node:assert/strict'
import { animCandidates, reflectorAt, heldFrames, createRenderer, hiddenAt, shieldAt } from './meleeRender.js'

const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg || ''} ${a} != ${b}`)

test('the reflector is the game effect: held band on its own pulse, start and reflect turning', () => {
  for (const state of [360, 361, 362, 364, 365, 366, 367, 369]) {
    assert.ok(reflectorAt(1, state, { age: 1 }), `Fox ${state}`)
    assert.ok(reflectorAt(22, state, { age: 1 }), `Falco ${state}`)
  }
  for (const state of [363, 368, 359, 370]) assert.equal(reflectorAt(1, state, { age: 1 }), null)
  assert.equal(reflectorAt(0, 361), null)   // Mario's down-B is not a reflector
  // held: EfFxData.dat model 0, corners 8.2686 out, hole half that, scaled by
  // the pulse RAM shows from the first held frame, times the model scale
  const pulse = [0.422, 0.751, 0.751, 1.0199, 1.0199, 0.422, 0.422]
  pulse.forEach((p, k) => {
    const fox = reflectorAt(1, 361, { held: k }).pieces[0]
    assert.equal(fox.shape, 'band')
    near(fox.r, 8.2686 * p * 0.96, `Fox held ${k}`); near(fox.hole, fox.r / 2)
    near(reflectorAt(22, 366, { held: k }).pieces[0].r, 8.2686 * p * 1.1, `Falco held ${k}`)
  })
  // centre: the HipN joint read in RAM, model units x scale (Falco's equal Fox's)
  const g = reflectorAt(1, 361, { held: 0 }), a = reflectorAt(22, 366, { held: 0 })
  near(g.dx, -1.27 * 0.96); near(g.dy, 5.62 * 0.96); near(a.dx, -0.13 * 1.1); near(a.dy, 7.3 * 1.1)
  // start: the white half hexagon turns 60 degrees an action frame; reflect:
  // every 2 frames, spawned on frame 1 and gone after 11
  const deg = piece => Math.round(piece.from * 180 / Math.PI)
  assert.deepEqual([1, 2, 3].map(age => deg(reflectorAt(1, 360, { age }).pieces[1])), [270, 330, 390])
  assert.deepEqual([1, 2, 3, 4].map(age => deg(reflectorAt(1, 362, { age }).pieces[0])), [30, 90, 90, 150])
  assert.equal(reflectorAt(1, 362, { age: 0 }), null)
  assert.equal(reflectorAt(1, 367, { age: 12 }), null)
})

test('the held reflector keeps its clock through a turn and restarts after a reflect', () => {
  const s = [14, 360, 360, 361, 361, 364, 364, 361, 362, 362, 361]
  assert.equal(heldFrames(s, 3), 0)
  assert.equal(heldFrames(s, 7), 4)                  // turning keeps the effect running
  assert.equal(heldFrames(s, 10), 0)                 // a reflect spawns a new one
  assert.equal(heldFrames(s, 2), null)               // not held
  assert.equal(heldFrames([361, 361, 361], 2), null) // began before the rows: unknown
})

test('the shield bubble sits on the shield bone, tilted by the smoothed stick and sized by health and depth', () => {
  // Falco (22), from the vanilla ISO: untilted centre (2.998, 9.9), full tilt up
  // (90 degrees) (1.641, 16.503), radius 1.1 x 12.5 = 13.75 at full size
  const n = 40, rows = (jy, last = 179) => ({
    state: [14, 178, 178, 178, 178, 178, 178, 178, 178, ...Array(n - 9).fill(179)].map((v, k) => k === n - 1 ? last : v),
    joyx: Array(n).fill(0), joyy: Array(n).fill(jy), dir: Array(n).fill(-1),
    shield: Array(n).fill(60), lt: Array(n).fill(100), age: Array(n).fill(3),
  })
  const still = shieldAt(22, rows(0), n - 1)
  near(still.dx, -2.998, 'facing left mirrors x'); near(still.dy, 9.9)
  near(still.r, 13.75 * ((1 - 0.15) * 1 * 0.5 + 0.15), 'hard press: half the size factor')
  // stick held up: angle and tilt each move halfway per frame, so 30 frames in
  // the bubble is at the full-tilt centre
  const up = shieldAt(22, rows(1), n - 1)
  assert.ok(Math.abs(up.dx + 1.641) < 1e-3 && Math.abs(up.dy - 16.503) < 1e-3, `${up.dx} ${up.dy}`)
  // shieldstun: the GuardDamage pose by action frame, the tilt dropped
  const stun = shieldAt(22, rows(1, 181), n - 1)
  near(stun.dy, 9.903)
  // no bubble in GuardOff, nor outside a guard
  assert.equal(shieldAt(22, rows(0, 180), n - 1), null)
  assert.equal(shieldAt(22, rows(0), 0), null)
})

test("the game's own animation for a state comes first (Pl*.dat action table)", async () => {
  const charmaps = JSON.parse(await import('node:fs').then(fs => fs.readFileSync(new URL('../../../../backend/tracker/tools/charmaps.json', import.meta.url), 'utf8')))
  // Samus's super missile (352) plays her action SpecialAir, not the homing
  // missile charmaps names; Peach's air turnip pull (353) is the file's SpecialN
  assert.equal(animCandidates(charmaps, 13, 352)[0], 'SpecialAir')
  assert.equal(animCandidates(charmaps, 9, 353)[0], 'SpecialN')
  // a thrown victim's animation is the thrower's, never taken from its own table
  assert.notEqual(animCandidates(charmaps, 9, 239)[0], 'TPeachThrowF')
})

// A two-character charmap shaped like tools/charmaps.json, with only what the
// name resolution reads.
const charmaps = {
  actionNameById: Object.assign([], { 14: 'Wait', 40: 'SquatWait', 239: 'ThrownF', 275: 'CaptureCaptain', 342: 'Unused' }),
  chars: {
    15: { animationMap: {}, specialsMap: {} },                 // Jigglypuff: no SquatWait mapping
    14: { animationMap: { Wait: 'Wait1' }, specialsMap: { 342: 'Guard' } },  // Yoshi shield special
  },
}

test('mapped names come first, fallbacks after', () => {
  assert.deepEqual(animCandidates(charmaps, 15, 40), ['SquatWait', 'SquatWait1'])
  assert.deepEqual(animCandidates(charmaps, 15, 239), ['ThrownF', 'DamageFlyN'])
  assert.deepEqual(animCandidates(charmaps, 15, 275), ['CaptureCaptain', 'CaptureWaitHi'])
  assert.deepEqual(animCandidates(charmaps, 14, 342), ['Guard', 'GuardOn'])
})

test('names with geometry get no fallback; unknown characters get nothing', () => {
  assert.deepEqual(animCandidates(charmaps, 14, 14), ['Wait1', 'Wait'])
  assert.deepEqual(animCandidates(charmaps, 99, 14), [])
})

// The common motion table (decomp ft/ftmotionstates.c) plays StopCeil for
// FlyReflectCeil (248); the zips have StopCeil, not FlyReflectCeil.
const cm2 = {
  actionNameById: Object.assign([], { 14: 'Wait', 30: 'FallF', 248: 'FlyReflectCeil', 264: 'AppealR', 266: 'ShoulderedWait',
    293: 'BarrelWait', 325: 'DamageIce', 356: 'Unused', 364: 'Unused' }),
  chars: {
    1: { scale: 1, animationMap: { Wait: 'Wait1', AppealR: 'Appeal' }, specialsMap: {} },
    2: { scale: 1, animationMap: { Wait: 'Wait1', AppealR: 'Appeal' }, specialsMap: {} },
    7: { scale: 1, animationMap: {}, specialsMap: { 356: 'Unsupported' } },
    22: { scale: 1, animationMap: {}, specialsMap: { 364: 'SpecialLw2' } },
  },
}
function recorder() {
  const calls = []
  return { calls, save() {}, restore() {}, setTransform() {}, translate() {}, scale() {},
    fill(path) { calls.push(path.d) }, stroke() {} }
}
globalThis.Path2D ??= class { constructor(d) { this.d = d } }

test('game animations and stand-ins replace the dot', () => {
  const r = createRenderer(cm2)
  const base = { age: 0, x: 0, y: 0, facing: 1, fill: '#fff', view: { S: 1, ox: 0, oy: 0 }, dpr: 1 }
  const draw = (cid, state, anims, extra = {}) => { const c = recorder(); const ok = r.draw(c, { [cid]: anims }, { ...base, cid, state, ...extra }); return [ok, c.calls] }
  // Fox tumbling into a ceiling: StopCeil
  assert.deepEqual(draw(1, 248, { StopCeil: ['M stopceil'] }), [true, ['M stopceil']])
  assert.ok(animCandidates(cm2, 1, 248).includes('StopCeil'))
  // Captain Falcon's taunt: his zip names it AppealR
  assert.deepEqual(draw(2, 264, { AppealR: ['M appeal'] }), [true, ['M appeal']])
  // carried by Donkey Kong: the held-victim pose
  assert.deepEqual(draw(1, 266, { CaptureWaitHi: ['M held'] }), [true, ['M held']])
  // Falco's reflector turn: the decomp's SpecialLwLoop (data/motionNames.js)
  assert.deepEqual(draw(22, 364, { SpecialLwLoop: ['M loop'] }), [true, ['M loop']])
  // frozen in ice (no animation of its own): the pose before it, held
  const states = [14, 30, 325, 325], ages = [5, 7, 0, 1]
  assert.deepEqual(draw(1, 325, { Wait1: ['w0', 'w1', 'w2'], FallF: ['f0', 'f1'] }, { states, ages, idx: 3 }), [true, ['f1']])
  // in a barrel or mid-vanish the game hides the fighter: nothing is drawn
  assert.deepEqual(draw(1, 293, { Wait1: ['w0'] }), ['hidden', []])
  assert.deepEqual(draw(7, 356, { SpecialHiStart: ['s'] }), ['hidden', []])
  assert.equal(hiddenAt(7, 357), false)
})

test('a "frameN" entry is that frame of the same animation; an empty pose draws nothing and no dot', () => {
  const r = createRenderer(cm2)
  const base = { x: 0, y: 0, facing: 1, fill: '#fff', view: { S: 1, ox: 0, oy: 0 }, dpr: 1 }
  const draw = (anims, age) => { const c = recorder(); const ok = r.draw(c, { 1: anims }, { ...base, cid: 1, state: 14, age }); return [ok, c.calls] }
  // Fox's Wait1 loops back to entry 0 at 120 in the zip: "frame0"
  assert.deepEqual(draw({ Wait1: ['M a', 'M b', 'frame0', 'frame1'] }, 3), [true, ['M b']])
  // Mewtwo's air dodge: entry 5 is empty, 6.. are "frame5"
  assert.deepEqual(draw({ Wait1: ['M a', '', 'frame1'] }, 1), ['empty', []])
  assert.deepEqual(draw({ Wait1: ['M a', '', 'frame1'] }, 2), ['empty', []])
})

test("a fighter in Yoshi's egg is drawn as the egg, not hidden and not a dot", () => {
  const r = createRenderer(cm2)
  let pts = [], fills = []
  const ctx = { save() {}, restore() {}, setTransform() {}, beginPath() { pts = [] }, closePath() {}, stroke() {}, arc() {},
    moveTo(x, y) { pts.push([x, y]) }, lineTo(x, y) { pts.push([x, y]) }, fill() { fills.push([this.fillStyle, pts.slice()]) } }
  // Fox (egg size 1.9, PlYs egg x victim ftCo_DatAttrs +0xBC), 4 frames into the
  // egg: s = 1.9 x (0.55 + 0.45 x 4/20); bottom on the recorded position
  const states = [14, 277, 277, 277, 277], o = { cid: 1, state: 277, age: 3, x: 10, y: 0, facing: 1, fill: '#f00',
    view: { S: 1, ox: 0, oy: 0 }, dpr: 1, states, idx: 4 }
  assert.equal(r.draw(ctx, { 1: { Wait1: ['M a'] } }, o), 'egg')
  const [colour, shell] = fills[0], s = 1.9 * (0.55 + 0.45 * 4 / 20)
  assert.equal(colour, '#dcdccc')
  const ys = shell.map(p => p[1]), xs = shell.map(p => p[0])
  assert.ok(Math.abs(Math.min(...ys)) < 1e-9 && Math.abs(Math.max(...ys) - 6.12 * s) < 0.05 * s, `${Math.min(...ys)} ${Math.max(...ys)}`)
  assert.ok(Math.abs(Math.max(...xs) - Math.min(...xs) - 5.48 * s) < 0.1 * s)
  assert.equal(hiddenAt(1, 277), false)
  assert.equal(r.draw(ctx, {}, { ...o, state: 332 }), 'egg')   // Kirby's copy
})

test("Bowser's Whirling Fortress is drawn as the shell the game swaps in, not the pack's full body", () => {
  const r = createRenderer({ actionNameById: [], chars: { 5: { scale: 1, animationMap: {}, specialsMap: { 359: 'SpecialHi' } } } })
  let pts = [], fills = []
  const ctx = { save() {}, restore() {}, setTransform() {}, translate() {}, scale() {}, beginPath() { pts = [] }, closePath() {},
    moveTo(x, y) { pts.push([x, y]) }, lineTo(x, y) { pts.push([x, y]) }, fill(p) { fills.push([p, pts.slice()]) } }
  const o = { cid: 5, state: 359, age: 38, x: 10, y: 0, facing: -1, fill: '#f00', view: { S: 1, ox: 0, oy: 0 }, dpr: 1 }
  const anims = { 5: { SpecialHi: Array(81).fill('M 0 0') } }
  assert.equal(r.draw(ctx, anims, o), 'shell')
  const shell = fills[0][1], ys = shell.map(p => p[1]), xs = shell.map(p => p[0])
  // the shell stays above the floor (the pack's body reaches 4 below it)
  assert.ok(Math.min(...ys) > 0 && Math.max(...ys) < 21 && Math.min(...xs) > 10 - 14 && Math.max(...xs) < 10 + 14)
  // the wind-up (action frames 0-5) and the end lag (50-) show the whole body
  fills = []
  assert.notEqual(r.draw(ctx, anims, { ...o, age: 3 }), 'shell')
  assert.notEqual(r.draw(ctx, anims, { ...o, age: 60 }), 'shell')
  assert.notEqual(r.draw(ctx, anims, { ...o, state: 360, age: 6 }), 'shell')
})
