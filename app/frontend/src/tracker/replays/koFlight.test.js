import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { screenPoint, starDepth, koFlightsAt, viewCamera, drawKoFlights } = await import('./koFlight.js')
const { RecordingContext } = await import('../../../../../tools/liteaudit/recording_context.mjs')
const KO = (await import('./data/koEffects.js')).default

const near = (a, b, tol = 0.01) => a.every((v, i) => Math.abs(v - b[i]) <= tol)

test("the screen KO's camera-space path is the game's (RAM)", () => {
  // values RAM held at these frames of a recorded screen KO (fighter +0x2350)
  for (const [k, want] of [[0, [0, 66.66, -100]], [1, [0, 65.03, -99]], [25, [0, 25.83, -75]], [50, [0, -15, -50]],
    [53, [0, -15, -50]], [54, [0, -14.2, -51]], [55, [0, -13.6, -52]], [70, [0, -27, -67]], [93, [0, -66.1, -90]]]) {
    assert.ok(near(screenPoint(k), want), `frame ${k}: ${screenPoint(k)} vs ${want}`)
  }
})

test("the star KO's depth is the game's (RAM)", () => {
  assert.equal(Math.abs(starDepth(0)), 0)
  assert.ok(Math.abs(starDepth(1) - -2.69) < 0.01)
  assert.equal(starDepth(130), -350)
  assert.equal(starDepth(170), -350)
})

// one fighter star KO'd at 10 (DeadUpStar 4 until 186), the other screen KO'd
// at 50 (DeadUpFall 6 until 101, DeadUpFallHitCamera 7 to 180)
function bundle() {
  const n = 200, row = v => Array.from({ length: n }, () => v)
  const st0 = Array.from({ length: n }, (_, i) => (i < 10 ? 90 : i < 186 ? 4 : 11))
  const st1 = Array.from({ length: n }, (_, i) => (i < 50 ? 88 : i < 101 ? 6 : i < 180 ? 7 : 11))
  return {
    meta: { n, stage: 32, start_frame: 0, players: [{}, {}] },
    frames: { cid: [row(1), row(2)], x: [row(10), row(-20)], y: [Array.from({ length: n }, (_, i) => 200 - i * 0.5), row(200)],
      dir: [row(1), row(-1)], state: [st0, st1], age: [Array.from({ length: n }, (_, i) => i % 20), Array.from({ length: n }, (_, i) => i)] },
    items: [],
  }
}
const view = { S: 3, ox: 480, oy: 300 }
const cam = viewCamera(view, 960, 540, 32)

test('a star KO shrinks into the distance, then twinkles', () => {
  const b = bundle()
  const at = k => koFlightsAt(b, 10 + k, cam).find(f => f.kind === 'star')
  assert.ok(at(0).scale > 0.99 && at(0).state === 38, 'full size at first, tumbling (DamageFall)')
  assert.ok(at(60).scale < at(10).scale && at(130).scale < at(60).scale, 'smaller and smaller')
  assert.ok(at(130).scale > 0.2 && at(130).scale < 0.6)
  assert.equal(at(130).twinkle, undefined)
  assert.equal(at(131).twinkle, 0, 'hidden at 131: the twinkle')
  assert.equal(koFlightsAt(b, 9, cam).length, 0)
})

test('a screen KO comes at the camera, hits it and falls away', () => {
  const b = bundle()
  const at = k => koFlightsAt(b, 50 + k, cam).find(f => f.kind === 'screen')
  assert.ok(at(0).y > cam.cy + 270 / view.S, 'it starts above the view')
  assert.ok(at(50).scale > at(10).scale && at(50).scale > 2, 'big on the camera')
  // on the camera, the pose is held at its last tumbling frame (this row's age is its index)
  assert.deepEqual([at(55).state, at(55).age], [38, 50 + 50])
  assert.ok(at(93))
  assert.equal(at(94), undefined, 'hidden after its fall')
})

test('star KOs are drawn behind (with the twinkle), screen KOs in front', () => {
  const b = bundle()
  const drawn = (idx, layer) => {
    const got = [], ctx = new RecordingContext()
    ctx.canvas = { width: 960, height: 540 }
    drawKoFlights(ctx, b, idx, view, 1, layer, (of, o) => got.push([of, o]))
    return { got, fills: ctx.calls.filter(c => c.op === 'fill' || c.op === 'fillRect').length }
  }
  assert.deepEqual(drawn(80, 'back').got.map(([of]) => of), [0])
  assert.deepEqual(drawn(80, 'front').got.map(([of]) => of), [1])
  // the silhouette is scaled with the view handed to the renderer
  const [, o] = drawn(80, 'front').got[0]
  assert.ok(o.view.S > view.S)
  // the twinkle is painted, not a silhouette
  const tw = drawn(10 + 131, 'back')
  assert.equal(tw.got.length, 0)
  assert.ok(tw.fills > 0)
})
