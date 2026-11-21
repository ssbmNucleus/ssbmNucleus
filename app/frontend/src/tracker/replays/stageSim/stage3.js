// NTSC 1.02 grpstadium.c, grStadium_801D4548. Recorded state transitions
// override the schedule. Do not confuse 801D435C (dust) with a terrain timer.
import { registerStageSimData } from '../stageData.js'
let data
import { setupCursor, frameCursor } from './rng.js'

const cache = new WeakMap(), f32 = Math.fround, CHECKPOINT = 240
const forms = { 3: [1, 2], 4: [3], 5: [4], 6: [5], 9: [7] }
const shrink = [1]
for (let t = 1; t <= 121; t++) shrink.push(Math.max(f32(.05), f32(shrink[t - 1] - f32(.95 / 120))))
// A shared numerical table is independent of replay state. Preserve the PPC
// repeated float32 additions without re-running an entire water episode for
// every paint or backward seek.
const wheelAngles = [0]
export function wheelAngle(age) {
  const count = Math.max(0, age + 1)
  while (wheelAngles.length <= count) wheelAngles.push(f32(wheelAngles.at(-1) + f32(-Math.PI / 360)))
  return wheelAngles[count]
}

export function chooseForm(previous, rng) {
  let form
  // Rejection sampling is intentional: it advances the shared RNG on retries.
  for (let i = 0; i < 65536; i++) {
    form = [3, 4, 6, 9][rng.int(4)]
    if (form !== previous) return form
  }
  throw new Error('Invalid Stadium random source')
}

export function initialSchedule(wait) {
  return { event: 0, form: 5, old: -1, previous: -1, wait, clock: 0, scale: 1, events: [] }
}
export function stepSchedule(s, rng, idx) {
  const before = s.event
  switch (s.event) {
    case 0:
      if (s.wait-- < 0) {
        const next = s.form === 5 ? chooseForm(s.previous, rng) : 5
        // Preserve xE2 <- xE0 <- xDE in that order, including neutral
        // transitions. A generic "never repeat the last form" rule differs.
        s.previous = s.old; s.old = s.form; s.form = next
        s.event = s.form === 5 ? 2 : 1
      }
      break
    case 1:
      // Vanilla Slippi's preloaded form archives finish at the next proc.
      // An emulator/mod with asynchronous load delays needs recorded events.
      s.event = 2; break
    case 2: s.clock = 0; s.event = 3; break
    case 3:
      if (s.clock++ > data.params.x10) { s.event = 4; s.clock = 0; s.scale = 1 }
      break
    case 4:
      s.scale = f32(s.scale - f32(.95 / data.params.x14))
      if (s.scale <= f32(.05)) {
        s.scale = f32(.05)
        if (s.clock++ > data.params.x18) { s.event = 5; s.clock = 0 }
      }
      break
    case 5:
      if (++s.clock > data.params.x14) s.event = 6
      break
    case 6:
      s.wait = s.form === 5 ? data.params.x0 + rng.int(data.params.x4 - data.params.x0)
        : data.params.x8 + rng.int(data.params.xC - data.params.x8)
      s.event = 0
      break
  }
  if (s.event !== before) s.events.push([idx, s.event, s.form])
}

function initialize(bundle) {
  if (bundle.stage_state?.stadium?.length) return { events: bundle.stage_state.stadium }
  const init = setupCursor(bundle)
  if (!init || !frameCursor(bundle, 0) || bundle.meta.start_frame !== -123) return null
  // Display initializes without draws; terrain's wait is GameStart draw 1.
  const wait = data.params.x0 + init.int(data.params.x4 - data.params.x0)
  return { checkpoints: new Map([[0, initialSchedule(wait)]]) }
}
const copyState = s => ({ ...s, events: s.events.slice() })

export function geometry(events, idx, fullPrefix = true) {
  let active = fullPrefix ? 5 : null, last = null, waterStart = null
  for (const e of events) {
    if (e[0] > idx) break
    last = e
    if (e[1] === 5 && e[2] === 9) waterStart = e[0]
    if (e[1] === 0 || e[1] === 6) active = e[2]
  }
  if (active == null) return null
  const ev = last?.[1] ?? 0, form = last?.[2] ?? active, dt = last ? idx - last[0] : 0
  if (!forms[active] || !forms[form]) return null
  // Water's collision wheel requires its original event-5 phase. A carried
  // completion at a clipped index does not encode that phase.
  if ((active === 9 || form === 9) && waterStart == null) return null
  const layers = []
  if (ev === 4) layers.push([active, shrink[Math.min(dt, 121)], 0])
  else if (ev === 5) {
    const t = Math.min(dt, 120)
    const scale = f32(f32(f32(.95) * t) / 120 + f32(.05))
    const newY = t < 60 ? f32(-10 * f32(1 - f32(t / 60))) : 0
    const oldY = t > 60 ? f32(-10 * f32(1 - f32((120 - t) / 60))) : 0
    layers.push([active, f32(.05), oldY], [form, scale, newY])
  } else layers.push([active, 1, 0])
  const edges = ev === 5 || active !== 5
  const lines = data.groups[6].filter(id => edges || (id !== 85 && id !== 111)).map(id => data.lines[id].slice())
  const baseCount = lines.length
  for (const [kind, scale, ty] of layers) for (const group of forms[kind]) for (const id of data.groups[group]) {
    const l = data.lines[id]
    lines.push([id, l[1], l[2], f32(l[3] * scale + ty), l[4], f32(l[5] * scale + ty)])
  }
  // The wheel is detached throughout shrink/grow, and is attached by the
  // water proc after case 6 signals xC4_b0 on the following frame.
  if (active === 9 && ev !== 4 && ev !== 5 && ev !== 6) {
    const angle = wheelAngle(idx - waterStart)
    const co = f32(Math.cos(angle)), si = f32(Math.sin(angle))
    for (const id of data.groups[0]) {
      const l = data.lines[id]
      const x0 = f32(co * l[2] - si * l[3] - 45), y0 = f32(si * l[2] + co * l[3] + 51)
      const x1 = f32(co * l[4] - si * l[5] - 45), y1 = f32(si * l[4] + co * l[5] + 51)
      const kind = dynamicKind(x1 - x0, y1 - y0)
      if (data.dynamicFloorOnly?.includes(id) && kind !== 1) continue
      lines.push([id, kind | (data.dynamicFloorOnly?.includes(id) ? 256 : l[1] & 256), x0, y0, x1, y1])
    }
  }
  const out = { lines, replace: true, complete: true }
  if (edges) {
    // A transformed terrain is a solid mass standing on the stage base, but its
    // collision is open: one chain of floors and walls running from the left
    // edge to the right one, with no underside, plus loose planks (the rock
    // form's slope and shelf, the fire form's deck, the grass form's tree
    // platforms). The base loses its top between the inner walls (lines 85/111
    // drop to y -5). Each piece is traced on its own for the FILL only, never
    // as collision, so old and new terrain never join into one self-crossing
    // outline mid-transformation: the base (its own lines and a top at y -5),
    // and each terrain layer closed under its chain (down both ends to the
    // base top, or just under the layer when it has sunk below it). The trace
    // keeps to the chain at forks and leaves the planks as lines.
    out.fillSets = [[...lines.slice(0, baseCount), [-1, 1, -70, -5, 70, -5]]]
    let at = baseCount
    for (const [kind] of layers) {
      const count = forms[kind].reduce((n, group) => n + data.groups[group].length, 0)
      const layer = lines.slice(at, at + count)
      at += count
      const closed = closeLayer(layer)
      if (closed) out.fillSets.push(closed)
    }
  }
  return out
}

// A terrain layer's lines closed into one body for the fill: its chain runs
// from the lowest line start nothing ends at (the left edge) to the lowest line
// end nothing starts at (the right edge); drop both to the base top and join
// them along it. Drop-through lines are not solid and take no part.
export function closeLayer(layer) {
  const solid = layer.filter(l => !(l[1] & 256))
  if (!solid.length) return null
  const key = (x, y) => `${Math.round(x * 100)},${Math.round(y * 100)}`
  const starts = new Set(solid.map(l => key(l[2], l[3]))), ends = new Set(solid.map(l => key(l[4], l[5])))
  let first = null, last = null
  for (const l of solid) {
    if (!ends.has(key(l[2], l[3])) && (!first || l[3] < first[1] || (l[3] === first[1] && l[2] < first[0]))) first = [l[2], l[3]]
    if (!starts.has(key(l[4], l[5])) && (!last || l[5] < last[1] || (l[5] === last[1] && l[4] > last[0]))) last = [l[4], l[5]]
  }
  if (!first || !last || !(last[0] > first[0])) return null
  const low = Math.min(-5, ...solid.map(l => Math.min(l[3], l[5]) - 1))
  return [...solid, [-2, 4, last[0], last[1], last[0], low], [-3, 2, last[0], low, first[0], low], [-4, 8, first[0], low, first[0], first[1]]]
}

export function dynamicKind(dx, dy) {
  const slope = f32(dy / dx)
  if (dx > 0) return slope > 1.7320508368950045 ? 8 : slope < -1.7320508368950045 ? 4 : 1
  if (dx < 0) return slope > .577350295784245 ? 4 : slope < -.577350295784245 ? 8 : 2
  return dy > 0 ? 8 : 4
}

export default function simulate(bundle, idx) {
  if (!data) return null
  if (!bundle || !Number.isInteger(idx) || idx < 0 || idx >= bundle.meta?.n) return null
  if (!cache.has(bundle)) cache.set(bundle, initialize(bundle))
  const c = cache.get(bundle)
  if (!c) return null
  let events = c.events
  if (!events) {
    let t = Math.floor(idx / CHECKPOINT) * CHECKPOINT
    while (!c.checkpoints.has(t)) t -= CHECKPOINT
    const s = copyState(c.checkpoints.get(t))
    for (let i = t; i <= idx; i++) {
      if (i >= 84) {
        const rng = frameCursor(bundle, i)
        if (!rng) return null
        // The normal VS READY callback releases terrain at frame -39 (index
        // 84). Alternate intros/training modes require another start marker.
        // Display/background GObj precedes the terrain controller. Its
        // per-frame Rand(200) and conditional direction/distance draw are
        // consumers of the same seed, even though they do not move terrain.
        if (rng.int(200) === 0) { rng.int(2); rng.int(200) }
        // Known limitation of the seed fallback: 801D2344 can also consume
        // draws when the jumbotron switches views. Its close-up cancellation
        // depends on camera clipping, which the bundle does not carry. The
        // available captures have no such switch on a terrain RNG frame.
        stepSchedule(s, rng, i)
      }
      if ((i + 1) % CHECKPOINT === 0) c.checkpoints.set(i + 1, copyState(s))
    }
    events = s.events
  }
  const result = geometry(events, idx, bundle.meta.start_frame === -123)
  if (result && !c.events) result.complete = false
  return result
}

registerStageSimData(3, value => {
  data = value
})
