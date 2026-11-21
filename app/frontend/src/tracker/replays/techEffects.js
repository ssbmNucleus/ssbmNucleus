// Techs: what the game draws when a fighter techs (melee decomp). Entering any
// tech state - in place (199), a tech roll (200, 201), on a wall (202), the
// wall jump (203), on a ceiling (204) - spawns effect 1053 (EfCoData model 15)
// (ftCo_Passive.c, ftCo_PassiveStand.c, ftCo_PassiveWall.c,
// ftCo_PassiveCeil.c). Watch Lite draws it with shapes of its own, sized, turned,
// coloured and timed by the game's numbers (data/hitEffects.js):
// - eight thin gold rays closing in (the effect's particle generator 261,
//   effects.tech, drawn like the hit sparks' particles);
// - a yellow glow fading in under them (tech.glow: its size, colours and fade);
// - two spinning rings (tech.rings): each a pinwheel of four streaky arcs, white
//   with a red rim, in the plane the game turns the ring's model to every frame.
//   The game draws them see-through after the fighters and the stage,
//   depth-tested against them, so the half of each ring behind the fighter
//   (z < 0) and whatever lies inside the stage are hidden. Here the half behind
//   is drawn before the stage and the fighters (drawTechRings 'back'), so they
//   cover it, and the half in front after them, clipped out of the stage's
//   body. A pass-through platform is only a line here, but in game its body
//   hides the rings under it too: a tech on one keeps them out from under it;
// - it sits where the fighter is for a floor tech, at the fighter's side
//   toward the wall for a wall tech or wall jump, and on top of the fighter for
//   a ceiling tech (tech.wall, tech.ceil).
import FX from './data/hitEffects.js'
import { drawHitEffect } from './hitSparks.js'
import { drawGlow } from './sparkArt.js'
import { insideBody } from './liteStageInference.js'

const TECH = new Set([199, 200, 201, 202, 203, 204])
const WALL = new Set([202, 203]), CEIL = 204
const rgb = (s) => [0, 2, 4, 6].map((i) => (i < s.length ? parseInt(s.slice(i, i + 2), 16) : 255))

// the frame a fighter row enters a tech state (a wall tech turning into its
// wall jump is the same tech: no second effect, ftCo_PassiveWall.c)
function entersTech(states, idx) {
  const s = states[idx], prev = states[idx - 1]
  return TECH.has(s) && prev !== s && !(s === 203 && prev === 202)
}

// Every tech in the bundle: {idx, x, y} where its effect sits, and `side`
// where the surface it teched on lies from it ('floor', 'ceil', or +1 / -1 for
// a wall to its right / left). Cached.
const cache = new WeakMap()
export function techEvents(bundle) {
  let out = cache.get(bundle)
  if (out) return out
  out = []
  const f = bundle?.frames, T = FX.tech
  if (f?.state && T) {
    const rows = f.state.map((st, i) => ({ st, x: f.x[i], y: f.y[i], dir: f.dir?.[i] }))
    for (const fo of f.fol || []) rows.push({ st: fo.state, x: fo.x, y: fo.y, dir: fo.dir })
    for (const r of rows) {
      for (let idx = 1; idx < r.st.length; idx++) {
        if (!entersTech(r.st, idx) || r.x[idx] == null) continue
        const s = r.st[idx]
        let x = r.x[idx], y = r.y[idx], side = 'floor'
        // a wall tech leaves the fighter facing away from the wall
        if (WALL.has(s)) { side = -(r.dir?.[idx] || 1); x += side * T.wall[0]; y += T.wall[1] }
        else if (s === CEIL) { side = 'ceil'; y += T.ceil }
        out.push({ idx, x, y, side })
      }
    }
    out.sort((a, b) => a.idx - b.idx)
  }
  cache.set(bundle, out)
  return out
}

// ---------------------------------------------------------------- the rings
const RINGS = FX.tech?.rings
// a lobe's streaks, in the lobe's own size: [radius, from, to (degrees round
// from one of its edges to the other), half width, alpha]; the outer one's rim
// is red (where the game's ring texture runs out of light)
const ARCS = [[0.45, 25, 65, 0.05, 0.7], [0.66, 20, 70, 0.06, 0.9], [0.86, 15, 75, 0.07, 1]]
const RIM = [0.95, 18, 72, 0.035, 0.9]
const STEPS = 14

// the world vector (x, y, z) of a lobe-plane vector (u, v): u x a + v x b
const along = (ax, u, v) => [u * ax[0] + v * ax[3], u * ax[1] + v * ax[4], u * ax[2] + v * ax[5]]

// One streak of one lobe as the pieces of it on one side of the fighters'
// plane (sign 1: z >= 0, -1: z < 0): polygons [[x, y], ...] in world units
// from the effect.
function streakPieces(E10, E01, [r, from, to, hw], sign) {
  const pts = []
  for (let i = 0; i <= STEPS; i++) {
    const t = i / STEPS, th = ((from + (to - from) * t) * Math.PI) / 180
    const h = hw * Math.sin(Math.PI * t) ** 0.7, c = Math.cos(th), s = Math.sin(th)
    const at = (rr) => [rr * (c * E10[0] + s * E01[0]), rr * (c * E10[1] + s * E01[1]), rr * (c * E10[2] + s * E01[2])]
    const mid = at(r)
    pts.push({ out: at(r + h), in: at(r - h), front: mid[2] >= 0 })
  }
  const pieces = []
  let run = []
  const close = () => {
    if (run.length > 1) pieces.push([...run.map((p) => p.out), ...run.reverse().map((p) => p.in)])
    run = []
  }
  for (const p of pts) {
    if ((sign > 0) === p.front) run.push(p)
    else close()
  }
  close()
  return pieces
}

function fillPieces(ctx, pieces, ev, colour, alpha, view, dpr) {
  if (!pieces.length || !(alpha > 0.004)) return
  ctx.fillStyle = `rgba(${colour[0] | 0},${colour[1] | 0},${colour[2] | 0},${Math.min(1, alpha)})`
  ctx.beginPath()
  for (const poly of pieces) {
    poly.forEach(([x, y], i) => {
      const px = dpr * (view.ox + view.S * (ev.x + x)), py = dpr * (view.oy - view.S * (ev.y + y))
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)
    })
    ctx.closePath()
  }
  ctx.fill()
}

// One ring on one side of the fighters' plane: its lobes' streaks, white (its
// TEV's KONST) with a red (TEV0) rim, mixed toward the material's white and
// faded by the BLEND track as the game does (tobj.c).
function drawRing(ctx, ev, lobes, [ax, blend, konst, tev0], sign, view, dpr) {
  const white = rgb(RINGS.base), k = rgb(konst), t0 = rgb(tev0)
  const tint = (c) => [0, 1, 2].map((i) => white[i] * (1 - blend) + c[i] * blend)
  const core = tint(k), rim = tint(t0)
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.globalCompositeOperation = 'source-over'
  ctx.globalAlpha = 1
  for (const [u0, v0, u1, v1] of lobes) {
    const E10 = along(ax, u0, v0), E01 = along(ax, u1, v1)
    fillPieces(ctx, streakPieces(E10, E01, RIM, sign), ev, rim, RIM[4] * blend, view, dpr)
    for (const arc of ARCS) fillPieces(ctx, streakPieces(E10, E01, arc, sign), ev, core, arc[4] * blend, view, dpr)
  }
}

// how far the rings reach from the effect, in world units
const REACH = Math.max(0, ...(RINGS?.frames || []).flatMap((row) => row.flatMap(([ax], i) =>
  RINGS.lobes[i].map(([u0, v0, u1, v1]) => {
    const p = along(ax, u0 + u1, v0 + v1)
    return Math.hypot(p[0], p[1])
  }))))

// A floor tech on a pass-through platform (a floor with no stage body under
// it): the band under the platform's line, as deep as the rings reach, which
// its body hides in game. Null for any other tech.
function platformBand(stage, ev) {
  if (ev.side !== 'floor' || !stage?.floors) return null
  for (const [x0, y0, x1, y1] of stage.floors) {
    if (x0 === x1 || ev.x < Math.min(x0, x1) - 0.5 || ev.x > Math.max(x0, x1) + 0.5) continue
    const y = y0 + (y1 - y0) * (ev.x - x0) / (x1 - x0)
    if (Math.abs(y - ev.y) > 1) continue
    if (insideBody(stage.fills, ev.x, y - 0.5)) return null
    return [[x0, y0], [x1, y1], [x1, y1 - REACH], [x0, y0 - REACH]]
  }
  return null
}

// Clip what follows out of these polygons (world units): one clip per polygon,
// each the canvas minus that polygon, so they intersect.
function clipOutOf(ctx, polys, view, dpr) {
  const W = ctx.canvas.width, H = ctx.canvas.height
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  for (const poly of polys) {
    ctx.beginPath()
    ctx.rect(0, 0, W, H)
    poly.forEach((p, i) => {
      const x = dpr * (view.ox + view.S * p[0]), y = dpr * (view.oy - view.S * p[1])
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
    })
    ctx.closePath()
    ctx.clip('evenodd')
  }
}

// Every live tech's ring halves behind the fighters' plane ('back': call it
// before the stage and the fighters are drawn, which cover it) or in front of
// it ('front'), kept out from under the platform it teched on. `stage` is the
// frame's stage geometry (stageGeometryAt).
export function drawTechRings(ctx, bundle, idx, view, dpr, layer, stage = null) {
  if (!RINGS?.frames.length) return
  for (const ev of techEvents(bundle)) {
    if (ev.idx > idx) break
    const row = RINGS.frames[idx - ev.idx]
    if (!row) continue
    const band = platformBand(stage, ev)
    ctx.save()
    if (band) clipOutOf(ctx, [band], view, dpr)
    row.forEach((ring, i) => drawRing(ctx, ev, RINGS.lobes[i], ring, layer === 'back' ? -1 : 1, view, dpr))
    ctx.restore()
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}

// Every tech effect alive on idx, in the game's order: the effect's model (a
// ring's front half, the glow, the other ring's front half: kept out of the
// stage's body and from under the platform it teched on; `stage` the frame's
// stage geometry), then its particles (the rays).
export function drawTechEffects(ctx, bundle, idx, view, dpr, stage = null) {
  const T = FX.tech
  if (!T) return
  const events = techEvents(bundle)
  if (!events.length) return
  const n = Math.max(T.glow.length, RINGS?.frames.length || 0, FX.effects.tech?.frames.length || 0)
  for (const ev of events) {
    if (ev.idx > idx) break
    const k = idx - ev.idx
    if (k >= n) continue
    const rings = RINGS?.frames[k] || []
    const band = platformBand(stage, ev)
    const hide = [...(stage?.fills || []), ...(band ? [band] : [])]
    const front = (i) => {
      if (!rings[i]) return
      ctx.save()
      if (hide.length) clipOutOf(ctx, hide, view, dpr)
      drawRing(ctx, ev, RINGS.lobes[i], rings[i], 1, view, dpr)
      ctx.restore()
    }
    ctx.save()
    front(0)
    const g = T.glow[k]
    if (g) {
      // [blend, KONST, TEV0, half size]: KONST in the middle fading through TEV0,
      // added (its PE), mixed over the material's white by the blend
      const [blend, konst, tev0, half] = g, white = rgb(RINGS?.base || 'ffffff')
      const tint = (c) => [0, 1, 2].map((i) => white[i] * (1 - blend) + c[i] * blend)
      const S = view.S * half * 0.01
      ctx.setTransform(dpr * S, 0, 0, -dpr * S, dpr * (view.ox + view.S * ev.x), dpr * (view.oy - view.S * ev.y))
      drawGlow(ctx, 100, tint(rgb(konst)), tint(rgb(tev0)), blend, true)
      ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
    }
    for (let i = 1; i < rings.length; i++) front(i)
    drawHitEffect(ctx, { kind: 'tech', x: ev.x, y: ev.y, scale: 1, facing: 1, turn: 0 }, k, view, dpr)
    ctx.restore()
  }
  ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}
