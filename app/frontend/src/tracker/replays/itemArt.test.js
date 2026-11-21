import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { EXPLOSIONS, explosionLength } from './itemArt.js'

// litePaint imports the app's transport layer: the audit loader stands it in for Node
register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { paintFrame } = await import('./litePaint.js')

const HERE = path.dirname(fileURLToPath(import.meta.url))

test('each explosion is the state whose hitbox is the blast, at its radius and frames (data/items)', () => {
  for (const [kind, [state, r, hit]] of Object.entries(EXPLOSIONS)) {
    const table = JSON.parse(fs.readFileSync(path.join(HERE, 'data/items', `${kind}.json`), 'utf8'))
    const anim = table.animations[String(table.states[state])]
    const frames = Object.keys(anim.frames).map(Number)
    const radius = anim.frames[String(Math.min(...frames))][0][4] * table.scale
    assert.equal(Math.round(radius * 100) / 100, r, `${kind} radius`)
    assert.equal(Math.max(...frames) + 1, hit, `${kind} hitbox frames`)
  }
})

// one fighter far away, one item; what was filled within 15 units of the item
function fillsNear(item, idx) {
  const n = item.s.length
  const b = { meta: { stage: 31, start_frame: 0, n, players: [{}] }, items: [item],
    frames: { x: [Array(n).fill(90)], y: [Array(n).fill(0)], air: [Array(n).fill(0)], state: [Array(n).fill(14)],
      cat: [Array(n).fill(0)], cid: [Array(n).fill(2)], age: [Array(n).fill(0)], dir: [Array(n).fill(1)] } }
  const fills = []; let pts = []
  const c = { canvas: { width: 640, height: 480 }, globalAlpha: 1, setTransform() {}, fillRect() {}, closePath() {}, stroke() {},
    save() {}, restore() {}, clip() {}, rect() {}, translate() {}, rotate() {}, scale() {},
    beginPath() { pts = [] }, moveTo(x, y) { pts.push([x, -y]) }, lineTo(x, y) { pts.push([x, -y]) },
    arc(x, y) { pts.push([x, -y]) }, ellipse(x, y) { pts.push([x, -y]) },
    fill() { if (c.globalAlpha > 0) fills.push([c.fillStyle, pts.slice()]) } }
  paintFrame(c, b, null, null, idx, { S: 1, ox: 0, oy: 0 }, 1)
  return fills.filter(([, p]) => p.some(([x, y]) => Math.hypot(x - item.x[idx], y - item.y[idx]) < 15))
}

test('a bomb that blew up shows our burst, then nothing: no dot where it was (Link, Samus, Bob-omb)', () => {
  for (const [kind, before] of [[58, 0], [59, 4], [93, 1], [6, 9]]) {
    const [state, , hit] = EXPLOSIONS[kind], end = explosionLength(hit), n = 3 + end + 10
    const s = [before, before, before, ...Array(n - 3).fill(state)]
    // on its own (no holder: a held one rides in a hand, heldAt)
    const item = { t: kind, o: -1, f: 0, x: Array(n).fill(-20), y: Array(n).fill(10), s, d: Array(n).fill(1), vx: Array(n).fill(0), vy: Array(n).fill(0) }
    assert.ok(fillsNear(item, 1).length, `${kind}: the bomb itself before it blows`)
    const burst = fillsNear(item, 3)
    assert.ok(burst.some(([col]) => col === '#ff8a2a'), `${kind}: the burst on the frame it blows`)
    assert.ok(fillsNear(item, 3 + hit + 2).length, `${kind}: smoke after the blast`)
    assert.deepEqual(fillsNear(item, 3 + end), [], `${kind}: nothing once it is over`)
    assert.deepEqual(fillsNear(item, n - 1), [], `${kind}: nothing while the item lingers`)
  }
})

// what was filled or stroked near the item, with its colour
function paintNear(item, idx, radius = 15) {
  const n = item.s.length, out = []
  const b = { meta: { stage: 31, start_frame: 0, n, players: [{}] }, items: [item],
    frames: { x: [Array(n).fill(90)], y: [Array(n).fill(0)], air: [Array(n).fill(0)], state: [Array(n).fill(14)],
      cat: [Array(n).fill(0)], cid: [Array(n).fill(2)], age: [Array(n).fill(0)], dir: [Array(n).fill(1)] } }
  let pts = []
  const c = { canvas: { width: 640, height: 480 }, globalAlpha: 1, setTransform() {}, fillRect() {}, closePath() {},
    save() {}, restore() {}, clip() {}, rect() {}, translate() {}, scale() {},
    beginPath() { pts = [] }, moveTo(x, y) { pts.push([x, -y]) }, lineTo(x, y) { pts.push([x, -y]) },
    arc(x, y) { pts.push(['arc', x, -y]) }, ellipse(x, y) { pts.push(['arc', x, -y]) },
    fill() { if (c.globalAlpha > 0) out.push(['fill', c.fillStyle, pts.slice()]) },
    stroke() { if (c.globalAlpha > 0) out.push(['stroke', c.strokeStyle, pts.slice()]) } }
  paintFrame(c, b, null, null, idx, { S: 1, ox: 0, oy: 0 }, 1)
  const near = p => p.some(q => { const [x, y] = q[0] === 'arc' ? q.slice(1) : q; return Math.hypot(x - item.x[idx], y - item.y[idx]) < radius })
  return out.filter(([, , p]) => near(p))
}
const track = (t, s, extra = {}) => ({ t, o: -1, f: 0, x: Array(s.length).fill(-20), y: Array(s.length).fill(20), s, d: Array(s.length).fill(1),
  vx: Array(s.length).fill(-1.5), vy: Array(s.length).fill(0.5), ...extra })

test("Yoshi's thrown egg is a spotted egg, not a disc the size of its blast; it breaks into pieces", () => {
  const egg = track(86, [0, 0, 1, 1, 1, 2, 2, 2, 2, 2])
  for (const idx of [1, 3]) {
    const drawn = paintNear(egg, idx)
    const shell = drawn.find(([op, col]) => op === 'fill' && col === '#f2f0e6')
    assert.ok(shell && drawn.some(([op, col]) => op === 'fill' && col === '#3fae49'), `egg at ${idx}`)
    const ys = shell[2].map(p => p[1])
    assert.ok(Math.max(...ys) - Math.min(...ys) < 9, 'about 7.8 tall, not the 25-unit break blast')
  }
  assert.ok(paintNear(egg, 7, 20).some(([op, col]) => op === 'fill' && col === '#f2f0e6'), 'shell pieces while it breaks')
})

test("Link's boomerang is a V of strokes, not a dot", () => {
  const drawn = paintNear(track(60, [0, 1, 2, 2, 3]), 3)
  assert.ok(drawn.length && drawn.every(([op]) => op === 'stroke'), 'strokes only')
})

test("Yoshi's shield is his egg: GuardHold and GuardDamage draw the egg in place of his pose", async () => {
  const { createRenderer } = await import('./meleeRender.js')
  const r = createRenderer({ actionNameById: [], chars: { 14: { scale: 1, animationMap: {}, specialsMap: {} } } })
  const fills = []; let pts = []
  const ctx = { save() {}, restore() {}, setTransform() {}, beginPath() { pts = [] }, closePath() {}, stroke() {},
    moveTo(x, y) { pts.push([x, y]) }, lineTo(x, y) { pts.push([x, y]) }, fill() { fills.push([this.fillStyle, pts.slice()]) } }
  const o = { cid: 14, state: 342, age: 3, x: 10, y: 0, facing: 1, fill: '#f00', view: { S: 1, ox: 0, oy: 0 }, dpr: 1 }
  assert.equal(r.draw(ctx, {}, o), 'egg')
  const ys = fills[0][1].map(p => -p[1])
  // 2 x shield size 6.3 tall around the shield bone 5.88 up: from the floor
  assert.ok(Math.abs(Math.min(...ys) - (5.88 - 6.3)) < 0.05 && Math.abs(Math.max(...ys) - (5.88 + 6.3)) < 0.05, `${Math.min(...ys)} ${Math.max(...ys)}`)
  assert.equal(r.draw(ctx, {}, { ...o, state: 344 }), 'egg')
  assert.notEqual(r.draw(ctx, {}, { ...o, state: 341 }), 'egg')   // GuardOn shows Yoshi himself
})

test("a held item rides in its holder's hand (the replay records where it was pulled), then leaves from there", async () => {
  const { registerHitDataLoader, ensureHitData } = await import('./stageData.js')
  const { heldAt } = await import('./litePaint.js')
  registerHitDataLoader(id => JSON.parse(fs.readFileSync(path.join(HERE, 'data/hits', `${id}.json`), 'utf8')))
  await ensureHitData(6)
  const H = JSON.parse(fs.readFileSync(path.join(HERE, 'data/hits/6.json'), 'utf8')).hold
  // Link (internal 6) walks right holding a bomb; its recorded position stays where he pulled it
  const n = 6, b = { meta: { stage: 31, start_frame: 0, n, players: [{}] },
    frames: { x: [[0, 2, 4, 6, 8, 10]], y: [[0, 0, 0, 0, 0, 0]], state: [Array(n).fill(14)], age: [[0, 2, 4, 6, 8, 10]], dir: [Array(n).fill(1)], cid: [Array(n).fill(6)] } }
  const bomb = { t: 58, o: 0, f: 0, x: Array(n).fill(-30), y: Array(n).fill(40), s: [0, 0, 0, 0, 2, 2] }
  const wait = H.states['14']
  for (const i of [0, 1, 2, 3]) {
    const [hx, hy] = heldAt(b, bomb, i, i)
    assert.ok(Math.abs(hx - (b.frames.x[0][i] + wait[i * 2])) < 1e-9 && Math.abs(hy - wait[i * 2 + 1]) < 1e-9, `frame ${i}`)
  }
  assert.equal(heldAt(b, bomb, 4, 4), null, 'thrown: its own recorded position again')
  // facing left, the hand is mirrored
  b.frames.dir[0].fill(-1)
  assert.ok(Math.abs(heldAt(b, bomb, 0, 0)[0] - (0 - wait[0])) < 1e-9)
})
