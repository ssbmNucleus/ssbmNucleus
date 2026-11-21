// Watch Lite's own drawings of the items and effects the game shows with its
// models, sprites and textures: flat shapes, strokes and licks of flame, made
// here. The game supplies numbers only (data/itemMetrics.js, measured from the
// vanilla ISO by tools/liteaudit/item_shapes/build.py): how big a thing is,
// its colours, where it sits and how that changes frame by frame. Nothing here
// is traced or copied from the game's art. Units are world units around the
// position Slippi records, x right and y up; wx / wy map them to the canvas.
import M from './data/itemMetrics.js'

export const METRICS = M
const TAU = 2 * Math.PI

// A polygon of local points around (ox, oy), turned by `ang` (radians, CCW)
// and mirrored in x first when `mirror` is -1.
export function shapePath(ctx, pts, ox, oy, ang, mirror, wx, wy) {
  const c = Math.cos(ang), s = Math.sin(ang)
  ctx.beginPath()
  pts.forEach(([px, py], i) => {
    const mx = px * mirror
    const X = ox + mx * c - py * s, Y = oy + mx * s + py * c
    i ? ctx.lineTo(wx(X), wy(Y)) : ctx.moveTo(wx(X), wy(Y))
  })
  ctx.closePath()
}
function fillPts(ctx, pts, ox, oy, ang, mirror, wx, wy, colour, alpha = 1) {
  ctx.globalAlpha = alpha
  shapePath(ctx, pts, ox, oy, ang, mirror, wx, wy)
  ctx.fillStyle = colour; ctx.fill()
  ctx.globalAlpha = 1
}
// n points round an ellipse, turned by `rot`
function ellipsePts(cx, cy, rx, ry, n = 16, rot = 0) {
  const c = Math.cos(rot), s = Math.sin(rot), out = []
  for (let i = 0; i < n; i++) {
    const a = i / n * TAU, x = rx * Math.cos(a), y = ry * Math.sin(a)
    out.push([cx + x * c - y * s, cy + x * s + y * c])
  }
  return out
}
// a box with rounded corners
function roundBox(x0, y0, x1, y1, r, n = 3) {
  r = Math.max(0, Math.min(r, (x1 - x0) / 2, (y1 - y0) / 2))
  const out = []
  const corner = (cx, cy, a0) => {
    for (let i = 0; i <= n; i++) { const a = a0 + i / n * Math.PI / 2; out.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]) }
  }
  corner(x1 - r, y0 + r, -Math.PI / 2); corner(x1 - r, y1 - r, 0)
  corner(x0 + r, y1 - r, Math.PI / 2); corner(x0 + r, y0 + r, Math.PI)
  return out
}
const lerp = (a, b, t) => a + (b - a) * t

// Onett's cars: a body up to the hood line, a cabin leaning in to the roof
// with two windows, a headlight at the front (toward -x) and two wheels on the
// road. Mirrored for the far lane.
export function drawCar(ctx, car, x, y, mirror, wx, wy) {
  const [x0, x1] = car.x, belt = car.belt, roof = car.roof, [r0, r1] = car.span
  const wr = Math.min(...car.wheels.map(w => w[1])), sill = wr * 0.7
  const lean = (roof - belt) * 0.6
  const c0 = Math.max(x0 + 0.5, r0 - lean), c1 = Math.min(x1 - 0.5, r1 + lean)
  ctx.lineJoin = 'round'; ctx.lineWidth = 1.5; ctx.strokeStyle = '#8a93ab'
  const cabin = [[c0, belt - 0.3], [r0, roof], [r1, roof], [c1, belt - 0.3]]
  const body = roundBox(x0, sill, x1, belt, Math.min(1.6, (belt - sill) / 2))
  for (const pts of [cabin, body]) {
    shapePath(ctx, pts, x, y, 0, mirror, wx, wy)
    ctx.fillStyle = car.body; ctx.fill(); ctx.stroke()
  }
  // the windows: the cabin inset, split by its pillar
  const yb = belt + 0.45, yt = roof - 0.6, t = (h) => (h - belt + 0.3) / (roof - belt + 0.3)
  const xl = (h) => lerp(c0, r0, t(h)) + 0.65, xr = (h) => lerp(c1, r1, t(h)) - 0.65
  const mid = (r0 + r1) / 2
  if (yt > yb + 0.4) {
    for (const [a, b] of [[(h) => xl(h), () => mid - 0.4], [() => mid + 0.4, (h) => xr(h)]]) {
      if (b(yt) - a(yt) < 0.3) continue
      fillPts(ctx, [[a(yb), yb], [a(yt), yt], [b(yt), yt], [b(yb), yb]], x, y, 0, mirror, wx, wy, '#c9dcf0', 0.9)
    }
  }
  const ly = sill + (belt - sill) * 0.62
  fillPts(ctx, ellipsePts(x0 + 0.55, ly, 0.5, 0.5, 10), x, y, 0, mirror, wx, wy, '#ffe9a0')
  fillPts(ctx, ellipsePts(x1 - 0.45, ly, 0.4, 0.4, 10), x, y, 0, mirror, wx, wy, '#ff6a5a')
  for (const [cx, r] of car.wheels) {
    fillPts(ctx, ellipsePts(cx, r, r, r, 16), x, y, 0, mirror, wx, wy, '#1e1e1e')
    fillPts(ctx, ellipsePts(cx, r, r * 0.45, r * 0.45, 10), x, y, 0, mirror, wx, wy, '#8a93ab')
  }
}

// The Ice Climbers' ice: a block of ice with a pointed top, and a lighter face
// that slides across it as it turns about its upright axis once a second; its
// width follows the turn (`k` frames into its state).
export function drawIce(ctx, k, x, y, wx, wy) {
  const I = M.ice, t = ((Math.floor(k) % 60) + 60) % 60
  const w = I.w[Math.floor(t / 5) % I.w.length], [y0, y1] = I.y, mid = (y0 + y1) / 2
  const block = [[-w, y0], [-0.8 * w, mid], [-0.22 * w, y1], [0.22 * w, y1], [0.8 * w, mid], [w, y0]]
  fillPts(ctx, block, x, y, 0, 1, wx, wy, I.colour, 0.9)
  ctx.lineWidth = 1; ctx.strokeStyle = '#7c8a96'; ctx.stroke()
  const fx = Math.sin(t / 60 * TAU) * 0.45 * w
  fillPts(ctx, [[fx - 0.3 * w, y0], [fx + 0.3 * w, y0], [fx * 0.3 + 0.08 * w, y1 - 0.5], [fx * 0.3 - 0.08 * w, y1 - 0.5]],
    x, y, 0, 1, wx, wy, '#eef4f8', 0.55)
}

// Samus's missile, nose along `ang`: a body with tail fins and a pointed nose,
// its tip in the nose colour.
export function drawMissile(ctx, x, y, ang, wx, wy) {
  const m = M.missile, [t, n] = m.x, r = m.r, L = n - t
  const body = [[t, 1.5 * r], [t + 0.25 * L, 0.75 * r], [n - 0.3 * L, 0.75 * r], [n, 0],
    [n - 0.3 * L, -0.75 * r], [t + 0.25 * L, -0.75 * r], [t, -1.5 * r], [t + 0.12 * L, 0]]
  fillPts(ctx, body, x, y, ang, 1, wx, wy, m.body)
  fillPts(ctx, ellipsePts(n - 0.17 * L, 0, 0.17 * L, 0.62 * r, 12), x, y, ang, 1, wx, wy, m.nose)
}

// Peach's turnip: three leaves fanning up from a round bulb with a short root
// and a little face. The origin is the top of the bulb.
export function drawTurnip(ctx, ox, oy, ang, mirror, wx, wy) {
  const T = M.turnip, [bx0, bx1, by0, by1] = T.bulb
  const cx = (bx0 + bx1) / 2, rx = (bx1 - bx0) / 2, ry = (by1 - by0) * 0.42, cy = by1 - ry
  const L = T.top - by1 + 0.4
  for (const a of [-0.55, 0, 0.55]) {
    const leaf = ellipsePts(0, L / 2, 0.75, L / 2, 12).map(([px, py]) =>
      [cx + px * Math.cos(a) - py * Math.sin(a), by1 - 0.4 + px * Math.sin(a) + py * Math.cos(a)])
    fillPts(ctx, leaf, ox, oy, ang, mirror, wx, wy, T.leaves)
  }
  const low = cy - by0 - 0.7
  const bulb = []
  for (let i = 0; i < 20; i++) {
    const a = i / 20 * TAU, s = Math.sin(a)
    bulb.push([cx + rx * Math.cos(a), cy + (s >= 0 ? ry : low) * s])
  }
  fillPts(ctx, bulb, ox, oy, ang, mirror, wx, wy, T.bulbColour)
  fillPts(ctx, [[cx - 0.55, cy - low * 0.92], [cx, by0], [cx + 0.55, cy - low * 0.92]], ox, oy, ang, mirror, wx, wy, T.bulbColour)
  for (const ex of [-0.95, 0.95]) fillPts(ctx, ellipsePts(cx + ex, cy - 0.2, 0.32, 0.45, 8), ox, oy, ang, mirror, wx, wy, '#2c2c24')
}

// Yoshi's egg around a swallowed fighter: an egg, fuller at the bottom, its
// bottom at 0 (unit size; meleeRender scales it by the victim).
let eggPts = null
export function eggOutline() {
  if (!eggPts) {
    const { w, h } = M.egg, rb = 0.44 * h, rt = h - rb
    eggPts = []
    for (let i = 0; i < 28; i++) {
      const a = i / 28 * TAU, c = Math.cos(a)
      eggPts.push([w * Math.sin(a), rb - c * (c >= 0 ? rb : rt)])
    }
  }
  return eggPts
}

// Yoshi's egg as a shell of our own: white with green spots, the unit egg
// (eggOutline) scaled by s, its bottom `lift` below (ox, oy), turned by `ang`
// about (ox, oy) and mirrored with `mirror`. `stroke` outlines it.
const EGG_SPOTS = [[-1.3, 3.6, 0.75], [1.2, 2.2, 0.85], [0.6, 4.9, 0.5], [-0.9, 1.1, 0.55]]
export function drawEggShell(ctx, ox, oy, s, lift, ang, mirror, wx, wy, stroke = '#aab4cc') {
  const pts = eggOutline().map(([px, py]) => [px * s, py * s - lift])
  shapePath(ctx, pts, ox, oy, ang, mirror, wx, wy)
  ctx.fillStyle = '#f2f0e6'; ctx.fill()
  ctx.lineWidth = 1.2; ctx.strokeStyle = stroke; ctx.stroke()
  for (const [sx, sy, sr] of EGG_SPOTS) fillPts(ctx, ellipsePts(sx * s, sy * s - lift, sr * s, sr * s, 12), ox, oy, ang, mirror, wx, wy, '#3fae49')
}
// Yoshi's thrown egg (Egg Throw, item 86): its article's box is 3 each way
// times its scale 1.3 (PlYs.dat article 0), so 7.8 tall around the item point.
// It turns as it flies, about 20 degrees a frame (from playback Dolphin frames).
export const EGG_THROW = { h: 7.8, spin: 20 * Math.PI / 180 }
export function drawThrownEgg(ctx, x, y, ang, wx, wy) {
  drawEggShell(ctx, x, y, EGG_THROW.h / M.egg.h, EGG_THROW.h / 2, ang, 1, wx, wy)
}
// The egg breaking (state 2, ityoshieggthrow.c it_802B2C38): a white flash
// while its blast hitbox is out (`hit` frames, radius R), then shell pieces
// flying out and falling, gone after `life` frames.
export function drawEggBreak(ctx, age, x, y, R, hit, wx, wy, life = 20) {
  if (age < 0 || age >= life) return
  const S = Math.abs(wx(1) - wx(0)), u = age / life
  if (age < hit) {
    ctx.globalAlpha = 0.7 * (1 - age / hit); ctx.fillStyle = '#ffffff'
    ctx.beginPath(); ctx.arc(wx(x), wy(y), Math.max(1, R * 0.45 * (0.6 + 0.4 * (age + 1) / hit) * S), 0, TAU); ctx.fill()
  }
  const shard = [[-1.1, -0.5], [0, 0.9], [1.1, -0.5], [0, -0.1]]
  for (let j = 0; j < 6; j++) {
    const a = j * TAU / 6 + 0.26, d = 2 + 9 * u
    const px = x + Math.cos(a) * d, py = y + Math.sin(a) * d - 6 * u * u
    fillPts(ctx, shard.map(([sx, sy]) => [sx * 1.3, sy * 1.3]), px, py, j + age * 0.3, 1, wx, wy, j % 2 ? '#3fae49' : '#f2f0e6', u > 0.7 ? (1 - u) / 0.3 : 1)
  }
  ctx.globalAlpha = 1
}

// Link's and Young Link's boomerang: a V of two arms, `r` its half span (the
// item's body radius), turned by `ang`.
export function drawBoomerang(ctx, x, y, r, ang, colour, wx, wy) {
  const S = Math.abs(wx(1) - wx(0)), half = 0.92, c = Math.cos(ang), s = Math.sin(ang)
  const at = (px, py) => [wx(x + px * c - py * s), wy(y + px * s + py * c)]
  const tipY = r * 0.12, elbowY = -r * 0.42   // a wide V, about 120 degrees
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'
  ctx.strokeStyle = colour; ctx.lineWidth = Math.max(2, r * 0.38 * S)
  ctx.beginPath(); ctx.moveTo(...at(-r * half, tipY)); ctx.lineTo(...at(0, elbowY)); ctx.lineTo(...at(r * half, tipY)); ctx.stroke()
  ctx.strokeStyle = '#8a6a40'; ctx.lineWidth = Math.max(1, r * 0.1 * S)
  ctx.beginPath(); ctx.moveTo(...at(-r * half * 0.8, tipY * 0.8)); ctx.lineTo(...at(0, elbowY * 0.75)); ctx.lineTo(...at(r * half * 0.8, tipY * 0.8)); ctx.stroke()
}
export const BOOMERANG_SPIN = 40 * Math.PI / 180

// Link's and Young Link's bomb before it blows: a round bomb of its body
// radius r, a light glint, the fuse cap on top and its spark, which flickers.
export function drawRoundBomb(ctx, x, y, r, age, colour, wx, wy) {
  const S = Math.abs(wx(1) - wx(0))
  const disc = (cx, cy, rr, col) => { ctx.fillStyle = col; ctx.beginPath(); ctx.arc(wx(cx), wy(cy), Math.max(0.8, rr * S), 0, TAU); ctx.fill() }
  disc(x, y, r, colour)
  disc(x - 0.35 * r, y + 0.35 * r, 0.25 * r, '#8fa3d8')
  fillPts(ctx, [[-0.22 * r, 0.85 * r], [0.22 * r, 0.85 * r], [0.22 * r, 1.2 * r], [-0.22 * r, 1.2 * r]], x, y, 0, 1, wx, wy, '#c8ccd8')
  disc(x, y + 1.32 * r, (age % 4 < 2 ? 0.26 : 0.18) * r, '#ffd34d')
}

// A lick of fire flying along `ang` (Bowser's breath): a flame with a round
// head of radius r at the item point and its tail streaming back, a hot core.
export function drawFireLick(ctx, x, y, r, ang, age, wx, wy) {
  const a = ang - Math.PI / 2
  fillPts(ctx, teardrop(0, r, -2.4 * r, r, age * 1.7), x, y, a, 1, wx, wy, '#ff7a2f', 0.85)
  fillPts(ctx, teardrop(0, 0.55 * r, -1.2 * r, 0.6 * r, age * 1.7 + 2), x, y, a, 1, wx, wy, '#ffd36a', 0.9)
}

// Ness's PK Fire in flight: a short jagged bolt along `ang`, 2.6 r long.
export function drawPkFireBolt(ctx, x, y, r, ang, wx, wy) {
  const S = Math.abs(wx(1) - wx(0)), c = Math.cos(ang), s = Math.sin(ang)
  const pts = [[1.3, 0], [0.45, 0.45], [0.2, -0.3], [-0.55, 0.35], [-1.3, 0]].map(([u, v]) => [u * r, v * r])
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'
  for (const [col, w] of [['#ff6a3d', 0.55], ['#ffe08a', 0.22]]) {
    ctx.strokeStyle = col; ctx.lineWidth = Math.max(1, w * r * S); ctx.beginPath()
    pts.forEach(([u, v], i) => { const X = wx(x + u * c - v * s), Y = wy(y + u * s + v * c); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y) })
    ctx.stroke()
  }
}

// Mario's and Luigi's fireball before its spin: a ball of flame with five soft
// licks round its centre; the bright core is drawn over it (litePaint).
const fireballCache = {}
export function fireballPts(kind) {
  if (!fireballCache[kind]) {
    const [fx, fy, R] = M.fireball[kind].flame, out = []
    for (let i = 0; i < 30; i++) {
      const a = i / 30 * TAU, r = R * (0.9 + 0.13 * Math.cos(5 * a + 0.3) + 0.04 * Math.cos(3 * a))
      out.push([fx + r * Math.cos(a), fy + r * Math.sin(a)])
    }
    fireballCache[kind] = out
  }
  return fireballCache[kind]
}

// Fire Fox / Fire Bird charging, frame `a` of its loop: a faint ring on the
// floor, a column of light, and a crown of flame licks flaring out from the
// feet, all at the game's sizes for that frame.
export function drawFlameCharge(ctx, a, x, y, wx, wy, S) {
  const C = M.flame.charge, [foot, top, h, colW, colH, ringW] = C[((a % C.length) + C.length) % C.length]
  ctx.globalAlpha = 0.35; ctx.strokeStyle = '#ffe070'; ctx.lineWidth = 2
  ctx.beginPath(); ctx.ellipse(wx(x), wy(y + 0.5), ringW * S, Math.max(1, 1.2 * S), 0, 0, 7); ctx.stroke()
  ctx.globalAlpha = 1
  fillPts(ctx, [[-colW, 0], [-colW * 0.75, colH], [colW * 0.75, colH], [colW, 0]], x, y, 0, 1, wx, wy, '#fff3a8', 0.35)
  const N = 7, crown = [[-foot, 0], [-top, 0.62 * h]]
  for (let i = 0; i < N; i++) {
    const um = ((i + 0.5) / N) * 2 - 1
    crown.push([um * top, h * (0.72 + 0.28 * Math.sin(i * 2.3 + a * 1.9)) * (1 - 0.2 * um * um)])
    if (i < N - 1) crown.push([(((i + 1) / N) * 2 - 1) * top * 0.98, 0.5 * h])
  }
  crown.push([top, 0.62 * h], [foot, 0])
  fillPts(ctx, crown, x, y, 0, 1, wx, wy, '#ffcf3a', 0.6)
}

// A flame trailing back from a round head: the head at `front`, the tail at
// `back`, its sides licking (local units: y along the travel, x across it).
// The game's extent includes its licks, so the solid body is a little narrower.
function teardrop(cx, hw, back, front, ph) {
  const R = Math.max(0.1, Math.min(0.75 * hw, (front - back) * 0.4)), hy = front - R, N = 9
  const pts = []
  for (let i = 0; i <= 8; i++) { const t = Math.PI * i / 8; pts.push([cx + R * Math.cos(t), hy + R * Math.sin(t)]) }
  const side = (j, s) => {
    const t = j / N, w = R * Math.pow(1 - t, 0.85) * (1 + 0.22 * Math.sin(j * 2.1 + ph + (s > 0 ? 1.7 : 0)))
    return [cx + s * w * (j % 2 ? 1 : 0.78), hy - t * (hy - back)]
  }
  for (let j = 1; j < N; j++) pts.push(side(j, -1))
  pts.push([cx, back])
  for (let j = N - 1; j >= 1; j--) pts.push(side(j, 1))
  return pts
}
// Fire Fox / Fire Bird travelling, frame `a` of its plume's loop: the plume and
// its bright core as flames streaming back along the travel line.
export function plumePts(a) {
  const T = M.flame.travel, [ox, ow, ob, of, cx, cw, cb, cf] = T[((a % T.length) + T.length) % T.length]
  return { outer: teardrop(ox, ow, ob, of, a * 1.3), core: teardrop(cx, cw, cb, cf, a * 1.3 + 3) }
}
export const flameHips = (cid) => M.flame.hips[cid]

// A PK Thunder tail piece's zigzag (texture `j` of its four), 4 long, from its
// position (x 0) back to x -4, as high as that texture's.
export function pkTrailLine(kind, j) {
  const amp = M.pkTrail[kind].amp[j % 4], n = 6, out = []
  for (let i = 0; i <= n; i++) {
    const s = (i + j) % 2 ? 1 : -1
    out.push([-4 + 4 * i / n, i === 0 || i === n ? 0 : s * amp * (0.55 + 0.45 * (((i * 5 + j * 3) % 4) / 3))])
  }
  return out
}
export const pkTrailColour = (kind) => M.pkTrail[kind].colour

// Thunder's bolt (texture `j` of its four): our own jagged bolt down 40 units
// from the item point, across the width that texture's bolt spans. Corners
// are [down, across] in fractions of the bolt (0 = its left edge, 1 = right);
// each texture takes the four shapes in turn, mirrored on odd ones.
const BOLTS = [
  [[0, 0.55], [0.14, 0.3], [0.2, 0.62], [0.38, 0.18], [0.45, 0.5], [0.63, 0.08], [0.7, 0.45], [0.86, 0.25], [1, 0.5]],
  [[0, 0.5], [0.1, 0.78], [0.27, 0.35], [0.33, 0.7], [0.52, 0.12], [0.6, 0.6], [0.78, 0.3], [0.84, 0.92], [1, 0.55]],
  [[0, 0.45], [0.18, 0.12], [0.25, 0.58], [0.41, 0.3], [0.5, 0.88], [0.68, 0.42], [0.74, 0.75], [0.9, 0.2], [1, 0.5]],
  [[0, 0.5], [0.12, 0.2], [0.3, 0.72], [0.37, 0.4], [0.55, 0.95], [0.62, 0.5], [0.8, 0.82], [0.88, 0.35], [1, 0.48]],
]
export function boltShape(j) {
  const b = M.bolt[j % M.bolt.length], [x0, x1] = b.x
  const flip = j % 2, line = BOLTS[j % BOLTS.length].map(([v, u]) => [x0 + (flip ? 1 - u : u) * (x1 - x0), -40 * v])
  return { line, stroke: b.stroke, glow: b.glow, width: Math.max(Math.abs(x0), Math.abs(x1)) }
}
export const BOLT_TEXTURES = M.bolt.length

// Yoshi's Story's Shy Guys, facing +x in the game's box: a red robe leaning
// forward, the white mask with its eyes and mouth in front, blue feet, and the
// propeller's blur behind its head. `ang` turns it (a knocked-off one tumbles).
export function drawShyGuy(ctx, x, y, d, wx, wy, ang = 0) {
  const [x0, x1, y0, y1] = M.shyGuy.box, W = x1 - x0, H = y1 - y0
  const at = (u, v) => [x0 + u * W, y0 + v * H]
  // every part turns with the tumble about the item point (mirrored first)
  const part = (u, v, rx, ry, colour, alpha = 1, rot = 0) => {
    const [cx, cy] = at(u, v)
    fillPts(ctx, ellipsePts(cx, cy, rx * W, ry * H, 18, rot), x, y, ang, d, wx, wy, colour, alpha)
  }
  part(0.33, 0.62, 0.33, 0.36, '#838b29', 0.45)       // the propeller's blur
  part(0.33, 0.62, 0.05, 0.05, '#5a5f1c')
  part(0.37, 0.15, 0.09, 0.1, '#0829a4')               // feet
  part(0.5, 0.09, 0.08, 0.08, '#0829a4')
  part(0.6, 0.42, 0.3, 0.42, '#c4100c', 1, -0.35)      // the robe
  part(0.84, 0.47, 0.15, 0.21, '#ece8ec')              // the mask
  part(0.8, 0.55, 0.026, 0.05, '#000000')
  part(0.89, 0.55, 0.026, 0.05, '#000000')
  part(0.845, 0.37, 0.035, 0.025, '#000000')
}

// Randall, Yoshi's Story's cloud and our mascot, drawn as our own cloud: puffs
// with a soft blue underside, two eyes and a big smile. Puffs are [x, y, r] in
// the cloud's box (0..1 across, 0..1 down from its top; r in box widths).
const CLOUD = [[0.5, 0.42, 0.25], [0.5, 0.55, 0.22], [0.29, 0.5, 0.14], [0.71, 0.5, 0.14],
  [0.37, 0.64, 0.13], [0.63, 0.64, 0.13]]
const CLOUD_FACE = { eyes: [[0.42, 0.42], [0.58, 0.42]], eye: [0.032, 0.058], smile: [0.5, 0.47, 0.17], smileWidth: 0.035 }
// in canvas pixels: the box's top-left corner, width and height
export function drawRandallCloud(ctx, left, top, w, h) {
  const px = (u) => left + u * w, py = (v) => top + v * h
  for (const [fill, dy] of [['#a9c8ee', 0.035], ['#f4f9ff', 0]]) {
    ctx.fillStyle = fill
    for (const [u, v, r] of CLOUD) { ctx.beginPath(); ctx.arc(px(u), py(v + dy), r * w, 0, TAU); ctx.fill() }
  }
  ctx.fillStyle = '#10141c'
  for (const [u, v] of CLOUD_FACE.eyes) {
    ctx.beginPath(); ctx.ellipse(px(u), py(v), CLOUD_FACE.eye[0] * w, CLOUD_FACE.eye[1] * h, 0, 0, TAU); ctx.fill()
  }
  const [su, sv, sr] = CLOUD_FACE.smile
  ctx.strokeStyle = '#e8323c'; ctx.lineWidth = CLOUD_FACE.smileWidth * w; ctx.lineCap = 'round'
  ctx.beginPath(); ctx.arc(px(su), py(sv), sr * w, 0.18 * Math.PI, 0.82 * Math.PI); ctx.stroke()
}
// The same cloud as an SVG (the phone's chat face), cropped to the cloud.
export function randallSvg(cls = '') {
  const n = (v) => +(v * 100).toFixed(2)
  const puffs = (fill, dy) => CLOUD.map(([u, v, r]) => `<circle cx="${n(u)}" cy="${n(v + dy)}" r="${n(r)}" fill="${fill}"/>`).join('')
  const eyes = CLOUD_FACE.eyes.map(([u, v]) =>
    `<ellipse cx="${n(u)}" cy="${n(v)}" rx="${n(CLOUD_FACE.eye[0])}" ry="${n(CLOUD_FACE.eye[1])}" fill="#10141c"/>`).join('')
  const [su, sv, sr] = CLOUD_FACE.smile, a0 = 0.18 * Math.PI, a1 = 0.82 * Math.PI
  const sx = (a) => n(su + sr * Math.cos(a)), sy = (a) => n(sv + sr * Math.sin(a))
  const smile = `<path d="M${sx(a0)} ${sy(a0)}A${n(sr)} ${n(sr)} 0 0 1 ${sx(a1)} ${sy(a1)}" fill="none" stroke="#e8323c" ` +
    `stroke-width="${n(CLOUD_FACE.smileWidth)}" stroke-linecap="round"/>`
  return `<svg${cls ? ` class="${cls}"` : ''} viewBox="12 14 76 72" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">` +
    puffs('#a9c8ee', 0.035) + puffs('#f4f9ff', 0) + eyes + smile + '</svg>'
}

// Common items as simple pictures over the game's ECB box (itemLooks.js), in
// canvas pixels: centre (cx, cy), half sizes rx and ry, `fill` the item's
// colour, `d` its facing. Returns false for a shape this does not draw.
export function drawItemIcon(ctx, shape, fill, cx, cy, rx, ry, d) {
  const f = d < 0 ? -1 : 1, r = Math.min(rx, ry)
  const ell = (x, y, ex, ey, colour) => {
    ctx.fillStyle = colour; ctx.beginPath(); ctx.ellipse(x, y, Math.max(0.5, ex), Math.max(0.5, ey), 0, 0, TAU); ctx.fill()
  }
  const poly = (pts, colour) => {
    ctx.fillStyle = colour; ctx.beginPath()
    pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))
    ctx.closePath(); ctx.fill()
  }
  const box = (x0, y0, x1, y1, colour) => poly([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], colour)
  // the top half of an ellipse (y down), its flat side at cy0
  const dome = (x, cy0, ex, ey, colour) => {
    const pts = []
    for (let i = 0; i <= 16; i++) { const a = Math.PI * i / 16; pts.push([x + ex * Math.cos(a), cy0 - ey * Math.sin(a)]) }
    poly(pts, colour)
  }
  switch (shape) {
    case 'capsule': {      // a pill standing up, light top half, darker bottom half
      const w = rx, h = ry, k = Math.min(w, h)
      ell(cx, cy - h + k, w, k, fill); box(cx - w, cy - h + k, cx + w, cy, fill)
      ell(cx, cy + h - k, w, k, '#9aa3b8'); box(cx - w, cy, cx + w, cy + h - k, '#9aa3b8')
      return true
    }
    case 'bobomb': {       // a round bomb on two feet, a fuse on top, eyes forward
      const by = cy + 0.08 * ry
      ell(cx - 0.45 * r, cy + 0.85 * ry, 0.32 * r, 0.18 * r, '#f0b030')
      ell(cx + 0.45 * r, cy + 0.85 * ry, 0.32 * r, 0.18 * r, '#f0b030')
      box(cx - f * 1.05 * r, by - 0.12 * r, cx - f * 0.8 * r, by + 0.12 * r, '#c8ccd8')
      ell(cx, by, r * 0.9, r * 0.85, fill)
      box(cx - 0.1 * r, by - 1.12 * r, cx + 0.1 * r, by - 0.8 * r, '#d8c8a0')
      ell(cx, by - 1.15 * r, 0.16 * r, 0.16 * r, '#ffd34d')
      ell(cx + f * 0.3 * r, by - 0.15 * r, 0.11 * r, 0.2 * r, '#f4f4ee')
      ell(cx + f * 0.58 * r, by - 0.15 * r, 0.11 * r, 0.2 * r, '#f4f4ee')
      return true
    }
    case 'sword': {        // the beam sword: a hilt at the bottom, a glowing blade up
      const top = cy - ry, bot = cy + ry, g = bot - 0.28 * 2 * ry
      box(cx - 0.8 * rx, g, cx + 0.8 * rx, bot, '#5a6070')
      box(cx - 1.6 * rx, g - 0.06 * ry, cx + 1.6 * rx, g + 0.06 * ry, '#8a93ab')
      ctx.globalAlpha *= 0.85; box(cx - rx, top, cx + rx, g, fill); ctx.globalAlpha /= 0.85
      box(cx - 0.35 * rx, top + 0.05 * ry, cx + 0.35 * rx, g, '#f4fbff')
      return true
    }
    case 'bat': {          // a bat: thick at the top, a taped grip at the bottom
      poly([[cx - rx, cy - ry], [cx + rx, cy - ry], [cx + 0.45 * rx, cy + ry], [cx - 0.45 * rx, cy + ry]], fill)
      box(cx - 0.45 * rx, cy + 0.55 * ry, cx + 0.45 * rx, cy + ry, '#8a6a40')
      return true
    }
    case 'pokeball': {     // red top, white bottom, a black band and its button
      dome(cx, cy, r, r, '#ff4d4d')
      dome(cx, cy, r, -r, '#f4f4ee')
      box(cx - r, cy - 0.09 * r, cx + r, cy + 0.09 * r, '#1e1e1e')
      ell(cx, cy, 0.3 * r, 0.3 * r, '#1e1e1e'); ell(cx, cy, 0.18 * r, 0.18 * r, '#f4f4ee')
      return true
    }
    case 'tomato': {       // a round tomato with its green leaves on top
      ell(cx, cy + 0.08 * ry, rx, ry * 0.88, fill)
      for (const a of [-0.9, 0, 0.9]) {
        ell(cx + Math.sin(a) * 0.32 * rx, cy - 0.72 * ry + (1 - Math.cos(a)) * 0.1 * ry, 0.22 * rx, 0.12 * ry, '#3fa34d')
      }
      ell(cx - 0.35 * rx, cy - 0.15 * ry, 0.14 * rx, 0.2 * ry, '#ffb0a8')
      return true
    }
    case 'heart': {        // a heart
      ell(cx - 0.48 * rx, cy - 0.3 * ry, 0.54 * rx, 0.56 * ry, fill)
      ell(cx + 0.48 * rx, cy - 0.3 * ry, 0.54 * rx, 0.56 * ry, fill)
      poly([[cx - 1.01 * rx, cy - 0.18 * ry], [cx + 1.01 * rx, cy - 0.18 * ry], [cx, cy + ry]], fill)
      return true
    }
    case 'shell': {        // a shell lying down: its dome over a pale rim
      dome(cx, cy + 0.35 * ry, rx, 1.35 * ry, fill)
      box(cx - rx, cy + 0.35 * ry, cx + rx, cy + 0.7 * ry, '#f4f0e0')
      box(cx - 0.9 * rx, cy + 0.7 * ry, cx + 0.9 * rx, cy + ry, '#c8b890')
      ell(cx, cy - 0.35 * ry, 0.32 * rx, 0.28 * ry, '#ffffff'); ctx.globalAlpha *= 0.4
      ell(cx, cy - 0.35 * ry, 0.32 * rx, 0.28 * ry, fill); ctx.globalAlpha /= 0.4
      return true
    }
    case 'crate': {        // a wooden crate: a frame and a cross brace
      box(cx - rx, cy - ry, cx + rx, cy + ry, '#8a5f2e')
      box(cx - 0.8 * rx, cy - 0.8 * ry, cx + 0.8 * rx, cy + 0.8 * ry, fill)
      poly([[cx - 0.8 * rx, cy - 0.62 * ry], [cx - 0.62 * rx, cy - 0.8 * ry], [cx + 0.8 * rx, cy + 0.62 * ry], [cx + 0.62 * rx, cy + 0.8 * ry]], '#8a5f2e')
      return true
    }
    case 'barrel': {       // a barrel: staves bulging a little, two iron hoops
      poly([[cx - 0.85 * rx, cy - ry], [cx + 0.85 * rx, cy - ry], [cx + rx, cy], [cx + 0.85 * rx, cy + ry],
        [cx - 0.85 * rx, cy + ry], [cx - rx, cy]], fill)
      for (const v of [-0.55, 0.55]) box(cx - 0.95 * rx, cy + v * ry - 0.08 * ry, cx + 0.95 * rx, cy + v * ry + 0.08 * ry, '#4e5260')
      return true
    }
    case 'hammer': {       // a mallet: its head across the top, the handle down
      box(cx - 0.14 * rx, cy - 0.6 * ry, cx + 0.14 * rx, cy + ry, '#a0703c')
      box(cx - 0.75 * rx, cy - ry, cx + 0.75 * rx, cy - 0.55 * ry, fill)
      for (const s of [-1, 1]) ell(cx + s * 0.75 * rx, cy - 0.775 * ry, 0.16 * rx, 0.225 * ry, '#c8a05a')
      return true
    }
    case 'mushroom': {     // a spotted cap over a pale stem with two eyes
      box(cx - 0.5 * rx, cy, cx + 0.5 * rx, cy + ry, '#f2e6c8')
      dome(cx, cy + 0.1 * ry, rx, 1.1 * ry, fill)
      for (const [u, v, s] of [[-0.5, -0.35, 0.2], [0.45, -0.4, 0.17], [0, -0.75, 0.16]]) ell(cx + u * rx, cy + v * ry, s * rx, s * ry, '#f4f4ee')
      ell(cx - 0.18 * rx, cy + 0.5 * ry, 0.07 * rx, 0.15 * ry, '#1e1e1e'); ell(cx + 0.18 * rx, cy + 0.5 * ry, 0.07 * rx, 0.15 * ry, '#1e1e1e')
      return true
    }
  }
  return false
}

// Bombs that blow up: [the state they blow up in, the blast's hitbox radius
// (times the item scale), the frames that hitbox is out], from the item tables
// (data/items/<kind>.json: that state's animation, its hitbox, its last hitbox
// frame + 1). The game hides the bomb as it blows (JOBJ_HIDDEN in itlinkbomb.c
// it_8029F69C, itbombhei.c it_80280B60) but keeps the item alive about 80
// frames longer; drawn as itself, it lingered as a dot where it blew.
export const EXPLOSIONS = {
  0: [5, 9.84, 8],      // a Capsule that blows up when opened
  1: [6, 9.37, 5],      // an exploding Crate
  2: [6, 9.37, 5],      // an exploding Barrel
  4: [7, 8.44, 5],      // an exploding Party Ball
  6: [11, 6.09, 3],     // Bob-omb (Peach's pulled ones too)
  19: [6, 10.31, 18],   // Motion-Sensor Bomb
  58: [5, 4, 6],        // Link's bomb
  59: [5, 3.98, 9],     // Young Link's
  93: [3, 3.84, 18],    // Samus's
}
// Items whose model the game no longer draws in this state, from the item code
// in the decomp: Samus's missile once it has exploded (states 2 and 3,
// itsamusmissile.c) and every bomb in the state it blows up in (EXPLOSIONS:
// JOBJ_HIDDEN). Watch Lite draws our burst there for a while, then nothing.
export const modelHidden = (kind, state) => (kind === 95 && (state === 2 || state === 3)) || EXPLOSIONS[kind]?.[0] === state
// how long our burst shows: the hitbox's frames, then the smoke for twice that
// (at least 12 frames); after that nothing
export const explosionLength = (hit) => hit + Math.max(12, 2 * hit)
const SMOKE = [[0.35, 0.15], [1.6, -0.1], [2.85, 0.1], [4.1, -0.05], [5.3, 0.12]]
// Our own blast, `age` frames after the bomb blew, radius R (world units): a
// ball of fire with licks swelling to R while the hitbox is out (`hit`
// frames), then the fire dying down under puffs of smoke that rise and fade.
export function drawExplosion(ctx, age, x, y, R, hit, wx, wy) {
  const fade = explosionLength(hit) - hit
  if (age < 0 || age >= hit + fade) return
  const S = Math.abs(wx(1) - wx(0))
  const disc = (cx, cy, r, colour, alpha) => {
    ctx.globalAlpha = alpha; ctx.fillStyle = colour
    ctx.beginPath(); ctx.arc(wx(cx), wy(cy), Math.max(1, r * S), 0, TAU); ctx.fill()
  }
  if (age < hit) {
    const r = R * (0.65 + 0.35 * (age + 1) / hit), turn = age * 0.35
    const star = []
    for (let i = 0; i < 12; i++) {
      const a = turn + i / 12 * TAU, f = i % 2 ? 0.72 : 1
      star.push([r * f * Math.cos(a), r * f * Math.sin(a)])
    }
    fillPts(ctx, star, x, y, 0, 1, wx, wy, '#ff8a2a', 0.85)
    disc(x, y, r * 0.62, '#ffd36a', 1)
    disc(x, y, r * 0.3, '#fffbe6', 1)
  } else {
    const u = (age - hit) / fade
    if (u < 0.4) disc(x, y + R * 0.2 * u, R * 0.6 * (1 - u / 0.4), '#ff9a3d', 0.75 * (1 - u / 0.4))
    for (const [a, wob] of SMOKE) {
      const d = R * (0.35 + 0.45 * u)
      disc(x + Math.cos(a) * d, y + Math.sin(a) * d * 0.7 + R * (0.6 * u + wob), R * (0.42 - 0.14 * u), '#8a8f9c', 0.55 * (1 - u))
    }
  }
  ctx.globalAlpha = 1
}

// The revival platform's deck under a respawning fighter's feet (scale 1): a
// flat top and a saucer's underside, at the game's width and depth.
let deckPts = null
export function rebirthDeck() {
  if (!deckPts) {
    const { w, top, bottom } = M.rebirth, n = 16
    deckPts = [[-w, top], [w, top]]
    for (let i = 1; i < n; i++) {
      const x = w - 2 * w * i / n
      deckPts.push([x, top - (top - bottom) * (1 - (x / w) ** 4)])
    }
  }
  return deckPts
}
export const rebirthScale = (cid) => M.rebirth.scale[cid] || 1

// Bowser's Whirling Fortress shell in the game's box for this action frame
// ([x0, x1, y0, y1], fighter-local, x along facing): a dome over a low rim,
// its spikes turning with the spin (`k`, frames into the move).
export function koopaShellPts(box, k) {
  const [x0, x1, y0, y1] = box, cx = (x0 + x1) / 2, rx = (x1 - x0) / 2, H = y1 - y0
  const base = y0 + 0.18 * H, ry = (y1 - base) / 1.25, step = Math.PI / 4
  const phase = ((k * 0.5) % step + step) % step
  const spikes = []
  for (let s = phase; s < Math.PI; s += step) if (s > 0.35 && s < Math.PI - 0.35) spikes.push(s)
  const pts = [[x1, base]]
  for (let i = 1; i < 48; i++) {
    const t = Math.PI * i / 48
    let f = 1
    for (const s of spikes) f = Math.max(f, 1 + 0.25 * Math.max(0, 1 - Math.abs(t - s) / 0.14))
    pts.push([cx + rx * f * Math.cos(t), base + ry * f * Math.sin(t)])
  }
  pts.push([x0, base], [x0 + 0.12 * (x1 - x0), y0], [x1 - 0.12 * (x1 - x0), y0])
  return pts
}
export const koopaShellFrames = (state) => M.koopaShell[String(state)]
