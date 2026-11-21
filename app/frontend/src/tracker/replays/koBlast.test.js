import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { koEvents, drawKoBlasts, colourIndex } = await import('./koBlast.js')
const { RecordingContext } = await import('../../../../../tools/liteaudit/recording_context.mjs')
const KO = (await import('./data/koEffects.js')).default

// two fighters on Final Destination (blast zones -246, 246, 188, -140):
// player 0 (port 3) is KO'd off the left at 10 while above the top blast zone,
// player 1 (port 1) off the bottom at 100, past the right blast zone
function bundle(players = [{ physical_port: 2 }, { physical_port: 0 }], teams = false) {
  const n = 170
  const row = (v) => Array.from({ length: n }, () => v)
  const st0 = Array.from({ length: n }, (_, i) => (i < 10 ? 88 : i < 70 ? 1 : 11))
  const st1 = Array.from({ length: n }, (_, i) => (i < 100 ? 29 : i < 160 ? 0 : 11))
  return {
    meta: { n, stage: 32, start_frame: 0, teams, players },
    frames: { cid: [row(1), row(2)], x: [row(-250), row(260)], y: [row(200), row(-145)], dir: [row(1), row(1)],
      state: [st0, st1], age: [row(0), row(0)] },
    items: [],
  }
}

test('a side or bottom KO spawns the blast where the game puts it, once', () => {
  const ev = koEvents(bundle())
  assert.deepEqual(ev.map(e => e.idx), [10, 100])
  // the left KO keeps its x and is brought down to the top blast zone, turned to point right
  assert.deepEqual([ev[0].x, ev[0].y, ev[0].turn], [-250, 188, -Math.PI / 2])
  // the bottom KO keeps its y and is brought in to the right blast zone, pointing up
  assert.deepEqual([ev[1].x, ev[1].y, ev[1].turn], [246, -145, 0])
})

test('the colour is the port, the team in a team game, grey for a CPU', () => {
  const b = bundle()
  assert.deepEqual(koEvents(b).map(e => e.colour), [2, 0])
  assert.equal(colourIndex(bundle([{ physical_port: 1, cpu: true }, {}]), 0), 4)
  // red, blue and green teams: colour indices 0, 1, 3 (gm_80160854)
  assert.equal(colourIndex(bundle([{ physical_port: 0, team: 2 }, {}], true), 0), 3)
  // a bundle from before ports were recorded: the player index
  assert.equal(colourIndex(bundle([{}, {}]), 1), 1)
  assert.equal(KO.blast.colours.length, 5)
})

test('star and screen KOs are not this effect', () => {
  const b = bundle()
  b.frames.state[0] = b.frames.state[0].map(s => (s === 1 ? 3 : s))
  b.frames.state[1] = b.frames.state[1].map(s => (s === 0 ? 6 : s))
  assert.equal(koEvents(b).length, 0)
})

test('the blast is painted for its frames, in the player colour, and not after', () => {
  const b = bundle()
  const view = { S: 2, ox: 640, oy: 360 }
  const paint = idx => {
    const c = new RecordingContext()
    drawKoBlasts(c, b, idx, view, 1)
    return c.calls.filter(x => x.op === 'fill' || x.op === 'fillRect')
  }
  assert.equal(paint(9).length, 0)
  assert.ok(paint(10).length > 0)
  const last = Math.max(KO.blast.frames.length, KO.blast.particles.frames.length) - 1
  assert.ok(paint(10 + last).length > 0)
  assert.equal(paint(10 + last + 1).length, 0)
  // the lingering flame is the player's: port 3's yellow (TEV0) at its rim, its light (KONST) at its heart
  const flame = KO.blast.frames.findIndex(r => r.some(([li]) => KO.blast.layers[li][4] === null))
  const c = new RecordingContext()
  drawKoBlasts(c, b, 10 + flame, view, 1)
  const stops = c.calls.filter(x => x.op === 'fill').flatMap(x => x.fillStyle?.stops || []).map(([, col]) => col)
  const [tev0, konst] = KO.blast.colours[2]
  const rgbOf = h => [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)).join(',')
  assert.ok(stops.some(s => s.includes(rgbOf(tev0))), `the port colour ${rgbOf(tev0)} among ${[...new Set(stops)].slice(0, 6)}`)
  assert.ok(stops.some(s => s.includes(rgbOf(konst))), `its light ${rgbOf(konst)}`)
})

test('every vanilla stage has its blast zones', () => {
  for (const id of [2, 3, 8, 28, 31, 32]) {
    const [l, r, t, b] = KO.zones[id]
    assert.ok(l < 0 && r > 0 && t > 0 && b < 0, `stage ${id}`)
  }
  assert.deepEqual(KO.zones[31], [-224, 224, 200, -108.8])
})

test('the blast points into the stage from the side it went out', () => {
  const b = bundle()
  const view = { S: 1, ox: 640, oy: 360 }
  // where the painted shapes sit (their transform's origin), on the left KO's
  // frame 1 and on the bottom KO's
  const centre = (idx, ev) => {
    const c = new RecordingContext()
    drawKoBlasts(c, b, idx, view, 1)
    const at = c.calls.filter(x => x.op === 'fill' || x.op === 'fillRect').map(x => [x.matrix[4], x.matrix[5]])
    return [at.reduce((a, p) => a + p[0], 0) / at.length - (view.ox + ev.x), (view.oy - ev.y) - at.reduce((a, p) => a + p[1], 0) / at.length]
  }
  const [left, bottom] = koEvents(b)
  const [lx, ly] = centre(11, left)
  assert.ok(lx > 40 && Math.abs(ly) < lx / 2, `left KO: to the right (${lx.toFixed(1)}, ${ly.toFixed(1)})`)
  const [bx, by] = centre(101, bottom)
  assert.ok(by > 40 && Math.abs(bx) < by / 2, `bottom KO: upward (${bx.toFixed(1)}, ${by.toFixed(1)})`)
})

test('no game art ships: numbers only', () => {
  assert.equal(KO.blast.textures, undefined)
  for (const l of KO.blast.layers) assert.equal(l.length, 6, 'a box and two colours, no traced regions')
  assert.deepEqual(KO.blast.particles.looks, ['streak', 'spikes', 'sparkle', 'star', 'smoke', 'burst'])
})
