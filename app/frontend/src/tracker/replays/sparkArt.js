// Our own drawings for the hit sparks' particles (hitSparks.js) and the tech
// effect's rays (techEffects.js). The game draws each particle with one of
// EfCoData.dat's particle textures; data/hitEffects.js says which one by its
// texture group and pose (`textures`: [group, pose, flags]), and this file draws
// a shape of our own that reads as it at a glance: a soft glow, a sparkle, a
// spiky burst, a streak, a bolt, a puff... Nothing here is the game's art.
//
// Every drawing fills the square -100..100 (y up) in the current transform.
// `hi` is the particle's bright colour (its primary), `lo` its dim one (its
// environment colour), `a` its alpha; additive particles add their light.

// a small seeded random, so a texture draws the same shape every frame
function rng(seed) {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6D2B79F5) >>> 0
    let t = Math.imul(s ^ (s >>> 15), 1 | s)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const css = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, Math.min(1, a))})`
const mix = (p, q, t) => [0, 1, 2].map((i) => p[i] + (q[i] - p[i]) * t)

function glow(ctx, r, inner, outer, a0, a1) {
  if (!ctx.createRadialGradient) {
    ctx.fillStyle = css(inner, a0)
    ctx.beginPath(); ctx.arc(0, 0, r * 0.6, 0, 7); ctx.fill()
    return
  }
  const g = ctx.createRadialGradient(0, 0, 0, 0, 0, r)
  g.addColorStop(0, css(inner, a0))
  g.addColorStop(0.45, css(mix(inner, outer, 0.5), (a0 + a1) / 2))
  g.addColorStop(1, css(outer, 0))
  ctx.fillStyle = g
  ctx.beginPath(); ctx.arc(0, 0, r, 0, 7); ctx.fill()
}

function softGlow(ctx, r, inner, outer, a) {
  if (!ctx.createRadialGradient) return disc(ctx, r * 0.3, inner, a)
  const g = ctx.createRadialGradient(0, 0, 0, 0, 0, r)
  g.addColorStop(0, css(inner, a)); g.addColorStop(0.15, css(mix(inner, outer, 0.4), 0.6 * a))
  g.addColorStop(0.45, css(outer, 0.15 * a)); g.addColorStop(1, css(outer, 0))
  ctx.fillStyle = g
  ctx.beginPath(); ctx.arc(0, 0, r, 0, 7); ctx.fill()
}

function disc(ctx, r, c, a) {
  ctx.fillStyle = css(c, a)
  ctx.beginPath(); ctx.arc(0, 0, r, 0, 7); ctx.fill()
}

// a star polygon: n points out to `out` (one radius, or a function of the point's
// index), pinched to `inner` between them, fading toward its tips
function star(ctx, n, out, inner, turn, c, a, tip = c) {
  const far = typeof out === 'function' ? Math.max(...Array.from({ length: n }, (_, i) => out(i))) : out
  if (ctx.createRadialGradient) {
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, far)
    g.addColorStop(0, css(c, a)); g.addColorStop(0.35, css(mix(c, tip, 0.5), 0.85 * a)); g.addColorStop(1, css(tip, 0))
    ctx.fillStyle = g
  } else ctx.fillStyle = css(c, a)
  ctx.beginPath()
  for (let i = 0; i < 2 * n; i++) {
    const r = i % 2 ? inner : typeof out === 'function' ? out(i / 2) : out
    const t = turn + (i * Math.PI) / n
    i ? ctx.lineTo(r * Math.sin(t), r * Math.cos(t)) : ctx.moveTo(r * Math.sin(t), r * Math.cos(t))
  }
  ctx.closePath(); ctx.fill()
}

// thin rays from the middle: n of them, lengths in [l0, l1], `w` wide at the base
function rays(ctx, n, seed, r0, l0, l1, w, c, a) {
  const R = rng(seed)
  ctx.fillStyle = css(c, a)
  ctx.beginPath()
  for (let i = 0; i < n; i++) {
    const t = ((i + 0.35 * R()) * 2 * Math.PI) / n, l = l0 + (l1 - l0) * R()
    const sx = Math.sin(t), cx = Math.cos(t), px = cx * w / 2, py = -sx * w / 2
    ctx.moveTo(r0 * sx + px, r0 * cx + py)
    ctx.lineTo(l * sx, l * cx)
    ctx.lineTo(r0 * sx - px, r0 * cx - py)
  }
  ctx.fill()
}

// a lens (a streak pointed at both ends) from (x0, y0) to (x1, y1), w wide
function lens(ctx, x0, y0, x1, y1, w, bend = 0) {
  const dx = x1 - x0, dy = y1 - y0, l = Math.hypot(dx, dy) || 1, nx = -dy / l, ny = dx / l
  const mx = (x0 + x1) / 2 + nx * bend, my = (y0 + y1) / 2 + ny * bend
  ctx.moveTo(x0, y0)
  ctx.quadraticCurveTo(mx + nx * w, my + ny * w, x1, y1)
  ctx.quadraticCurveTo(mx - nx * w, my - ny * w, x0, y0)
}

function streak(ctx, hi, lo, a) {
  ctx.fillStyle = css(lo, 0.35 * a)
  ctx.beginPath(); lens(ctx, 0, -98, 0, 98, 14); ctx.fill()
  ctx.fillStyle = css(hi, a)
  ctx.beginPath(); lens(ctx, 0, -95, 0, 95, 5); ctx.fill()
}

// a zigzag from (x0, y0) to (x1, y1)
function bolt(ctx, seed, x0, y0, x1, y1, hi, lo, a) {
  const R = rng(seed), n = 6, pts = [[x0, y0]]
  const dx = x1 - x0, dy = y1 - y0, l = Math.hypot(dx, dy) || 1
  for (let i = 1; i < n; i++) {
    const j = (R() - 0.5) * 0.45 * l
    pts.push([x0 + (dx * i) / n - (dy / l) * j, y0 + (dy * i) / n + (dx / l) * j])
  }
  pts.push([x1, y1])
  ctx.lineJoin = 'round'; ctx.lineCap = 'round'
  for (const [c, w, al] of [[lo, 16, 0.45], [hi, 5, 1]]) {
    ctx.strokeStyle = css(c, al * a); ctx.lineWidth = w
    ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke()
  }
}

// a soft cloud of a few round blobs
function puff(ctx, seed, n, spread, size, hi, lo, a, dark = 0) {
  const R = rng(seed)
  for (let i = 0; i < n; i++) {
    const t = R() * 2 * Math.PI, d = spread * Math.sqrt(R()), r = size * (0.6 + 0.5 * R())
    ctx.save(); ctx.translate(d * Math.sin(t), d * Math.cos(t))
    glow(ctx, r, mix(hi, lo, 0.35 + dark), lo, 0.55 * a, 0.3 * a)
    ctx.restore()
  }
}

// a burst of flame tongues around a bright middle
function flames(ctx, seed, n, l0, l1, hi, lo, a) {
  glow(ctx, 95, hi, lo, 0.35 * a, 0.15 * a)
  const R = rng(seed)
  ctx.fillStyle = css(mix(hi, lo, 0.4), 0.85 * a)
  ctx.beginPath()
  for (let i = 0; i < n; i++) {
    const t = ((i + R() * 0.6) * 2 * Math.PI) / n, l = l0 + (l1 - l0) * R(), w = 10 + 10 * R()
    const sx = Math.sin(t), cx = Math.cos(t), bend = (R() - 0.5) * 18
    ctx.moveTo(cx * w + sx * 18, -sx * w + cx * 18)
    ctx.quadraticCurveTo(sx * l * 0.55 + cx * bend, cx * l * 0.55 - sx * bend, sx * l, cx * l)
    ctx.quadraticCurveTo(sx * l * 0.55 + cx * bend * 0.4, cx * l * 0.55 - sx * bend * 0.4, -cx * w + sx * 18, sx * w + cx * 18)
  }
  ctx.fill()
  disc(ctx, 30, hi, 0.9 * a)
}

// the normal hit's comic burst: a jagged, outlined shape
function comic(ctx, seed, hi, lo, a) {
  const R = rng(seed), n = 13, pts = []
  for (let i = 0; i < 2 * n; i++) {
    const t = (i * Math.PI) / n + (R() - 0.5) * 0.12, r = i % 2 ? 50 + 12 * R() : 80 + 18 * R()
    pts.push([r * Math.sin(t), r * Math.cos(t)])
  }
  ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath()
  ctx.fillStyle = css(mix(lo, hi, 0.12), 0.9 * a); ctx.fill()
  ctx.lineJoin = 'miter'; ctx.lineWidth = 7; ctx.strokeStyle = css(hi, a); ctx.stroke()
}

// a fan of streaks closing in at the bottom
function fan(ctx, seed, n, hi, lo, a) {
  const R = rng(seed)
  for (let i = 0; i < n; i++) {
    const t = ((i / Math.max(1, n - 1)) - 0.5) * 0.9 + (R() - 0.5) * 0.15, l = 120 + 60 * R()
    const x1 = Math.sin(t) * l, y1 = -92 + Math.cos(t) * l
    ctx.fillStyle = css(lo, 0.35 * a); ctx.beginPath(); lens(ctx, 0, -92, x1, y1, 12); ctx.fill()
    ctx.fillStyle = css(hi, a); ctx.beginPath(); lens(ctx, 0, -92, x1, y1, 5); ctx.fill()
  }
}

function snowflake(ctx, hi, lo, a) {
  glow(ctx, 70, hi, lo, 0.45 * a, 0.25 * a)
  ctx.lineCap = 'round'
  for (const [c, w, al] of [[lo, 18, 0.55], [hi, 7, 1]]) {
  ctx.strokeStyle = css(c, al * a); ctx.lineWidth = w
  ctx.beginPath()
  for (let i = 0; i < 6; i++) {
    const t = (i * Math.PI) / 3, sx = Math.sin(t), cx = Math.cos(t)
    ctx.moveTo(sx * 14, cx * 14); ctx.lineTo(sx * 94, cx * 94)
    for (const [d, b] of [[45, 20], [70, 15]]) {
      for (const s of [-1, 1]) {
        const u = t + s * 0.75
        ctx.moveTo(sx * d, cx * d); ctx.lineTo(sx * d + Math.sin(u) * b, cx * d + Math.cos(u) * b)
      }
    }
  }
  ctx.stroke()
  }
}

// where each of the 8 lightning bolts (group 6) runs in its square
const BOLTS = [[5, 90, -15, 15], [-75, 30, 25, 5], [-30, -10, 85, -15], [-20, -10, 10, -90],
  [-50, -40, 15, -90], [55, 85, 50, 10], [-70, -10, -15, -95], [-35, -15, 10, -60]]

// texture group -> its poses' drawings
const ART = {
  2: [
    (c, h, l, a) => { glow(c, 98, h, l, 0.85 * a, 0.45 * a); star(c, 4, 96, 12, 0, h, a, l); star(c, 4, 55, 10, Math.PI / 4, h, 0.8 * a, l); disc(c, 20, h, a) },
    (c, h, l, a) => comic(c, 21, h, l, a),
    (c, h, l, a) => { glow(c, 85, h, l, 0.55 * a, 0.3 * a); rays(c, 18, 22, 8, 55, 98, 7, h, a); disc(c, 16, h, a) },
    (c, h, l, a) => { glow(c, 70, h, l, 0.45 * a, 0.2 * a); rays(c, 14, 23, 12, 40, 96, 9, h, a); disc(c, 24, h, a) },
    (c, h, l, a) => puff(c, 24, 6, 50, 48, h, l, 0.8 * a),
    (c, h, l, a) => { bolt(c, 25, -90, 70, -40, 90, h, l, a); bolt(c, 26, 50, 50, 90, 10, h, l, a); bolt(c, 27, -60, -50, -10, -85, h, l, a) },
  ],
  4: [(c, h, l, a) => { glow(c, 40, h, l, 0.6 * a, 0.2 * a); star(c, 4, 96, 6, 0, h, a, l) }],
  5: [
    (c, h, l, a) => { glow(c, 90, l, l, 0.35 * a, 0.15 * a); rays(c, 24, 51, 10, 45, 95, 5, mix(h, l, 0.6), 0.85 * a); disc(c, 9, h, a) },
    (c, h, l, a) => softGlow(c, 95, h, l, a),
    (c, h, l, a) => flames(c, 53, 12, 45, 85, mix(h, l, 0.5), l, a),
  ],
  6: BOLTS.map((p, i) => (c, h, l, a) => bolt(c, 60 + i, p[0], p[1], p[2], p[3], h, l, a)),
  7: [
    (c, h, l, a) => flames(c, 70, 14, 45, 70, h, l, a),
    (c, h, l, a) => flames(c, 71, 16, 55, 85, h, l, a),
    (c, h, l, a) => flames(c, 72, 18, 60, 95, h, l, a),
    (c, h, l, a) => flames(c, 73, 20, 65, 98, h, l, a),
    (c, h, l, a) => puff(c, 74, 7, 45, 45, h, l, a, 0.3),
  ],
  8: [(c, h, l, a) => { glow(c, 70, h, l, 0.5 * a, 0.3 * a); star(c, 8, (i) => (i % 2 ? 70 : 97), 16, 0, h, a, l) }],
  11: [0, 1, 2, 3, 4].map((p) => (c, h, l, a) => puff(c, 110 + p, 5, 40, 50, h, l, a, 0.25)),
  16: [0, 1, 2, 3].map((p) => (c, h, l, a) => {
    const R = rng(160 + p)
    for (let i = 0; i < 7; i++) {
      c.save(); c.translate((R() - 0.5) * 150, (R() - 0.5) * 150); disc(c, 4 + 4 * R(), h, a); c.restore()
    }
  }),
  17: [(c, h, l, a) => snowflake(c, h, l, a)],
  21: [
    (c, h, l, a) => { disc(c, 74, h, a); rays(c, 12, 210, 60, 88, 98, 10, h, a) },
    ...[1, 2, 3, 4, 5].map((p) => (c, h, l, a) => {
      c.strokeStyle = css(h, a); c.lineWidth = 15 - 2 * p
      c.beginPath(); c.arc(0, 0, 90, 0, 7); c.stroke()
      c.strokeStyle = css(l, 0.5 * a); c.lineWidth = 4
      c.beginPath(); c.arc(0, 0, 40 + 6 * p, 0, 7); c.stroke()
    }),
  ],
  23: [(c, h, l, a) => streak(c, h, l, a)],
  24: [(c, h, l, a) => streak(c, h, l, a)],
  25: [
    (c, h, l, a) => { glow(c, 80, h, l, 0.8 * a, 0.4 * a); star(c, 4, 80, 7, 0, h, a, l) },
    (c, h, l, a) => { glow(c, 80, h, l, 0.8 * a, 0.4 * a); star(c, 4, 80, 7, 0, h, a, l) },
    (c, h, l, a) => { glow(c, 85, h, l, 0.8 * a, 0.4 * a); star(c, 6, 82, 7, 0, h, a, l) },
  ],
  26: [0, 1, 2, 3, 4, 5].map((p) => (c, h, l, a) => {
    puff(c, 260 + p, 6, 45, 42, h, l, 1.3 * a, 0.45)
    flames(c, 270 + p, 5, 40, 80, mix(h, l, 0.6), l, 0.6 * a)
  }),
  32: [[5], [3], [5], [3]].map(([n], p) => (c, h, l, a) => fan(c, 320 + p, n, h, l, a)),
  33: [
    (c, h, l, a) => star(c, 4, 92, 5, Math.PI / 4, h, a),
    (c, h, l, a) => {
      for (const [d, w] of [[0, 9], [26, 6]]) {
        c.fillStyle = css(l, 0.8 * a); c.beginPath(); lens(c, -80 + d, -50 + d, 70 + d, 75 + d, 2.4 * w, -28); c.fill()
        c.fillStyle = css(h, a); c.beginPath(); lens(c, -80 + d, -50 + d, 70 + d, 75 + d, w, -28); c.fill()
      }
    },
    (c, h, l, a) => {
      for (const [d, w] of [[0, 7], [-22, 5]]) {
        c.fillStyle = css(l, 0.8 * a); c.beginPath(); lens(c, -60 + d, -30 + d, 75 + d, 55 + d, 2.4 * w, -24); c.fill()
        c.fillStyle = css(h, a); c.beginPath(); lens(c, -60 + d, -30 + d, 75 + d, 55 + d, w, -24); c.fill()
      }
    },
  ],
}


// Draw texture `tex` ([group, pose, flags]: 4 flips left to right, 8 upside
// down) as our own shape, coloured hi/lo at alpha a, added when `additive`.
export function drawArt(ctx, tex, hi, lo, a, additive) {
  const draw = ART[tex[0]]?.[tex[1]]
  if (!draw || !(a > 0.004)) return
  ctx.globalCompositeOperation = additive ? 'lighter' : 'source-over'
  ctx.globalAlpha = 1
  const fs = tex[2] & 4, ft = tex[2] & 8
  if (fs || ft) { ctx.save(); ctx.scale(fs ? -1 : 1, ft ? -1 : 1) }
  draw(ctx, hi, lo, a)
  if (fs || ft) ctx.restore()
}

// a soft round glow of our own (the tech effect's glow): hi in the middle
// fading through lo, `r` the radius in the current transform
export function drawGlow(ctx, r, hi, lo, a, additive) {
  ctx.globalCompositeOperation = additive ? 'lighter' : 'source-over'
  ctx.globalAlpha = 1
  glow(ctx, r, hi, lo, a, 0.45 * a)
}
