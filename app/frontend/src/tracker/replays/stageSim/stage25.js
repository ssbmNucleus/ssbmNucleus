import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[25]
// VS Icicle Mountain, gricemt.c (NTSC 1.02). Field IDs here are zero-based
// icemt_field indices; MapLine/MapJoint IDs remain the game's original IDs.
import { registerStageSimData } from '../stageData.js'
let data

const cache = new WeakMap(), f32 = Math.fround, CHECKPOINT = 240
let P
export { nextSeed } from './rng.js'
import { setupCursor, frameCursor } from './rng.js'
export function spacing(under, upper) {
  return f32(f32(data.scale * data.fields[upper].bounds[0] + P.spacing)
    - f32(data.scale * data.fields[under].bounds[1]))
}
export function initialState(under, upper) {
  const fieldCooldown = Array(6).fill(0)
  fieldCooldown[under] = fieldCooldown[upper] = P.fieldCooldown
  const top = f32(-20 * data.scale)
  return { under, upper, fields: {
    [under]: { y: f32(top + spacing(under, upper)), born: -1 }, [upper]: { y: top, born: -1 } },
    phase: 0, delay: 0, lerp: 0, speed: 0, program: -1,
    fieldCooldown, scrollCooldown: Array(12).fill(0), contacts: {} }
}
export function chooseProgram(s, rng) {
  const available = s.scrollCooldown.map((n, i) => n === 0 ? i : -1).filter(i => i >= 0)
  const chosen = available[rng.int(available.length)]
  s.scrollCooldown = s.scrollCooldown.map(n => Math.max(0, n - 1))
  s.scrollCooldown[chosen] = P.scrollCooldown
  s.delay = P.waitMin + rng.int(P.waitMax - P.waitMin)
  s.program = chosen; s.phase = 1; s.lerp = P.lerp
}
function chooseField(s, rng) {
  let chosen
  do { chosen = rng.int(6) } while (s.fieldCooldown[chosen] || chosen === s.under || chosen === s.upper)
  s.fieldCooldown = s.fieldCooldown.map(n => Math.max(0, n - 1))
  s.fieldCooldown[chosen] = P.fieldCooldown
  return chosen
}
export function stepScroll(s, rng, idx) {
  if (s.phase === 0) {
    if (s.delay-- < 0) chooseProgram(s, rng)
  } else {
    if (--s.lerp !== 0) s.speed = f32(s.speed + f32(f32(data.speeds[s.program] - s.speed) / s.lerp))
    else { s.phase = 0; s.speed = data.speeds[s.program] }
  }
  s.fields[s.under].y = f32(s.fields[s.under].y - s.speed)
  s.fields[s.upper].y = f32(s.fields[s.upper].y - s.speed)
  const cur = s.fields[s.upper].y, distance = spacing(s.under, s.upper)
  if (cur > 0) {
    const old = s.under
    delete s.fields[old]
    clearContacts(s, old)
    s.under = s.upper
    s.upper = chooseField(s, rng)
    s.fields[s.upper] = { y: f32(cur - spacing(s.under, s.upper)), born: idx }
  } else if (cur < -distance) {
    const old = s.upper
    delete s.fields[old]
    clearContacts(s, old)
    s.upper = s.under
    s.under = chooseField(s, rng)
    s.fields[s.under] = { y: f32(spacing(s.under, s.upper) + f32(cur + distance)), born: idx }
  }
}

function clearContacts(s, field) {
  const f = data.fields[field]
  for (let joint = f.firstJoint; joint <= f.lastJoint; joint++) delete s.contacts[joint]
}

export function triggerContact(s, joint, idx) {
  if (![37, 38, 117].includes(joint)) return false
  const field = joint < 67 ? 1 : 3
  if (!s.fields[field]) return false
  if (s.contacts[joint] != null && idx - s.contacts[joint] <= data.tracks[joint].period) return false
  s.contacts[joint] = idx
  return true
}

function fighterContacts(s, bundle, idx) {
  // The bundle currently lacks Slippi's lastGroundID. Prefer it when a
  // producer supplies it; otherwise only unambiguous grounded feet are used.
  const candidateLines = geometry(s, idx).lines.filter(l => [553, 554, 555].includes(l[0]))
  for (let p = 0; p < (bundle.frames.x?.length || 0); p++) {
    if (bundle.frames.air?.[p]?.[idx] !== 0 || (bundle.frames.state?.[p]?.[idx] ?? 0) < 14) continue
    const ground = bundle.frames.ground_id?.[p]?.[idx]
    const x = bundle.frames.x[p][idx], y = bundle.frames.y?.[p]?.[idx]
    for (const l of candidateLines) {
      if (ground != null ? ground === l[0] : x >= Math.min(l[2],l[4]) && x <= Math.max(l[2],l[4]) &&
        Math.abs(y - (l[3] + (l[5]-l[3])*(x-l[2])/(l[4]-l[2]))) < .01) {
        triggerContact(s, [37,38,117][l[0]-553], idx)
      }
    }
  }
}

// Compact numerical FOBJ keys, not a recording of this match. Linear and
// Hermite interpolation follow HSD_FObj; tangent-only keys are significant.
export function sample(keys, frame) {
  let p0 = 0, p1 = 0, d0 = 0, d1 = 0, t0 = 0, t1 = 0, last = 0, first = true
  for (const [time, op, value, tangent] of keys) {
    if (op === 5) { d0 = d1; d1 = tangent; last = op; continue }
    if (first) {
      p1 = value; d1 = tangent || 0; t1 = time; last = op; first = false
      if (frame <= t1) return p1
      continue
    }
    p0 = p1; p1 = value; t0 = t1; t1 = time
    if (op === 4) { d0 = d1; d1 = tangent }
    else if (last !== 5) { d0 = d1; d1 = 0 }
    if (frame <= t1) {
      if (t1 === t0) return p1
      const u = (frame - t0) / (t1 - t0)
      if (last === 1 || last === 6) return p0
      if (last === 2) return f32(p0 + (p1 - p0) * u)
      return f32((2*u**3-3*u**2+1)*p0 + (u**3-2*u**2+u)*(t1-t0)*d0
        + (-2*u**3+3*u**2)*p1 + (u**3-u**2)*(t1-t0)*d1)
    }
    last = op
  }
  return p1
}
function dynamicKind(dx, dy) {
  const slope = f32(dy / dx)
  if (dx > 0) return slope > 1.7320508368950045 ? 8 : slope < -1.7320508368950045 ? 4 : 1
  if (dx < 0) return slope > .577350295784245 ? 4 : slope < -.577350295784245 ? 8 : 2
  return dy > 0 ? 8 : 4
}
export function geometry(s, idx) {
  const lines = []
  for (const [field, state] of Object.entries(s.fields)) {
    const f = data.fields[field]
    for (let joint = f.firstJoint; joint <= f.lastJoint; joint++) {
      const bone = f.bones[joint]
      if (!bone) continue
      let [tx, ty, sx, sy, angle] = bone
      const track = data.tracks[joint]
      if (track) {
        const contact = s.contacts[joint]
        const age = contact == null ? idx - state.born : idx - contact
        if (track.kind === 6) ty = sample(track.keys, age % track.period)
        else if (contact != null) {
          if (age >= 265 && age < 638) continue
          angle = sample(track.keys, Math.min(age, track.period))
        }
      }
      const co = f32(Math.cos(angle)), si = f32(Math.sin(angle))
      const a = f32(data.scale * f32(co * sx)), b = f32(data.scale * f32(-si * sy))
      const c = f32(data.scale * f32(si * sx)), d = f32(data.scale * f32(co * sy))
      const x = f32(data.scale * tx), y = f32(data.scale * ty + state.y)
      for (const id of data.joints[joint]) {
        const l = data.lines[id]
        const x0 = f32(a*l[2]+b*l[3]+x), y0 = f32(c*l[2]+d*l[3]+y)
        const x1 = f32(a*l[4]+b*l[5]+x), y1 = f32(c*l[4]+d*l[5]+y)
        let flags = l[1]
        if (id >= 553) {
          const kind = dynamicKind(x1-x0,y1-y0)
          if (data.dynamicFloorOnly.includes(id) && kind !== 1) continue
          flags = kind | (data.dynamicFloorOnly.includes(id) ? 256 : flags & 256)
        }
        lines.push([id,flags,x0,y0,x1,y1])
      }
    }
  }
  // Autonomous geometry and grounded contact machinery are covered. Item
  // damage/hide callbacks and airborne ECB contacts are not reconstructed;
  // do not suppress witness trails as if those cases had been proven exact.
  return { lines, replace: true, complete: false }
}
function copyState(s) {
  return { ...s, fields: Object.fromEntries(Object.entries(s.fields).map(([k,v])=>[k,{...v}])),
    fieldCooldown: [...s.fieldCooldown], scrollCooldown: [...s.scrollCooldown], contacts: {...s.contacts} }
}
function initialize(bundle) {
  const init = setupCursor(bundle)
  if (!init || !frameCursor(bundle, 0) || bundle.meta.start_frame !== -123) return null
  // stageGObj9_OnInit: first field, then rejection-sample a distinct field.
  const under = init.int(6)
  let upper
  do { upper = init.int(6) } while (upper === under)
  return { checkpoints: new Map([[0, initialState(under, upper)]]) }
}
export default function simulate(bundle, idx) {
  if (!data) return null
  if (!bundle || !Number.isInteger(idx) || idx < 0 || idx >= bundle.meta?.n) return null
  if (!cache.has(bundle)) cache.set(bundle, initialize(bundle))
  const c = cache.get(bundle)
  if (!c) return null
  let t = Math.floor(idx / CHECKPOINT) * CHECKPOINT
  while (!c.checkpoints.has(t)) t -= CHECKPOINT
  const s = copyState(c.checkpoints.get(t))
  for (let i = t; i <= idx; i++) {
    const rng = frameCursor(bundle, i)
    if (!rng) return null
    // Normal VS READY ends at frame -39. Training/alternate intros need
    // their actual Ground_801C0FB8 release frame from the bundle producer.
    if (i >= 84) stepScroll(s, rng, i)
    fighterContacts(s, bundle, i)
    if ((i + 1) % CHECKPOINT === 0) c.checkpoints.set(i + 1, copyState(s))
  }
  return geometry(s, idx)
}

registerStageSimData(25, value => {
  data = value
  P = data.params
})
