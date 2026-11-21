// Missed techs and shield breaks, drawn with Watch Lite's own shapes (spikes,
// puffs, rays, sparks) from the game's numbers: timing, size, colour, place
// and motion (data/impactEffects.js, tools/liteaudit/impact_effects/build.py).
// - A missed tech (entering DownBoundU 183 / DownBoundD 191, ftCo_DownBound.c)
//   spawns effect 1030 on the fighter, turned to the floor's slope: three
//   rings of green spikes, seen from the front, that widen and flatten over
//   about 9 frames (`crown`: per ring its base radius, the spikes' reach and
//   height, how many go round, and per frame the scale across and up and the
//   alpha), and effect 1031: white puffs of dust sliding out along the floor
//   (`dust`). Fountain of Dreams' floor names a stage effect instead of the
//   dust (mplib.c mpLib_80056B34), which is not drawn.
// - A shield break (entering ShieldBreakFly 205) spawns, from the fighter's
//   own action script (Pl*.dat action 286), a blue-white flare on its first
//   action frame and three electric bursts on action frames 1, 3 and 7
//   (`emit`: hitlag holds the action frame, so a broken-by-a-hit shield bursts
//   later), plus a small pale orb and specks (effect 1051). Each burst sits on
//   TopN (the fighter where it is then) offset by the model scale x
//   (facing x (4 + U3), U2) across and up and -facing x U1 in depth, U = 14 x
//   HSD_Randf - 7 (ftCo_8009F834), drawn from the global RNG right after its
//   per-frame reset: the frame's recorded seed, three draws in on the entry
//   frame (effect 1011 draws first). Checked against RAM on two breaks: within
//   0.8 units, depth within 0.001. Bursts behind the stage plane are drawn
//   before the fighters (drawImpactEffects `behind`), and not at all when
//   their heart is inside the stage body (the floor hides them in the game);
//   what falls inside the stage body is clipped, as the Fire Fox flame is.
//   Each part is drawn as its texture's picture (star `pose`: a flash, a
//   jagged ring, rays, scattered rays; lightning; twinkles), not copied.
// The rest is drawn after the fighters, like the hit sparks.
import IFX from './data/impactEffects.js'
import { insideBody, stageGeometryAt } from './liteStageInference.js'
import { fighterDataFor } from './stageData.js'
import { random } from './stageSim/rng.js'

const BOUNCE = new Set([183, 191]), SHIELD_BREAK = 205
const NO_DUST = new Set([2])           // Fountain of Dreams
const LAST = 60                        // longer than any of them lasts, in frames
const rgb = (s) => [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16))
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a))})`
const WHITE = [255, 255, 255]
// a stable pseudo-random number in [0, 1) from integers (the same picture on a seek as on play)
function hash(...n) {
  let h = 2166136261
  for (const v of n) h = Math.imul(h ^ (v | 0), 16777619) >>> 0
  h = Math.imul(h ^ (h >>> 15), 2246822507) >>> 0
  return ((h ^ (h >>> 13)) >>> 0) / 4294967296
}
const at = (list, i) => (list && i < list.length ? list[i] : undefined)

// the slope (radians) of the floor under (x, y) on idx, 0 when none is found
function floorAngle(bundle, idx, x, y) {
  let floors = []
  try { floors = stageGeometryAt(bundle, idx)?.floors || [] } catch { floors = [] }
  for (let [x0, y0, x1, y1] of floors) {
    if (x0 > x1) [x0, y0, x1, y1] = [x1, y1, x0, y0]
    if (x < x0 - 0.5 || x > x1 + 0.5 || x1 - x0 < 1e-6) continue
    if (Math.abs(y - (y0 + (y1 - y0) * (x - x0) / (x1 - x0))) <= 3) return Math.atan2(y1 - y0, x1 - x0)
  }
  return 0
}

function buried(bundle, idx, x, y) {
  try { return insideBody(stageGeometryAt(bundle, idx)?.fills, x, y) } catch { return false }
}

// The script's offset of a burst spawned on idx: [across, up, depth] in model
// units before the scale, or the offsets' mean without a recorded seed.
function burstOffset(bundle, idx, entry) {
  const c = random(bundle.frames.frame_seed?.[0]?.[idx])
  if (!c) return [4, 0, 0]
  if (entry) for (let n = 0; n < 3; n++) c.float()
  const [U1, U2, U3] = [0, 1, 2].map(() => 14 * c.float() - 7)
  return [4 + U3, U2, -U1]
}

// Every missed tech and shield break in the bundle: {idx, kind ('bounce' |
// 'shieldBreak'), x, y, angle, dust; a shield break's `bursts`: [{idx, x, y,
// z}]}. Cached.
const cache = new WeakMap()
export function impactEvents(bundle) {
  let out = cache.get(bundle)
  if (out) return out
  out = []
  const f = bundle?.frames
  if (f?.state) {
    const rows = f.state.map((st, i) => ({ st, x: f.x[i], y: f.y[i], age: f.age?.[i], cid: f.cid?.[i], dir: f.dir?.[i] }))
    for (const fo of f.fol || []) rows.push({ st: fo.state, x: fo.x, y: fo.y, age: fo.age, cid: fo.cid, dir: fo.dir })
    for (const r of rows) {
      for (let idx = 1; idx < r.st.length; idx++) {
        const s = r.st[idx], prev = r.st[idx - 1]
        if (s === prev || r.x[idx] == null) continue
        if (BOUNCE.has(s) && !BOUNCE.has(prev)) {
          const x = r.x[idx], y = r.y[idx]
          out.push({ idx, kind: 'bounce', x, y, angle: floorAngle(bundle, idx, x, y), dust: !NO_DUST.has(bundle.meta?.stage) })
        } else if (s === SHIELD_BREAK) {
          // each burst on the first frame its action frame is reached, where the fighter is then
          const bursts = []
          for (const e of IFX.shieldBreak.emit) {
            let j = idx
            while (j < r.st.length && r.st[j] === SHIELD_BREAK && (r.age?.[j] ?? j - idx + 1) < e - 0.01) j++
            if (j < r.st.length && r.st[j] === SHIELD_BREAK && r.x[j] != null) {
              const sc = fighterDataFor(r.cid?.[j])?.modelScale ?? 1, face = r.dir?.[j] || 1
              const [ax, up, dz] = burstOffset(bundle, j, j === idx)
              const x = r.x[j] + sc * face * ax, y = r.y[j] + sc * up, z = sc * face * dz || 0
              // behind the stage plane with its heart inside the stage body: the game's depth test hides it
              bursts.push({ idx: j, x, y, z, hidden: z < 0 && buried(bundle, j, x, y) })
            }
          }
          out.push({ idx, kind: 'shieldBreak', x: r.x[idx], y: r.y[idx], angle: 0, bursts })
        }
      }
    }
    out.sort((a, b) => a.idx - b.idx)
  }
  cache.set(bundle, out)
  return out
}

// Every effect alive on idx: with `behind`, only the shield-break bursts
// behind the stage plane (painted before the fighters), else everything else.
export function drawImpactEffects(ctx, bundle, idx, view, dpr, behind = false) {
  const events = impactEvents(bundle)
  if (!events.length) return
  ctx.save()
  const W = (x, y) => [dpr * (view.ox + view.S * x), dpr * (view.oy - view.S * y)]
  const u = dpr * view.S                 // pixels per world unit
  for (const ev of events) {
    if (ev.idx > idx) break
    const k = idx - ev.idx
    if (k >= LAST) continue
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    if (ev.kind === 'bounce') {
      if (behind) continue
      drawCrown(ctx, ev, k, W, u)
      if (ev.dust) drawDust(ctx, ev, k, W, u)
    } else {
      ctx.save()
      clipOutStage(ctx, bundle, idx, view, dpr)
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      drawShieldBreak(ctx, ev, idx, W, u, behind)
      ctx.restore()
    }
  }
  ctx.restore()
  ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}

// ---------------------------------------------------------------- missed tech
// A ring of spikes seen from the front: spike i stands at azimuth az round
// the ring, its tip `reach` x cos(az) out and `height` up (the frame's
// measured envelope), so the ones facing the camera stand up and the ones at
// the sides lean out. Lengths vary as the texture's flame-like spikes do; a
// white base, green, then clear at the tip, as the texture shades them.
function drawCrown(ctx, ev, k, W, u) {
  const C = IFX.crown, green = rgb(C.green)
  const [ox, oy] = W(ev.x, ev.y), c = Math.cos(ev.angle), s = Math.sin(ev.angle)
  // ring-local (across, up) in world units -> pixels, turned with the floor
  const P = (x, y) => [ox + u * (x * c - y * s), oy - u * (x * s + y * c)]
  C.rings.forEach((ring, ri) => {
    const a = at(ring.a, k)
    if (!(a > 0.004)) return
    const reach = ring.reach[k], height = ring.height[k]
    for (let i = 0; i < ring.n; i++) {
      const az = (i + 0.5 * ri) / ring.n * 2 * Math.PI, ca = Math.cos(az)
      const len = 0.55 + 0.45 * hash(ri, i)
      const bx = 0.25 * reach * ca, tx = reach * ca * len, ty = height * len
      const half = Math.max(0.3, (0.12 + 0.1 * Math.abs(Math.sin(az))) * Math.min(reach, 2 * height + 4) * 0.25)
      const [x0, y0] = P(bx - half, 0), [x1, y1] = P(bx + half, 0), [x2, y2] = P(tx, ty)
      if (ctx.createLinearGradient) {
        const g = ctx.createLinearGradient((x0 + x1) / 2, (y0 + y1) / 2, x2, y2)
        g.addColorStop(0, rgba(WHITE, a)); g.addColorStop(0.3, rgba(WHITE, 0.9 * a))
        g.addColorStop(0.55, rgba(green, 0.85 * a)); g.addColorStop(1, rgba(green, 0))
        ctx.fillStyle = g
      } else ctx.fillStyle = rgba(green, 0.6 * a)
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x2, y2); ctx.lineTo(x1, y1); ctx.closePath(); ctx.fill()
    }
  })
}

// White puffs born a few a frame, sliding out along the floor (seen from the
// front: across by the cosine of their direction), slowing by friction, rising
// and growing, then fading.
function drawDust(ctx, ev, k, W, u) {
  const D = IFX.dust
  let n = 0
  D.births.forEach((count, born) => {
    for (let j = 0; j < count; j++, n++) {
      const age = k - born
      if (age < 0 || age >= D.alpha.length) continue
      const dir = Math.cos(2 * Math.PI * hash(ev.idx, n, 7))
      let d = D.out, y = 0.2, v = D.speed, vy = D.rise
      for (let t = 0; t < age; t++) { v *= D.friction; vy = (vy - D.gravity) * D.friction; d += v; y += vy }
      const [px, py] = W(ev.x + d * dir, ev.y + y)
      const r = u * (D.size + D.grow * age), a = D.alpha[age]
      const g = ctx.createRadialGradient(px, py, 0, px, py, r)
      g.addColorStop(0, rgba(WHITE, 0.85 * a)); g.addColorStop(0.55, rgba(WHITE, 0.5 * a)); g.addColorStop(1, rgba(WHITE, 0))
      ctx.fillStyle = g
      ctx.beginPath(); ctx.arc(px, py, r, 0, 7); ctx.fill()
    }
  })
}

// ---------------------------------------------------------------- shield break
// The game blends every part by its alpha (none adds its light).
function drawShieldBreak(ctx, ev, idx, W, u, behind) {
  const SB = IFX.shieldBreak
  const k = idx - ev.idx
  const [ox, oy] = W(ev.x, ev.y)
  if (behind) {
    ev.bursts.forEach((b, bi) => { if (b.z < 0) drawBurst(ctx, b, bi, idx, W, u) })
    return
  }
  // effect 1051: a small pale orb, a glint and specks, where the shield broke
  if (at(SB.orb.size, k)) glow(ctx, ox, oy, u * SB.orb.size[k], rgb(SB.orb.colour), 0.8 * SB.orb.alpha[k])
  if (at(SB.glint.size, k)) glow(ctx, ox, oy, u * SB.glint.size[k], rgb(SB.glint.colour), SB.glint.alpha[k])
  if (at(SB.specks.size, k)) {
    for (let i = 0; i < SB.specks.n; i++) {
      const a = 2 * Math.PI * hash(ev.idx, i, 50), r = SB.specks.reach[k] * (0.4 + 0.6 * hash(ev.idx, i, 51))
      dot(ctx, ox + u * r * Math.cos(a), oy - u * r * Math.sin(a), Math.max(1, u * SB.specks.size[k]), WHITE, SB.specks.alpha[k])
    }
  }
  // effect 1011: the flare where the fighter was on its first action frame,
  // eight-pointed, then an X
  if (at(SB.flare.size, k)) flare(ctx, ox, oy, u * SB.flare.size[k], rgb(SB.flare.colour), SB.flare.alpha[k], at(SB.flare.pose, k) ?? 2)
  // the electric bursts in front of the stage plane
  ev.bursts.forEach((b, bi) => { if (!(b.z < 0)) drawBurst(ctx, b, bi, idx, W, u) })
}

// One electric burst, `a` frames old. Each part is the game's picture redrawn:
// white where its texture is bright, its colour where it fades (the colour is
// the env colour, lerped to white by the texture).
function drawBurst(ctx, b, bi, idx, W, u) {
  const SB = IFX.shieldBreak
  const a = idx - b.idx
  if (a < 0 || b.hidden) return
  const [bx, by] = W(b.x, b.y), seed = b.idx * 7 + bi
  // 15: a soft blue glow
  if (at(SB.glow.size, a)) glow(ctx, bx, by, 0.6 * u * SB.glow.size[a], rgb(SB.glow.colour), 0.6 * SB.glow.alpha[a])
  // 13: the star, a new picture each frame: a white flash, a jagged ring, a burst of rays, then scattered rays
  if (at(SB.star.size, a)) {
    const r = u * SB.star.size[a], col = rgb(SB.star.colour), al = SB.star.alpha[a], turn = hash(seed, 13, a) * Math.PI
    const pose = at(SB.star.pose, a) ?? 2
    if (pose === 0) flash(ctx, bx, by, r, col, al, turn)
    else if (pose === 1) jagRing(ctx, bx, by, r, col, al, turn, seed)
    else rayBurst(ctx, bx, by, r, col, al, turn, hash(seed, a, 19), pose === 3)
  }
  // 14: a purple-white spark of lightning at its heart, a new one each frame
  if (at(SB.sparkle.size, a)) {
    const ang = 2 * Math.PI * hash(seed, 14, a), r = SB.sparkle.reach[a] * hash(seed, 14, a, 1)
    zigzag(ctx, bx + u * r * Math.cos(ang), by - u * r * Math.sin(ang), u * SB.sparkle.size[a], 2 * Math.PI * hash(seed, 14, a, 2),
      rgb(SB.sparkle.colour), SB.sparkle.alpha[a], hash(seed, 14, a, 3))
  }
  // 16: small white twinkles flying out
  if (at(SB.sparks.size, a)) {
    for (let i = 0; i < SB.sparks.n; i++) {
      const ang = 2 * Math.PI * hash(seed, i, 16), r = SB.sparks.reach[a] * (0.55 + 0.45 * hash(seed, i, 17))
      twinkle(ctx, bx + u * r * Math.cos(ang), by - u * r * Math.sin(ang), u * SB.sparks.size[a], rgb(SB.sparks.colour), SB.sparks.alpha[a])
    }
  }
  // 17: purple lightning bolts and 18: small purple-white ray bursts, round
  // it, both jumping to a new place each frame
  for (const [part, id] of [[SB.bolts, 17], [SB.zaps, 18]]) {
    if (!at(part.size, a)) continue
    for (let i = 0; i < part.n; i++) {
      const ang = 2 * Math.PI * hash(seed, i, id, a), r = part.reach[a] * (0.3 + 0.7 * hash(seed, i, id, a, 1))
      const px = bx + u * r * Math.cos(ang), py = by - u * r * Math.sin(ang), turn = 2 * Math.PI * hash(seed, i, id, a, 2)
      if (id === 17) zigzag(ctx, px, py, u * part.size[a], turn, rgb(part.colour), part.alpha[a], hash(seed, i, id, a, 3))
      else rayBurst(ctx, px, py, u * part.size[a], rgb(part.colour), part.alpha[a], turn, hash(seed, i, id, a, 3), false)
    }
  }
}

// ---------------------------------------------------------------- shapes (pixels)
function glow(ctx, x, y, r, col, a) {
  if (!(r > 0.5) || !(a > 0.004)) return
  const g = ctx.createRadialGradient(x, y, 0, x, y, r)
  g.addColorStop(0, rgba(WHITE, a)); g.addColorStop(0.2, rgba(col, 0.7 * a)); g.addColorStop(0.55, rgba(col, 0.2 * a)); g.addColorStop(1, rgba(col, 0))
  ctx.fillStyle = g
  ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill()
}
function dot(ctx, x, y, r, col, a) {
  ctx.fillStyle = rgba(col, a)
  ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill()
}
// thin rays from the centre: a coloured halo, then (with `core`) a white core
function rays(ctx, x, y, list, col, a, core = true) {
  for (const [w, colour, alpha] of core ? [[1, col, 0.55 * a], [0.4, WHITE, a]] : [[1, col, 0.55 * a]]) {
    ctx.fillStyle = rgba(colour, alpha)
    for (const [ang, len, width] of list) {
      const c = Math.cos(ang), s = Math.sin(ang), hw = width * w
      ctx.beginPath()
      ctx.moveTo(x - s * hw, y - c * hw); ctx.lineTo(x + c * len, y - s * len); ctx.lineTo(x + s * hw, y + c * hw); ctx.lineTo(x - c * len * 0.15, y + s * len * 0.15)
      ctx.closePath(); ctx.fill()
    }
  }
}
// a white flash: a bright blob with a few broad spikes
function flash(ctx, x, y, r, col, a, turn) {
  glow(ctx, x, y, 0.75 * r, col, a)
  rays(ctx, x, y, Array.from({ length: 8 }, (_, i) => [turn + i * Math.PI / 4, r * (0.7 + 0.3 * hash(i, 31)), Math.max(1, r * 0.16)]), col, 0.8 * a)
}
// a jagged ring: a star-shaped outline, white with a coloured edge, its inside
// half see-through
function jagRing(ctx, x, y, r, col, a, turn, seed) {
  const pts = []
  for (let i = 0; i < 26; i++) {
    const ang = turn + i * Math.PI / 13, rr = r * (i % 2 ? 0.62 : 0.8 + 0.2 * hash(seed, i, 32))
    pts.push([x + rr * Math.cos(ang), y - rr * Math.sin(ang)])
  }
  const path = () => { ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.closePath() }
  ctx.fillStyle = rgba(col.map(c => (c + 255) / 2), 0.35 * a); path(); ctx.fill()
  ctx.lineJoin = 'miter'
  for (const [w, colour, alpha] of [[Math.max(2, r * 0.09), col, 0.6 * a], [Math.max(1, r * 0.04), WHITE, a]]) {
    ctx.strokeStyle = rgba(colour, alpha); ctx.lineWidth = w; path(); ctx.stroke()
  }
}
// a burst of thin white rays of mixed length round a white heart, or
// (`scattered`) broken streaks flying off it, the heart gone
function rayBurst(ctx, x, y, r, col, a, turn, j, scattered) {
  const key = (j * 1e9) | 0
  if (!scattered) {
    glow(ctx, x, y, 0.4 * r, col, a)
    rays(ctx, x, y, Array.from({ length: 20 }, (_, i) =>
      [turn + (i + 0.4 * hash(key, i, 33)) * Math.PI / 10, r * (0.5 + 0.5 * hash(key, i, 34)), Math.max(0.8, r * 0.05)]), col, a)
    return
  }
  ctx.lineCap = 'round'
  for (const [w, colour, alpha] of [[Math.max(1.2, r * 0.05), col, 0.5 * a], [Math.max(0.6, r * 0.02), WHITE, 0.9 * a]]) {
    ctx.strokeStyle = rgba(colour, alpha); ctx.lineWidth = w
    ctx.beginPath()
    for (let i = 0; i < 14; i++) {
      const ang = turn + (i + 0.6 * hash(key, i, 35)) * Math.PI / 7
      const r0 = r * (0.25 + 0.3 * hash(key, i, 36)), r1 = r * (0.65 + 0.35 * hash(key, i, 37))
      ctx.moveTo(x + r0 * Math.cos(ang), y - r0 * Math.sin(ang)); ctx.lineTo(x + r1 * Math.cos(ang), y - r1 * Math.sin(ang))
    }
    ctx.stroke()
  }
  ctx.lineCap = 'butt'
}
// a small four-point twinkle: a white dot with a cross of rays
function twinkle(ctx, x, y, r, col, a) {
  rays(ctx, x, y, [0, 1, 2, 3].map(i => [i * Math.PI / 2, r, Math.max(0.6, r * 0.12)]), col, a)
  dot(ctx, x, y, Math.max(1, 0.22 * r), WHITE, a)
}
// the 1011 flare: an eight-point star (`pose` 1), then an X with a faint
// cross (2), round a white heart
function flare(ctx, x, y, r, col, a, pose) {
  glow(ctx, x, y, 0.35 * r, col, 0.9 * a)
  rays(ctx, x, y, Array.from({ length: 8 }, (_, i) =>
    [i * Math.PI / 4, r * (i % 2 ? (pose === 1 ? 0.7 : 1) : (pose === 1 ? 1 : 0.45)), Math.max(1, r * 0.05)]), col, a)
}
// a short lightning bolt: a jagged line, coloured then a white core
function zigzag(ctx, x, y, len, turn, col, a, jitter) {
  const c = Math.cos(turn), s = Math.sin(turn), pts = []
  for (let i = 0; i <= 4; i++) {
    const t = (i / 4 - 0.5) * len, off = (i % 2 ? 1 : -1) * len * 0.18 * (0.6 + 0.8 * ((jitter * (i + 3) * 7.13) % 1))
    pts.push([x + c * t - s * off, y - s * t - c * off])
  }
  ctx.lineJoin = 'round'
  for (const [w, colour, alpha] of [[Math.max(1.5, len * 0.07), col, 0.7 * a], [Math.max(0.8, len * 0.025), WHITE, 0.8 * a]]) {
    ctx.strokeStyle = rgba(colour, alpha); ctx.lineWidth = w
    ctx.beginPath(); pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py))); ctx.stroke()
  }
}

// clip to everything but the stage body: a huge rectangle wound against its fills
function clipOutStage(ctx, bundle, idx, view, dpr) {
  let fills = []
  try { fills = stageGeometryAt(bundle, idx)?.fills || [] } catch { fills = [] }
  if (!fills.length) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  const wx = (v) => view.ox + v * view.S, wy = (v) => view.oy - v * view.S
  ctx.beginPath(); ctx.moveTo(-1e5, -1e5); ctx.lineTo(1e5, -1e5); ctx.lineTo(1e5, 1e5); ctx.lineTo(-1e5, 1e5); ctx.closePath()
  for (const poly of fills) poly.forEach(([px, py], i) => { i ? ctx.lineTo(wx(px), wy(py)) : ctx.moveTo(wx(px), wy(py)) })
  ctx.clip()
}
