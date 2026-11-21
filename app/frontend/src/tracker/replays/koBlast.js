// KO blasts: what the game draws when a fighter is KO'd through the left,
// right or bottom blast zone (melee decomp ft_0D31.c ftCo_800D3680, 800D3950,
// 800D3BC8; efasync.c 0x42B). Entering DeadLeft (1), DeadRight (2) or
// DeadDown (0) spawns effect 1067, EfCoData model 25:
// - where the fighter is that frame; a side KO's height and a bottom KO's x
//   are kept inside the stage's blast zones (data/koEffects.js zones);
// - turned so the model's +y points into the stage (-pi/2 on the left,
//   +pi/2 on the right, 0 at the bottom), scaled by ftCommonData +0x4F4;
// - its five meshes flash and stretch frame by frame (blast.frames: each
//   one's joint scale and translation and its alpha, as the game animates
//   them), drawn here as our own shapes in the boxes the meshes fill
//   (blast.layers): the flame that lingers, in the player's colours (TEV0 and
//   KONST by the colour index the game gives the player: its port, its team
//   in a team game, grey for a CPU, gm_80160854), a flash, a burst of rays, a
//   long beam and a green flame that flies out;
// - its particles (blast.particles: where each is, its size, turn, colours and
//   trail, read from RAM in effect space; the kind of shape it shows), drawn
//   as our own streaks, spikes, sparkles, stars, smoke and starbursts, turned
//   and scaled with it, after the meshes.
// No game art ships: the shapes are drawn here, from the game's numbers.
// It is see-through and drawn after the models: the game's frames show it over
// the stage and the fighters, so paintFrame draws it last.
// Star KOs and screen KOs are the fighter's own flight (koFlight.js).
import KO from './data/koEffects.js'

const B = KO.blast
const TURN = { 0: 0, 1: -Math.PI / 2, 2: Math.PI / 2 }
const css = (hex, a = 1) => `rgba(${parseInt(hex.slice(0, 2), 16)},${parseInt(hex.slice(2, 4), 16)},${parseInt(hex.slice(4, 6), 16)},${Math.max(0, Math.min(1, a))})`
// 'rrggbb' moved fraction t of the way to white
const pale = (hex, t) => [0, 2, 4].map((i) => Math.round(255 - (255 - parseInt(hex.slice(i, i + 2), 16)) * (1 - t)).toString(16).padStart(2, '0')).join('')

// gm_80160854: a team game colours by team (red 0, blue 1, green 3), else the
// port; a CPU is grey (4). Older bundles have no physical port: the player index.
export function colourIndex(bundle, i) {
  const pl = bundle.meta?.players?.[i]
  if (!pl || pl.cpu) return 4
  if (bundle.meta.teams && pl.team != null) return [0, 1, 3, 2][pl.team] ?? 4
  const port = pl.physical_port ?? i
  return port >= 0 && port < 4 ? port : 4
}

// a death row: states, x, y (a leader or Nana), with its player
function rowsOf(bundle) {
  const f = bundle.frames, rows = f.state.map((st, i) => ({ st, x: f.x[i], y: f.y[i], of: i }))
  for (const fo of f.fol || []) rows.push({ st: fo.state, x: fo.x, y: fo.y, of: fo.of })
  return rows
}

// Every side or bottom KO in the bundle: {idx, x, y, turn, colour}. Cached.
const cache = new WeakMap()
export function koEvents(bundle) {
  let out = cache.get(bundle)
  if (out) return out
  out = []
  const zone = KO.zones[bundle?.meta?.stage]
  if (bundle?.frames?.state) {
    for (const r of rowsOf(bundle)) {
      for (let idx = 1; idx < r.st.length; idx++) {
        const s = r.st[idx], prev = r.st[idx - 1]
        if (!(s in TURN) || prev == null || prev <= 11 || r.x[idx] == null) continue
        let x = r.x[idx], y = r.y[idx]
        if (zone) {
          const [left, right, top, bottom] = zone
          if (s === 0) x = Math.min(right, Math.max(left, x))
          else y = Math.min(top, Math.max(bottom, y))
        }
        out.push({ idx, x, y, turn: TURN[s], colour: colourIndex(bundle, r.of) })
      }
    }
    out.sort((a, b) => a.idx - b.idx)
  }
  cache.set(bundle, out)
  return out
}

// The meshes as shapes in their box, drawn in a unit square: u across (-1..1),
// v along the blast (-1 at the blast zone end, +1 into the playfield).
function poly(ctx, pts) {
  ctx.beginPath()
  pts.forEach(([u, v], i) => (i ? ctx.lineTo(u, v) : ctx.moveTo(u, v)))
  ctx.closePath()
}
function radial(ctx, stops, r = 1) {
  const g = ctx.createRadialGradient(0, 0, 0, 0, 0, r)
  for (const [at, col] of stops) g.addColorStop(at, col)
  return g
}
// jagged edge: points across u from -1 to 1 alternating between two heights
function teeth(n, lo, hi, flip = 1) {
  const out = []
  for (let i = 0; i <= n; i++) out.push([-1 + 2 * i / n, flip * (i % 2 ? lo : hi * (0.8 + 0.2 * Math.cos(i * 2.3)))])
  return out
}
const LAYER_SHAPES = [
  // 0: the player's flame, light (KONST) at its heart, the player's colour (TEV0) at its rim and tips
  (ctx, prim, env, a) => {
    poly(ctx, [[-0.55, -1], [-0.95, -0.55], [-1, 0.15], ...teeth(8, 0.55, 1), [1, 0.15], [0.95, -0.55], [0.55, -1]])
    const g = ctx.createLinearGradient(-1, 0, 1, 0)
    g.addColorStop(0, css(env, a)); g.addColorStop(0.35, css(prim, a)); g.addColorStop(0.65, css(prim, a)); g.addColorStop(1, css(env, a))
    ctx.fillStyle = g; ctx.fill()
  },
  // 1: the flash, a white glow
  (ctx, prim, env, a) => {
    ctx.fillStyle = radial(ctx, [[0, css(prim, a)], [0.55, css(env, 0.6 * a)], [1, css(env, 0)]])
    ctx.beginPath(); ctx.arc(0, 0, 1, 0, 7); ctx.fill()
  },
  // 2: the burst, white at its heart, blue toward its rim, with rays
  (ctx, prim, env, a) => {
    ctx.fillStyle = radial(ctx, [[0, css(prim, a)], [0.35, css(prim, 0.85 * a)], [0.6, css(env, 0.55 * a)], [1, css(env, 0)]])
    ctx.beginPath(); ctx.arc(0, 0, 1, 0, 7); ctx.fill()
    ctx.fillStyle = css(prim, 0.5 * a)
    for (let i = 0; i < 16; i++) {
      const t = i * Math.PI / 8, r = i % 2 ? 0.8 : 1, w = 0.05
      poly(ctx, [[Math.cos(t - w) * 0.25, Math.sin(t - w) * 0.25], [Math.cos(t) * r, Math.sin(t) * r], [Math.cos(t + w) * 0.25, Math.sin(t + w) * 0.25]])
      ctx.fill()
    }
  },
  // 3: the beam, a long white column with lavender edges and a ragged tip
  (ctx, prim, env, a) => {
    poly(ctx, [[-0.55, -1], [0.55, -1], [1, -0.85], [1, 0.8], ...teeth(6, 0.84, 1).reverse(), [-1, 0.8], [-1, -0.85]])
    const g = ctx.createLinearGradient(-1, 0, 1, 0)
    g.addColorStop(0, css(env, 0)); g.addColorStop(0.3, css(env, 0.7 * a)); g.addColorStop(0.5, css(prim, a))
    g.addColorStop(0.7, css(env, 0.7 * a)); g.addColorStop(1, css(env, 0))
    ctx.fillStyle = g; ctx.fill()
  },
  // 4: the green flame, a band across the blast, white along its middle and spiked both ways
  (ctx, prim, env, a) => {
    poly(ctx, [...teeth(12, 0.25, 0.85), ...teeth(11, 0.2, 0.7, -1).reverse()])
    const g = ctx.createLinearGradient(0, -1, 0, 1)
    g.addColorStop(0, css(env, 0.2 * a)); g.addColorStop(0.35, css(env, 0.8 * a)); g.addColorStop(0.5, css(prim, a))
    g.addColorStop(0.65, css(env, 0.8 * a)); g.addColorStop(1, css(env, 0.2 * a))
    ctx.fillStyle = g; ctx.fill()
  },
]

// One layer on frame row [layer, sx, sy, tx, ty, alpha]: its box (x0 y0 x1 y1
// in joint space) as the unit square, scaled and moved by the joint, turned
// and scaled with the effect at the KO.
function drawLayer(ctx, ev, row, view, dpr) {
  const [li, sx, sy, tx, ty, alpha] = row
  const [x0, y0, x1, y1, prim, env] = B.layers[li]
  const [tev0, konst] = B.colours[ev.colour] || B.colours[4]
  const hx = (x1 - x0) / 2, hy = (y1 - y0) / 2
  const qx = tx + sx * (x0 + x1) / 2, qy = ty + sy * (y0 + y1) / 2
  const c = Math.cos(ev.turn), s = Math.sin(ev.turn), k = view.S * B.scale
  const X = ev.x + B.scale * (c * qx - s * qy), Y = ev.y + B.scale * (s * qx + c * qy)
  ctx.setTransform(dpr * k * c * sx * hx, -dpr * k * s * sx * hx, -dpr * k * s * sy * hy, -dpr * k * c * sy * hy,
    dpr * (view.ox + view.S * X), dpr * (view.oy - view.S * Y))
  ctx.globalCompositeOperation = 'source-over'
  LAYER_SHAPES[li]?.(ctx, prim ?? konst, env ?? tev0, alpha)
}

// A particle [look, x, y, half size, turn (degrees), colours, additive,
// tail?] of effect `fx` ({looks, frames, colours}, data/koEffects.js) in its
// effect's units, placed at `at` ({x, y, turn}) scaled by `s`: our own shape
// for its look in a unit square, stretched back along its trail.
const PARTICLE_SHAPES = {
  // a thin line with a faint glow, paler than its light colour: the game's
  // streaks read white (even the pale yellow ones), and the wide beams stack
  // up along the blast, where a stronger or yellower glow, or the dark (env)
  // colour, built a yellow haze the game does not show
  streak: (ctx, p, e, a) => {
    p = pale(p, 0.6)
    poly(ctx, [[0, -1], [0.3, -0.6], [0.3, 0.6], [0, 1], [-0.3, 0.6], [-0.3, -0.6]])
    const g = ctx.createLinearGradient(-0.3, 0, 0.3, 0)
    g.addColorStop(0, css(p, 0)); g.addColorStop(0.3, css(p, 0.05 * a)); g.addColorStop(0.42, css(p, 0.6 * a))
    g.addColorStop(0.5, css(p, a)); g.addColorStop(0.58, css(p, 0.6 * a)); g.addColorStop(0.7, css(p, 0.05 * a)); g.addColorStop(1, css(p, 0))
    ctx.fillStyle = g; ctx.fill()
  },
  spikes: (ctx, p, e, a) => {
    ctx.fillStyle = css(p, 0.85 * a)
    for (const [x, h] of [[-0.6, 0.5], [-0.25, 1], [0.1, 0.7], [0.45, 0.9], [0.75, 0.4]]) {
      poly(ctx, [[x - 0.12, -1], [x, h], [x + 0.12, -1]]); ctx.fill()
    }
  },
  sparkle: (ctx, p, e, a) => {
    ctx.fillStyle = radial(ctx, [[0, css(p, a)], [0.4, css(e, 0.2 * a)], [1, css(e, 0)]], 0.45)
    ctx.beginPath(); ctx.arc(0, 0, 0.45, 0, 7); ctx.fill()
    ctx.fillStyle = css(p, a)
    poly(ctx, [[0, -1], [0.07, 0], [0, 1], [-0.07, 0]]); ctx.fill()
    poly(ctx, [[-1, 0], [0, 0.07], [1, 0], [0, -0.07]]); ctx.fill()
  },
  star: (ctx, p, e, a) => {
    ctx.fillStyle = radial(ctx, [[0, css(e, 0.3 * a)], [1, css(e, 0)]])
    ctx.beginPath(); ctx.arc(0, 0, 1, 0, 7); ctx.fill()
    const pts = []
    for (let i = 0; i < 10; i++) {
      const t = Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? 0.36 : 0.8
      pts.push([Math.cos(t) * r, Math.sin(t) * r])
    }
    poly(ctx, pts); ctx.fillStyle = css(p, a); ctx.fill()
  },
  smoke: (ctx, p, e, a) => {
    ctx.fillStyle = radial(ctx, [[0, css(p, 0.7 * a)], [0.6, css(p, 0.45 * a)], [1, css(e, 0)]])
    for (const [x, y, r] of [[0, 0, 0.8], [-0.35, 0.25, 0.55], [0.35, -0.2, 0.55]]) {
      ctx.save(); ctx.translate(x, y); ctx.scale(r, r); ctx.beginPath(); ctx.arc(0, 0, 1, 0, 7); ctx.fill(); ctx.restore()
    }
  },
  burst: (ctx, p, e, a) => {
    ctx.fillStyle = radial(ctx, [[0, css(p, a)], [0.3, css(e, 0.3 * a)], [1, css(e, 0)]], 0.5)
    ctx.beginPath(); ctx.arc(0, 0, 0.5, 0, 7); ctx.fill()
    ctx.fillStyle = css(p, 0.8 * a)
    for (let i = 0; i < 8; i++) {
      const t = i * Math.PI / 4, r = i % 2 ? 0.6 : 1
      poly(ctx, [[Math.cos(t - 0.08) * 0.15, Math.sin(t - 0.08) * 0.15], [Math.cos(t) * r, Math.sin(t) * r], [Math.cos(t + 0.08) * 0.15, Math.sin(t + 0.08) * 0.15]])
      ctx.fill()
    }
  },
}
export function drawEffectParticle(ctx, fx, p, at, s, view, dpr) {
  const draw = PARTICLE_SHAPES[(fx.looks || B.particles.looks)[p[0]]]
  if (!draw) return
  const [prim, env] = fx.colours[p[5]]
  const c = Math.cos(at.turn), sn = Math.sin(at.turn)
  let lx = p[1], ly = p[2], hw = p[3] * s, hh = hw, fade = 1
  const tail = p[7]
  if (tail) {
    lx += tail[0] / 2; ly += tail[1] / 2; hh += Math.hypot(tail[0], tail[1]) * s / 2; fade = (1 + tail[2]) / 2
  }
  const x = at.x + s * (c * lx - sn * ly), y = at.y + s * (sn * lx + c * ly)
  const a = p[4] * Math.PI / 180 + at.turn, ca = Math.cos(a), sa = Math.sin(a), S = view.S
  ctx.setTransform(dpr * S * ca * hw, -dpr * S * sa * hw, -dpr * S * sa * hh, -dpr * S * ca * hh,
    dpr * (view.ox + view.S * x), dpr * (view.oy - view.S * y))
  ctx.globalCompositeOperation = p[6] ? 'lighter' : 'source-over'
  ctx.globalAlpha = 1
  draw(ctx, prim, env, parseInt(prim.slice(6, 8) || 'ff', 16) / 255 * fade)
}

// Every KO blast showing on idx.
export function drawKoBlasts(ctx, bundle, idx, view, dpr) {
  const events = koEvents(bundle)
  if (!events.length) return
  for (const ev of events) {
    if (ev.idx > idx) break
    const k = idx - ev.idx, rows = B.frames[k], parts = B.particles.frames[k]
    if (!rows && !parts) continue
    ctx.save()
    for (const row of rows || []) drawLayer(ctx, ev, row, view, dpr)
    for (const p of parts || []) drawEffectParticle(ctx, B.particles, p, ev, B.scale, view, dpr)
    ctx.globalCompositeOperation = 'source-over'
    ctx.restore()
  }
  ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}
