// Sword trails: the swoosh Link, Young Link, Marth and Roy leave behind a
// swing. The game's rule (melee decomp, ftafterimage.c), with the tables from
// the ISO in data/hits/<cid>.json `trail` (tools/liteaudit/sword_trails/build.py):
// - The move's subaction script starts a trail (command 0x31, value 0) and
//   stops it (-1); any other motion change stops it too. The tables keep, per
//   action state, the action frames it is on and, for each, the sword joint's
//   position and X axis (model scale included), fighter-local.
// - Every frame that did not start in hitlag pushes the joint into a ring of
//   three (ftCo_800C2FD8). In a replay the action frame counter stands still
//   through hitlag, so a frame whose counter did not move pushes nothing.
// - With two or more samples the game draws one strip after the fighter's
//   model (ftCo_800C2600): per sample the blade from inner to outer along the
//   axis, from the newest sample to the oldest, where the edges have moved to
//   the `old` fractions of the blade; between samples the axis turns about
//   their cross product in steps of 5 degrees while the joint moves straight.
//   Inner and outer edges take their own colours; alpha runs from `alpha[0]`
//   at the newest sample to `alpha[1]` at the oldest by the distance the tip
//   travelled (as the game measures it, trailStrip); blended over what is
//   behind (src-alpha / inv-src-alpha).
// - A held Beam Sword (any fighter's Swing states: the command's item bit)
//   follows the sword item instead (data/hits/<cid>.json `beam`): its bone 5
//   on the hand and that bone's Y axis, inner 0, outer 10.03 x the blade's
//   live length (x10 x x28 x x4C x 0.3, it_802852B8; the swing's own commands
//   stretch it), colours and fade from the item's attributes (it_80285300).
//   The game measures every sample with the newest push's blade.
// Watch Lite draws the strip seen from the front: the quads go additively into
// a scratch canvas, where neighbours' shared edges add up to exactly one
// coverage (no seams), and that is blended over the frame once. Hosts with no
// canvas of their own (Node audits) get the quads filled directly.
import { hitDataFor } from './stageData.js'

const STEP = 0.0872664600610733     // 5 degrees (ftafterimage.c)
const RING = 3                      // Fighter +0x20B0[3]
const MAX_GAP = 6                   // device px between strip rows (alpha and taper stay smooth)

function windowsFor(T, state) {
  let w = T.states[state]
  if (typeof w === 'number') w = T.states[w]
  return Array.isArray(w) ? w : null
}
// the joint at a (possibly fractional) action frame of the window [first, last, rows]
function rowAt(w, age) {
  const k = Math.floor(age) - w[0], r = w[2][k], n = w[2][k + 1], u = age - Math.floor(age)
  if (!n || !(u > 0)) return r
  return r.map((v, i) => v + (n[i] - v) * u)
}

// The ring a fighter row holds on idx for the table `kind` ('trail', its own
// sword; 'beam', a held Beam Sword), newest first, in world space:
// [{ b: [x, y, z] joint, a: [x, y, z] axis, o?: blade outer }], or null below
// two samples.
export function trailSamples(cid, states, ages, xs, ys, dirs, idx, kind = 'trail') {
  const T = hitDataFor(cid)?.[kind], state = states?.[idx], age = ages?.[idx]
  if (!T || state == null || !Number.isFinite(age)) return null
  const ws = windowsFor(T, state)
  const f = Math.floor(age), w = ws && ws.find(([a, b]) => f >= a && f <= b)
  if (!w) return null
  const out = []
  for (let j = idx; j >= 0 && out.length < RING; j--) {
    const aj = ages[j]
    if (states[j] !== state || !Number.isFinite(aj) || Math.floor(aj) < w[0]) break
    if (j < idx && aj > ages[j + 1]) break                       // an earlier run of the same state
    if (j > 0 && states[j - 1] === state && ages[j - 1] === aj) continue   // hitlag: no push
    const s = rowAt(w, aj), d = dirs?.[j] || 1
    out.push({ b: [xs[j] + d * s[0], ys[j] + s[1], d * s[2]], a: [d * s[3], s[4], d * s[5]], o: s[6] })
  }
  return out.length >= 2 ? out : null
}

const sub = (p, q) => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const len = (p) => Math.hypot(p[0], p[1], p[2])
const along = (b, a, s) => [b[0] + a[0] * s, b[1] + a[1] * s, b[2] + a[2] * s]
function cross(p, q) { return [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]] }
// v turned by `angle` about the unit axis k (right-handed)
function rotate(v, k, angle) {
  const c = Math.cos(angle), s = Math.sin(angle), kv = k[0] * v[0] + k[1] * v[1] + k[2] * v[2], x = cross(k, v)
  return [0, 1, 2].map(i => v[i] * c + x[i] * s + k[i] * kv * (1 - c))
}

// The strip ftCo_800C2600 builds from the ring: rows newest to oldest,
// { i: inner [x, y, z], o: outer, a: alpha 0..1 }.
export function trailStrip(T, samples) {
  // The distances the alpha and taper follow, as the game measures them: each
  // step is the tip less the previous step's difference vector, not the
  // previous tip (800C2908 keeps the difference), so past the first step it
  // depends on where in the world the fighter stands.
  const cum = [0]
  let total = 0, prev = [0, 0, 0]
  samples.forEach((s, k) => {
    const delta = sub(along(s.b, s.a, T.outer), prev)
    if (k) cum.push(total += len(delta))
    prev = delta
  })
  if (total < 1e-5) total = 1
  const span = T.outer - T.inner
  const oldIn = T.old[0] * span + T.inner, oldOut = T.old[1] * span + T.inner
  // t: 1 at the newest sample, 0 at the oldest
  const edge = (t) => [t * (T.inner - oldIn) + oldIn, t * (T.outer - oldOut) + oldOut, t * (T.alpha[0] - T.alpha[1]) + T.alpha[1]]
  const rows = []
  const push = (b, a, [si, so, al]) => rows.push({ i: along(b, a, si), o: along(b, a, so), a: al })
  for (let k = 0; k < samples.length; k++) {
    const cur = samples[k], e = edge(1 - cum[k] / total)
    push(cur.b, cur.a, e)
    const nxt = samples[k + 1]
    if (!nxt) break
    const c = cross(cur.a, nxt.a), cl = len(c), la = len(cur.a) * len(nxt.a)
    if (!(cl > 1e-10) || !(la > 1e-10)) continue
    const angle = Math.acos(Math.max(-1, Math.min(1, (cur.a[0] * nxt.a[0] + cur.a[1] * nxt.a[1] + cur.a[2] * nxt.a[2]) / la)))
    const m = Math.floor(angle / STEP)
    const k2 = c.map(v => v / cl), e2 = edge(1 - cum[k + 1] / total)
    for (let j = 1; j <= m; j++) {
      const u = j / (m + 1)
      push(cur.b.map((v, i) => v + (nxt.b[i] - v) * u), rotate(cur.a, k2, angle * u), e.map((v, i) => v + (e2[i] - v) * u))
    }
  }
  return rows
}

let scratch = null
// a cleared 2D context at least w x h, or null where the host has no canvas
function scratchContext(w, h) {
  if (!scratch) {
    if (typeof OffscreenCanvas === 'function') scratch = new OffscreenCanvas(w, h)
    else if (typeof document !== 'undefined' && document.createElement) scratch = document.createElement('canvas')
    else return null
  }
  if (scratch.width < w) scratch.width = w
  if (scratch.height < h) scratch.height = h
  const c = scratch.getContext('2d')
  if (!c) return null
  c.setTransform(1, 0, 0, 1, 0, 0)
  c.globalCompositeOperation = 'source-over'
  c.globalAlpha = 1
  c.clearRect(0, 0, w, h)
  return c
}

const rgb = (hex) => [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16))
// one strip, its rows already in device px ({ i: [x, y], o: [x, y], a })
function fillStrip(c, rows, T, additive) {
  const [ci, co] = T.color.map(rgb)
  const mid = ci.map((v, k) => (v + co[k]) / 2 | 0)
  c.globalCompositeOperation = additive ? 'lighter' : 'source-over'
  for (let k = 0; k + 1 < rows.length; k++) {
    const p = rows[k], q = rows[k + 1], alpha = (p.a + q.a) / 2
    if (!(alpha > 0.002)) continue
    c.globalAlpha = Math.min(1, alpha)
    if (c.createLinearGradient) {
      const g = c.createLinearGradient((p.i[0] + q.i[0]) / 2, (p.i[1] + q.i[1]) / 2, (p.o[0] + q.o[0]) / 2, (p.o[1] + q.o[1]) / 2)
      g.addColorStop(0, `rgb(${ci})`); g.addColorStop(1, `rgb(${co})`)
      c.fillStyle = g
    } else c.fillStyle = `rgb(${mid})`
    c.beginPath()
    c.moveTo(p.i[0], p.i[1]); c.lineTo(p.o[0], p.o[1]); c.lineTo(q.o[0], q.o[1]); c.lineTo(q.i[0], q.i[1])
    c.closePath(); c.fill()
  }
  c.globalCompositeOperation = 'source-over'; c.globalAlpha = 1
}

// rows seen from the front in device px, with extra rows in a long step so
// the alpha and the taper change smoothly (the game interpolates per vertex)
function deviceRows(rows, view, dpr) {
  const px = (p) => [(view.ox + p[0] * view.S) * dpr, (view.oy - p[1] * view.S) * dpr]
  const out = []
  rows.forEach((r, k) => {
    const cur = { i: px(r.i), o: px(r.o), a: r.a }, prev = out[out.length - 1]
    if (prev) {
      const n = Math.min(32, Math.floor(Math.max(Math.hypot(cur.o[0] - prev.o[0], cur.o[1] - prev.o[1]),
        Math.hypot(cur.i[0] - prev.i[0], cur.i[1] - prev.i[1])) / MAX_GAP))
      for (let j = 1; j <= n; j++) {
        const u = j / (n + 1), lerp = (p, q) => [p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u]
        out.push({ i: lerp(prev.i, cur.i), o: lerp(prev.o, cur.o), a: prev.a + (cur.a - prev.a) * u })
      }
    }
    out.push(cur)
  })
  return out
}

export function drawSwordTrails(ctx, bundle, idx, view, dpr) {
  const f = bundle?.frames
  if (!f?.x) return
  for (let p = 0; p < f.x.length; p++) for (const kind of ['trail', 'beam']) {
    const cid = f.cid?.[p]?.[idx], table = hitDataFor(cid)?.[kind]
    if (!table) continue
    const samples = trailSamples(cid, f.state[p], f.age?.[p], f.x[p], f.y[p], f.dir?.[p], idx, kind)
    if (!samples) continue
    // the Beam Sword's blade runs from its joint (inner 0) to the newest push's length
    const T = kind === 'beam' ? { ...table, inner: 0, outer: samples[0].o } : table
    const rows = deviceRows(trailStrip(T, samples), view, dpr)
    if (rows.length < 2) continue
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const r of rows) for (const [x, y] of [r.i, r.o]) {
      x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y)
    }
    x0 = Math.floor(x0) - 2; y0 = Math.floor(y0) - 2
    const w = Math.ceil(x1) + 2 - x0, h = Math.ceil(y1) + 2 - y0
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    const c = w > 0 && h > 0 && w * h <= 4096 * 4096 ? scratchContext(w, h) : null
    if (!c) { fillStrip(ctx, rows, T, false); continue }
    const local = rows.map(r => ({ i: [r.i[0] - x0, r.i[1] - y0], o: [r.o[0] - x0, r.o[1] - y0], a: r.a }))
    fillStrip(c, local, T, true)
    ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
    ctx.drawImage(c.canvas, 0, 0, w, h, x0, y0, w, h)
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}
