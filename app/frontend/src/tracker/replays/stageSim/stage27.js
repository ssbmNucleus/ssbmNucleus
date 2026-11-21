import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[27]
// grflatzone.c, NTSC 1.02. The platform animations are constant visibility
// masks extracted from GrFz.dat; frame time alone cannot choose the pattern.
import { registerStageSimData } from '../stageData.js'
let data

const cache = new WeakMap(), CHECKPOINT = 240
export const ANIMATIONS = [
  [0, 1, 2, -1, -1], [3, 4, 5, 6, 7], [8, 9, 10, 11, 12],
  [13, 14, 15, 16, 17], [18, -1, -1, -1, -1],
  [19, -1, -1, -1, -1], [20, -1, -1, -1, -1], [21, -1, -1, -1, -1],
]
export { nextSeed } from './rng.js'
import { setupCursor, frameCursor } from './rng.js'
export function nextVariation(layout, previous, rng) {
  for (let i = 0; i < 65536; i++) {
    const v = rng.int(4) + 1
    if (v !== previous && ANIMATIONS[layout][v] !== -1) return v
  }
  throw new Error('Invalid Flat Zone random source')
}
export function initialState(wait, platformWait) {
  return { wait, platformWait, layout: 2, variation: 1, animation: 9,
    // xC8 is initialized to 8 and is never assigned again in grflatzone.c.
    previousLayout: 8, event: 0, running: true, tools: 0,
    oilPhase: -1, oilWait: 0, oilDirection: 1 }
}
function chooseLayout(s, rng, withVariation) {
  let layout
  do { layout = rng.int(8) } while (layout === s.previousLayout || (withVariation && ANIMATIONS[layout][1] === -1))
  s.layout = layout
  s.variation = 0
  if (withVariation) {
    do { s.variation = rng.int(4) + 1 } while (ANIMATIONS[layout][s.variation] === -1)
    s.platformWait = 120 + rng.int(300)
  } else s.platformWait = 0
  s.animation = ANIMATIONS[layout][s.variation]
}
export function stepState(s, rng) {
  // Controller 2 executes before oil machine 3, platforms 5, and tools 8.
  let startOil = false
  if (s.running) {
    if (s.wait !== 0) {
      if (--s.wait === 0) {
        s.running = false
        let event
        do { event = 3 + rng.int(2) } while (event === s.event)
        s.event = event
        if (event === 3) s.tools = 1200
        else startOil = true
        chooseLayout(s, rng, false)
      }
    } else {
      chooseLayout(s, rng, true)
      s.wait = 1800 + rng.int(1200)
    }
  }
  if (startOil) {
    s.oilDirection = rng.int(2) ? 1 : -1
    s.oilPhase = 0; s.oilWait = s.oilDirection === 1 ? 65 : 130
  }
  switch (s.oilPhase) {
    case 0:
      if (--s.oilWait <= 0) { s.oilPhase = 1; s.oilWait = 24 * (2 + rng.int(6)) }
      break
    case 1:
      if (--s.oilWait <= 0) { s.oilPhase = 2; s.oilWait = 46 }
      break
    case 2:
      if (--s.oilWait <= 0) { s.oilPhase = 3; s.oilWait = 1200; s.running = true }
      break
    case 3: if (--s.oilWait <= 1) s.oilPhase = 4; break
    case 4: s.oilPhase = -1; break
  }
  if (s.variation !== 0 && s.platformWait-- < 0) {
    s.variation = nextVariation(s.layout, s.variation, rng)
    s.animation = ANIMATIONS[s.layout][s.variation]
    s.platformWait = 120 + rng.int(300)
  }
  // Tools spawn after the platform controller. No MapLines belong to the
  // falling items, but their three random calls belong to this frame's stream.
  if (s.tools > 0) {
    if (s.tools % 60 === 0) { rng.int(65536); rng.int(5); rng.int(2) }
    if (--s.tools === 0) s.running = true
  }
}
function initialize(bundle) {
  const init = setupCursor(bundle)
  if (!init || !frameCursor(bundle, 0) || bundle.meta.start_frame !== -123) return null
  // Controller 2 initializes before platform controller 5.
  const wait = 1800 + init.int(1200), platformWait = 120 + init.int(300)
  return { checkpoints: new Map([[0, initialState(wait, platformWait)]]) }
}
export default function simulate(bundle, idx) {
  if (!data) return null
  if (!bundle || !Number.isInteger(idx) || idx < 0 || idx >= bundle.meta?.n) return null
  if (!cache.has(bundle)) cache.set(bundle, initialize(bundle))
  const c = cache.get(bundle)
  if (!c) return null
  let t = Math.floor(idx / CHECKPOINT) * CHECKPOINT
  while (!c.checkpoints.has(t)) t -= CHECKPOINT
  const s = { ...c.checkpoints.get(t) }
  for (let i = t; i <= idx; i++) {
    const rng = frameCursor(bundle, i)
    if (!rng) return null
    // Normal VS READY ends at frame -39. Training/alternate intros need
    // their actual Ground_801C0FB8 release frame from the bundle producer.
    if (i >= 84) stepState(s, rng)
    if ((i + 1) % CHECKPOINT === 0) c.checkpoints.set(i + 1, { ...s })
  }
  const ids = [...data.groups[50], ...data.groups[33], ...data.animations[s.animation]]
  return { lines: ids.map(id => data.lines[id].slice()), replace: true, complete: true }
}

registerStageSimData(27, value => {
  data = value
})
