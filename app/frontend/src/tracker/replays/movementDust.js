// Movement dust: the puffs the game spawns as fighters dash, turn while
// running, jump, land and run (melee decomp). Each fighter's action scripts
// (Pl<XX>.dat) carry effect commands (0x28 Graphic Effect, 0x37 Sound and
// Graphic Effect, ftaction.c) that run when the action frame reaches their
// time; the dust ids among them (efasync.c) are:
// - 0x3FF dash: EfCoData model 5, turned by the facing, and generator 9;
// - 0x401 turn (0x400 the other way): generator 0x5A, by the facing;
// - 0x402 jump and 0x403 double jump (a ring under the feet);
// - 0x404 landing: EfCoData model 24 and generator 10;
// - 0x407 aerial and special-fall landings (wavedashes): generator 0x3C;
// - 0x3FE walk and run steps: generator 0x107.
// The same commands also bring dust to rolls, getup rolls, ledge jumps and
// rolls and the like. Which state spawns what, when, is baked per fighter
// (data/movementDust.js fighters, tools/liteaudit/dust/build.py). The puffs are
// drawn with shapes of our own, no game art: each particle the game spawns
// (read frame by frame in playback Dolphin) and each part of its two models
// (posed from RAM) is measured into a soft ellipse, or a ring when it is
// hollow, with its size, place, turn, opacity and colour frame by frame.
// Slippi records each fighter's state and action frame, so a command runs on
// the first frame of a state's run whose action frame has reached its time; a
// run restarts when the state changes or its action frame goes back (a dash
// dance's next dash, a run's animation looping). The dust stays where it
// spawned and is mirrored by facing.
import DUST from './data/movementDust.js'

const KINDS = DUST.kinds
const LIFE = Math.max(...Object.values(DUST.effects).map(fx => fx.frames.length))
const own = Object.prototype.hasOwnProperty

// The commands a fighter's state runs: its own list, else the one every
// fighter shares (a number is another state's list). A command is
// time x 8 + kind, or [time, kind, forward, up] when it sits off the fighter.
function schedule(cid, state) {
  const t = DUST.fighters[cid], c = DUST.fighters.common
  let s = t && own.call(t, state) ? t[state] : c?.[state]
  if (typeof s === 'number') s = t && own.call(t, s) ? t[s] : c?.[s]
  return s?.length ? s : null
}

// Every dust puff in the bundle: {idx, kind, x, y, facing, row (the fighter's
// rows it came from)}, sorted by idx. Cached.
const cache = new WeakMap()
export function dustEvents(bundle) {
  let out = cache.get(bundle)
  if (out) return out
  out = []
  const f = bundle?.frames
  if (f?.state && f.age) {
    const rows = f.state.map((st, i) => ({ cid: f.cid[i], st, age: f.age[i], x: f.x[i], y: f.y[i], dir: f.dir?.[i] }))
    for (const fo of f.fol || []) rows.push({ cid: fo.cid, st: fo.state, age: fo.age, x: fo.x, y: fo.y, dir: fo.dir })
    for (const r of rows) {
      if (!r.age) continue
      let prevSt = null, prevAge = 0, cmds = null, fired = 0
      for (let idx = 0; idx < r.st.length; idx++) {
        const st = r.st[idx], age = r.age[idx]
        if (st == null || age == null || r.x[idx] == null) { prevSt = null; continue }
        if (st !== prevSt || age < prevAge) { fired = 0; cmds = schedule(r.cid[idx], st) }
        if (cmds) {
          for (let j = 0; j < cmds.length; j++) {
            const c = cmds[j], t = typeof c === 'number' ? c >> 3 : c[0]
            if (fired & (1 << j) || age < t) continue
            fired |= 1 << j
            // a run already under way when the rows begin spawned its dust before them
            if (prevSt == null) continue
            const dir = (r.dir?.[idx] ?? 1) < 0 ? -1 : 1, k = KINDS[typeof c === 'number' ? c & 7 : c[1]]
            // turnback (0x400) is turn's generator with the facing negated (efAsync_Dispatch)
            out.push({ idx, kind: k === 'turnback' ? 'turn' : k, facing: k === 'turnback' ? -dir : dir,
              x: r.x[idx] + (typeof c === 'number' ? 0 : dir * c[2]), y: r.y[idx] + (typeof c === 'number' ? 0 : c[3]), row: r })
          }
        }
        prevSt = st; prevAge = age
      }
    }
    out.sort((a, b) => a.idx - b.idx)
  }
  cache.set(bundle, out)
  return out
}

// One shape (data/movementDust.js effects): [kind, x, y, rx, ry, turn, alpha,
// colour, width?] around the spawn point, mirrored when m = -1. Kind 0 is a
// soft ellipse, alpha x (1 - r^2) out to its radii; kind 1 a ring, a line of
// `width` along the ellipse.
const STOPS = [[0, 1], [0.25, 0.9375], [0.5, 0.75], [0.75, 0.4375], [1, 0]]
const RGB = new WeakMap()
function rgb(fx, i) {
  let list = RGB.get(fx)
  if (!list) { list = fx.colours.map(c => [0, 2, 4].map(j => parseInt(c.slice(j, j + 2), 16)).join(',')); RGB.set(fx, list) }
  return list[i]
}
function drawShape(ctx, fx, s, ox, oy, m, view, dpr) {
  const [kind, x, y, rx, ry, turn, alpha, ci, width] = s
  const t = m * turn * Math.PI / 180, c = Math.cos(t), sn = Math.sin(t), S = view.S
  // the unit circle onto the ellipse, in canvas pixels (y down)
  ctx.setTransform(dpr * S * rx * c, -dpr * S * rx * sn, -dpr * S * ry * sn, -dpr * S * ry * c,
    dpr * (view.ox + S * (ox + m * x)), dpr * (view.oy - S * (oy + y)))
  const col = rgb(fx, ci)
  ctx.beginPath()
  ctx.arc(0, 0, 1, 0, 2 * Math.PI)
  if (kind === 1) {
    ctx.lineWidth = 2 * width / (rx + ry)
    ctx.strokeStyle = `rgba(${col},${alpha})`
    ctx.stroke()
    return
  }
  const g = ctx.createRadialGradient(0, 0, 0, 0, 0, 1)
  for (const [at, v] of STOPS) g.addColorStop(at, `rgba(${col},${alpha * v})`)
  ctx.fillStyle = g
  ctx.fill()
}

// One puff `k` frames after it spawned: the model's parts, then its particles.
export function drawDustEffect(ctx, ev, k, view, dpr) {
  const fx = DUST.effects[ev.kind]
  if (!fx) return
  const m = fx.facing !== ev.facing ? -1 : 1
  for (const s of fx.frames[k] || []) drawShape(ctx, fx, s, ev.x, ev.y, m, view, dpr)
}

// Every puff alive on idx, after the fighters (the game draws effects last).
export function drawDust(ctx, bundle, idx, view, dpr) {
  const events = dustEvents(bundle)
  if (!events.length) return
  // the first puff still alive: binary search on idx
  let lo = 0, hi = events.length
  while (lo < hi) { const mid = (lo + hi) >> 1; if (events[mid].idx <= idx - LIFE) lo = mid + 1; else hi = mid }
  if (lo >= events.length || events[lo].idx > idx) return
  ctx.save()
  for (let i = lo; i < events.length && events[i].idx <= idx; i++) drawDustEffect(ctx, events[i], idx - events[i].idx, view, dpr)
  ctx.restore()
  ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}
