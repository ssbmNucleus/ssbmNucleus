import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { techEvents, drawTechEffects, drawTechRings } = await import('./techEffects.js')
const { RecordingContext } = await import('../../../../../tools/liteaudit/recording_context.mjs')
const FX = (await import('./data/hitEffects.js')).default

// one fighter: tumbling (88), techs in place at 5, wall techs at 30 facing left
// (the wall on its right), and a wall tech turning into its wall jump at 31
function bundle() {
  const n = 60
  const state = Array.from({ length: n }, (_, i) => (i >= 5 && i < 25 ? 199 : i === 30 ? 202 : i >= 31 && i < 40 ? 203 : 88))
  const row = v => Array.from({ length: n }, () => v)
  return { meta: { n, stage: 32, start_frame: 0 }, frames: { cid: [row(1)], x: [row(10)], y: [row(0)], dir: [row(-1)], state: [state], age: [row(0)] }, items: [] }
}

test('a tech spawns its effect where the game puts it, once per tech', () => {
  const ev = techEvents(bundle())
  assert.deepEqual(ev.map(e => e.idx), [5, 30], 'the wall jump out of a wall tech is the same tech')
  assert.deepEqual([ev[0].x, ev[0].y, ev[0].side], [10, 0, 'floor'], 'a floor tech: on the fighter')
  // facing left after a wall tech: the wall is to its right
  assert.deepEqual([ev[1].x, ev[1].y, ev[1].side], [10 + FX.tech.wall[0], FX.tech.wall[1], 1])
})

test('the effect is painted for its frames and not after', () => {
  const b = bundle()
  const view = { S: 4, ox: 320, oy: 240 }
  const fills = idx => {
    const c = new RecordingContext()
    drawTechEffects(c, b, idx, view, 1)
    return c.calls.filter(x => x.op === 'fill' || x.op === 'fillRect').length
  }
  // the rays fade in from nothing; the glow comes a few frames later
  const shows = k => (FX.effects.tech.frames[k]?.length || 0) + (FX.tech.rings.frames[k]?.length || 0) > 0 || !!FX.tech.glow[k]
  const n = Math.max(FX.tech.glow.length, FX.tech.rings.frames.length, FX.effects.tech.frames.length)
  const first = [...Array(n).keys()].find(shows), last = n - 1
  assert.equal(fills(4), 0)
  assert.ok(fills(5 + first) > 0)
  assert.ok(fills(5 + last) > 0)
  assert.equal(fills(5 + last + 1), 0)
})

test('the rings: streaks in the plane each ring turns in, the half behind the fighter drawn apart from the half in front', () => {
  const b = bundle()
  const view = { S: 4, ox: 320, oy: 240 }
  const R = FX.tech.rings
  const ground = { fills: [[[-100, 0], [100, 0], [100, -50], [-100, -50]]], floors: [[-100, 0, 100, 0]] }
  const draw = (idx, layer, stage) => {
    const c = new RecordingContext()
    if (layer === 'front') drawTechEffects(c, b, idx, view, 1, stage)
    else drawTechRings(c, b, idx, view, 1, layer, stage)
    return c.calls
  }
  // ring streaks are the only flat-colour fills a tech draws without a transform
  const streaks = calls => calls.filter(x => x.op === 'fill' && x.matrix[0] === 1 && x.matrix[3] === 1 && /^rgba/.test(x.fillStyle))
  for (let k = 0; k < R.frames.length; k++) {
    const back = streaks(draw(5 + k, 'back', ground)), front = streaks(draw(5 + k, 'front', ground))
    assert.ok(back.length > 0 && front.length > 0, `frame +${k}: both halves drawn`)
    // every point within the rings' reach of the effect (10, 0), never on the far side of it
    for (const call of [...back, ...front]) {
      for (const { point: [x, y] } of call.path.filter(p => p.point)) {
        assert.ok(Math.hypot((x - view.ox) / view.S - 10, (view.oy - y) / view.S) < 16, `frame +${k}: ${x}, ${y}`)
      }
    }
  }
  assert.equal(streaks(draw(5 + R.frames.length, 'back', ground)).length, 0)
  assert.equal(streaks(draw(5 + R.frames.length, 'front', ground)).length, 0)
  // on solid ground the stage body (drawn after the back half) hides what it
  // covers: no clip; on a pass-through platform its band under the line does
  const rects = calls => calls.filter(x => x.op === 'rect').length
  assert.equal(rects(draw(5, 'back', ground)), 0)
  const platform = { fills: [], floors: [[-20, 0, 40, 0]] }
  assert.ok(rects(draw(5, 'back', platform)) > 0)
  // the front half is always kept out of the stage's body
  assert.ok(rects(draw(5, 'front', ground)) > 0)
})
