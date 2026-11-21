import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[15]
import { frameCursor, setupCursor } from './rng.js'
import { registerStageSimData } from '../stageData.js'
let DATA

// NTSC 1.02 grkraid.c: Ground_SetupStageCallbacks registers priority 4.
// Map object 3 precedes Kraid 4. Kraid's initial wait is GameStart draw 1;
// in-match work follows the current frame's final fighter input tail.
const cache = new WeakMap()
const F = Math.fround
const POSITIONS = [-60, -30, 0, 30, 60, 0]
import { nextSeed as stepSeed } from './rng.js'
export { stepSeed }
export { previousSeed } from './rng.js'

export function initialState(wait) {
  return { frame: -124, state: 0, timer: wait, animation: 0, age: 0,
    position: 0, facing: 0, lastHit: true, hit: 0, rotating: false,
    duration: 0, speed: 0, deceleration: 0, angle: 0 }
}

// mpJointUpdateDynamics uses different thresholds for floors and ceilings.
export function lineKind(x0, y0, x1, y1) {
  const dx = F(x1 - x0), dy = F(y1 - y0), slope = F(dy / dx)
  if (dx > 0) return slope > 1.7320508368950045 ? 8 : slope < -1.7320508368950045 ? 4 : 1
  if (dx < 0) return slope > 0.577350295784245 ? 4 : slope < -0.577350295784245 ? 8 : 2
  return dy > 0 ? 8 : 4
}

export function advance(state, seed) {
  const s = { ...state, frame: state.frame + 1 }
  const rand = n => { seed = stepSeed(seed); return Math.floor(n * (seed >>> 16) / 65536) }
  // Map gobj 3 runs before Kraid gobj 4. A hit starts motion two procs later.
  if (!s.rotating && s.hit) {
    s.duration = 150 + rand(90)
    s.rotating = true
  } else if (s.rotating) {
    if (s.duration === 0) s.speed = F(s.speed - s.deceleration)
    else s.duration--
    if (Math.abs(s.speed) < Math.abs(s.deceleration)) {
      s.hit = 0; s.rotating = false; s.speed = 0; s.deceleration = 0
    } else {
      s.angle = F(s.angle + F(s.speed * F(Math.PI / 180)))
    }
  }
  const play = animation => { s.animation = animation; s.age = 0 }
  const ended = () => s.age >= DATA.lengths[s.animation]
  switch (s.state) {
    case 0:
      if (s.timer > 0) s.timer--
      else if (!s.hit) {
        let p
        if (s.lastHit) { do { p = rand(6) } while (p === s.position) }
        else p = rand(2) ? 0 : 4
        s.position = p; s.lastHit = false
        s.facing = POSITIONS[p] === 0 ? rand(2) : Number(POSITIONS[p] > 0)
        play(3); s.state = 1
      }
      break
    case 1:
      if (ended()) { play(rand(3)); s.timer = 0; s.state = 2 }
      break
    case 2:
      if (ended()) { play(s.facing + 5); s.timer = 0; s.state = 3 }
      s.timer++
      break
    case 3: {
      const left = s.animation === 5
      if (!s.hit && s.timer >= (left ? 158 : 130) && s.timer <= (left ? 169 : 138)) {
        const handX = F(POSITIONS[s.position] + DATA.handX[left ? 0 : 1])
        const factor = F(F(F(F(.3) / F(.2)) / 132) * F(.2))
        s.hit = left ? -1 : 1
        s.speed = F(Math.max(F(.2), Math.min(F(.3), F(factor * Math.abs(handX)))) * s.hit)
        s.deceleration = F(s.speed / 180)
        s.lastHit = true
      }
      s.timer++
      if (ended()) { play(4); s.state = 4 }
      break
    }
    case 4:
      if (ended()) { s.timer = 120 + rand(300); s.state = 0 }
      break
  }
  s.age++
  return s
}

export function geometry(angle) {
  const c = F(Math.cos(angle) * F(.7)), s = F(Math.sin(angle) * F(.7))
  const vertices = DATA.vertices.map(([x, y]) => [F(c * x - s * y), F(s * x + c * y)])
  const lines = DATA.lines.map(([a, b, flags], id) => {
    const [x0, y0] = vertices[a], [x1, y1] = vertices[b]
    return [id, (flags & 0x100) | lineKind(x0, y0, x1, y1), x0, y0, x1, y1]
  })
  return { lines, replace: true, complete: true }
}

export default function simulate(bundle, idx) {
  if (!DATA) return null
  const meta = bundle?.meta, seeds = bundle?.frames?.seed?.[0]
  if (meta?.stage !== 15 || meta.start_frame !== -123 || !Number.isInteger(idx) || idx < 0 ||
      !seeds || idx >= seeds.length || seeds[idx] == null || seeds[0] == null) return null
  let entry = cache.get(bundle)
  if (!entry) {
    const init = setupCursor(bundle)
    if (!init) return null
    entry = { checkpoints: new Map([[-124, initialState(120 + init.int(300))]]) }
    cache.set(bundle, entry)
  }
  const frame = idx - 123
  const checkpoint = -124 + Math.floor((frame + 124) / 128) * 128
  let key = checkpoint
  while (!entry.checkpoints.has(key)) key -= 128
  let state = entry.checkpoints.get(key)
  for (let f = key + 1; f <= frame; f++) {
    const rng = frameCursor(bundle, f + 123)
    if (!rng) return null
    state = advance(state, rng.seed)
    if ((f + 124) % 128 === 0) entry.checkpoints.set(f, state)
  }
  return geometry(state.angle)
}

registerStageSimData(15, value => {
  DATA = value
})
