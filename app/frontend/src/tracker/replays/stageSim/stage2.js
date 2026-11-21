import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[2]
// grizumi.c: grIzumi_801CCBDC / grIzumi_801CC358, NTSC 1.02.
// All RNG is shared. Re-anchor to the replay's pre-frame seed each frame;
// the two platform procs execute in creation order (left, then right).
import { registerStageSimData } from '../stageData.js'
let data
import { setupCursor, frameCursor } from './rng.js'
export { nextSeed, previousSeed, random } from './rng.js'

const cache = new WeakMap()
const f32 = Math.fround
let P
const CHECKPOINT = 240

export function initialPlatform(height, timer) {
  return { state: 1, timer, height, target: height, collision: height, hidden: false }
}

// A hidden fountain retains an ENABLED collision line below the stage. Its
// collision translation is the fountain model root's -2.25 minus 1, not -1.
export function stepPlatform(p, rng) {
  switch (p.state) {
    case 0:
      p.state = 1; p.timer = P.x38 + rng.int(P.x3C - P.x38); p.collision = p.height
      break
    case 1:
      if (p.timer-- < 0) {
        let choice = f32(rng.float() * f32(P.x40 + P.x44 + P.x48))
        choice = f32(choice - P.x40)
        if (choice < 0) { p.state = 2; p.target = -1; break }
        choice = f32(choice - P.x48)
        if (choice < 0) {
          // PPC fmadds rounds the product+sum once.
          const amount = f32((P.x1C - P.x18) * rng.float() + P.x18)
          const r = rng.float()
          const up = p.height < P.xC ? r >= P.x30 : p.height > P.xC ? r < P.x34 : r < .5
          p.target = Math.max(P.x24, Math.min(P.x20, f32(p.target + (up ? amount : -amount))))
          p.state = 2
        } else p.timer = P.x38 + rng.int(P.x3C - P.x38)
      }
      break
    case 2: {
      const delta = f32(p.target - p.height)
      if (delta > 0) {
        if (delta < P.x28) { p.height = p.target; p.state = 0 }
        else p.height = f32(p.height + P.x28)
      } else if (delta < 0) {
        if (-delta < P.x2C) { p.height = p.target; p.state = p.height < P.x24 ? 3 : 0 }
        else p.height = f32(p.height - P.x2C)
      } else p.state = 0
      p.collision = p.height
      break
    }
    case 3:
      p.state = 4; p.timer = P.x4C + rng.int(P.x50 - P.x4C)
      p.hidden = true; p.collision = -3.25
      break
    case 4:
      if (p.timer-- < 0) {
        p.state = 2; p.target = P.xC; p.hidden = false; p.collision = p.height
      }
      break
  }
  return p
}

function initialize(bundle) {
  const events = bundle.stage_state?.fod
  const n = bundle.meta?.n
  if (!Number.isInteger(n) || n <= 0) return null
  if (events?.length) {
    // Event checkpoints include suppressed repeated -1 heights: the second
    // -1 after the submerged dwell marks the fountain's reappearance.
    const checkpoints = new Map()
    const state = { i: 0, heights: bundle.meta.start_frame === -123 ? [28, 20] : [null, null],
      bottomAt: [null, null], submerged: [false, false] }
    for (let t = 0; t < n; t++) {
      if (t % CHECKPOINT === 0) checkpoints.set(t, structuredState(state))
      stepEvents(state, events, t)
    }
    return { events, checkpoints }
  }
  const init = setupCursor(bundle)
  if (!init || !frameCursor(bundle, 0) || bundle.meta.start_frame !== -123) return null
  // grIzumi_OnInit creates left then right before fighters: draws 1 and 2.
  const left = P.x38 + init.int(P.x3C - P.x38)
  const right = P.x38 + init.int(P.x3C - P.x38)
  const state = [initialPlatform(P.x0, left), initialPlatform(P.x8, right)]
  return { checkpoints: new Map([[0, state]]) }
}

function structuredState(s) {
  return { i: s.i, heights: [...s.heights], bottomAt: [...s.bottomAt], submerged: [...s.submerged] }
}
function stepEvents(s, events, idx) {
  for (let p = 0; p < 2; p++) if (s.bottomAt[p] != null && idx > s.bottomAt[p]) s.submerged[p] = true
  while (s.i < events.length && events[s.i][0] <= idx) {
    const [t, p, h] = events[s.i++]
    if (p !== 0 && p !== 1) continue
    const wasBottom = s.heights[p] === -1
    s.heights[p] = h
    if (h === -1 && !wasBottom) s.bottomAt[p] = t
    else { s.bottomAt[p] = null; s.submerged[p] = false }
  }
}

export default function simulate(bundle, idx) {
  if (!data) return null
  if (!bundle || !Number.isInteger(idx) || idx < 0 || idx >= bundle.meta?.n) return null
  if (!cache.has(bundle)) cache.set(bundle, initialize(bundle))
  const c = cache.get(bundle)
  if (!c) return null
  let heights
  if (c.events) {
    const t = Math.floor(idx / CHECKPOINT) * CHECKPOINT
    const s = structuredState(c.checkpoints.get(t))
    for (let i = t; i <= idx; i++) stepEvents(s, c.events, i)
    if (s.heights.some(h => !Number.isFinite(h))) return null
    // A carried -1 loses whether this is the arrival, submerged dwell, or
    // departure frame. The next frame's event (or its absence) disambiguates.
    if (idx === 0 && bundle.meta.start_frame !== -123 && s.heights.includes(-1)) return null
    heights = [1, 0].map(p => s.submerged[p] ? -3.25 : s.heights[p])
  } else {
    let t = Math.floor(idx / CHECKPOINT) * CHECKPOINT
    while (!c.checkpoints.has(t)) t -= CHECKPOINT
    const state = c.checkpoints.get(t).map(p => ({ ...p }))
    for (let i = t; i <= idx; i++) {
      const rng = frameCursor(bundle, i)
      if (!rng) return null
      for (const p of state) stepPlatform(p, rng)
      if ((i + 1) % CHECKPOINT === 0) c.checkpoints.set(i + 1, state.map(p => ({ ...p })))
    }
    heights = state.map(p => p.collision)
  }
  const lines = data.lines.map(line => {
    if (line[0] > 1) return line.slice()
    const y = f32(f32(heights[line[0]] * .75) + 1.125)
    return [line[0], line[1], line[2], y, line[4], y]
  })
  return { lines, replace: true, complete: true }
}

registerStageSimData(2, value => {
  data = value
  P = data.params
})
