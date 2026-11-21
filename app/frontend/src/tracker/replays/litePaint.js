// Watch Lite's pure painting layer, extracted from WatchLiteClip.jsx so the
// Combo Video preview/exporter can render clips without the component. Every
// function here takes an explicit target context — no React, no module state
// beyond the shared charmap cache.
import { api } from '../../shared/transport/api'
import { randallPlatform, collisionGeometry } from './meleeStages'
import { stageGeometryAt, groundWitness, fodPlatformY, windTable, WIND_LX0, WIND_LX1, WIND_RX0, WIND_RX1, buriedPlatform, interiorLine, cachedFills } from './liteStageInference'
import { heldFrames, reflectorAt } from './meleeRender'
import ITEM_SIZES from './data/itemSizes.json'
import { hitDataFor } from './stageData.js'
import { METRICS, shapePath, drawCar, drawIce, drawMissile, drawTurnip, fireballPts, drawFlameCharge, plumePts, flameHips,
  pkTrailLine, pkTrailColour, boltShape, BOLT_TEXTURES, drawShyGuy, drawRandallCloud, rebirthDeck, rebirthScale, drawItemIcon,
  EXPLOSIONS, drawExplosion, drawThrownEgg, drawEggBreak, EGG_THROW, drawBoomerang, BOOMERANG_SPIN,
  drawRoundBomb, drawFireLick, drawPkFireBolt } from './itemArt.js'
import { itemLook, HIDDEN } from './itemLooks'
import { drawHitSparks, hitShake, shieldStun, drawShieldScribble } from './hitSparks'
import { drawTechEffects, drawTechRings } from './techEffects'
import { drawSwordTrails } from './swordTrails'
import { flashFill } from './hitFlash'
import { drawImpactEffects } from './impactEffects'
import { invincibleOutline } from './invincible'
import { drawKoBlasts } from './koBlast'
import { drawKoFlights } from './koFlight'
import { drawDust } from './movementDust'

// Re-exported so the inference rules stay reachable from here (see liteStageInference).
export { fodPlatformY, windTable }

// per-port colours (1v1 + FFA up to 4) and Melee team colours (red/blue/green)
export const P = ['#ff7a66', '#5aa0ff', '#5ad07a', '#f5c451']
export const TEAM_COLORS = ['#ff5a5a', '#5a8cff', '#5ad07a']
export function pcolor(bundle, i) {
  const pl = bundle.meta.players[i]
  if (bundle.meta.teams && pl && pl.team != null && TEAM_COLORS[pl.team]) return TEAM_COLORS[pl.team]
  return P[i % P.length]
}

// A failed request is forgotten so the next clip asks again. (Kept apart from
// the clip loader's cache so the offline paint tools never load the network
// loader.)
let charmapsPromise = null
export function getCharmaps() {
  if (!charmapsPromise) {
    charmapsPromise = api.get('/api/nucleome/lite/charmaps').catch(error => {
      charmapsPromise = null
      throw error
    })
  }
  return charmapsPromise
}

// Melee-style smoothed follow camera (ported from slippilab Camera.tsx).
// Framing: a box shorter than MIN grows mostly UPWARD (2/3 of the slack), so
// fighters on the floor sit low in the frame with the platforms above them in
// view, as in Melee. The old 100-unit box centred on the fighters showed only
// ~50 units above the floor: Dream Land's and Battlefield's top platforms
// (51.4 / 54.4) were never on screen during a grounded neutral.
export function stepCamera(cam, f, idx, snap) {
  const PAD = 25, MIN = 120, UP = 2 / 3, MIN_SC = 1.8, MAX_SC = 6
  // Frame the LIVING fighters. A dead/respawning player teleports to the top of
  // the stage and would otherwise blow the camera out to nothing. Sleep (11)
  // is off screen too: paintFrame doesn't draw it, so neither is it framed.
  const NP = f.x.length
  const pts = []
  for (let i = 0; i < NP; i++) {
    const dead = (f.cat && f.cat[i][idx] === 6) || f.state[i][idx] <= DEAD_MAX
    if (!dead) pts.push([f.x[i][idx], f.y[i][idx]])
  }
  // ICs Nana (render-only follower rows) — frame her too; null = dead/absent
  for (const fo of (f.fol || [])) {
    const st = fo.state[idx]
    if (st != null && st > 10 && fo.x[idx] != null) pts.push([fo.x[idx], fo.y[idx]])
  }
  if (!pts.length) for (let i = 0; i < NP; i++) pts.push([f.x[i][idx], f.y[i][idx]])
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1])
  const xMin = Math.min(...xs) - PAD, xMax = Math.max(...xs) + PAD
  let yMin = Math.min(...ys) - PAD, yMax = Math.max(...ys) + PAD
  const slack = MIN - (yMax - yMin)
  if (slack > 0) { yMax += slack * UP; yMin -= slack * (1 - UP) }
  const cxT = (xMin + xMax) / 2, cyT = (yMin + yMax) / 2
  let scT = Math.min(640 / Math.max(xMax - xMin, MIN), 480 / Math.max(yMax - yMin, MIN))
  scT = Math.max(MIN_SC, Math.min(MAX_SC, scT))   // keep fighters a visible size
  const k = snap ? 1 : 0.08
  cam.cx = cam.cx == null ? cxT : cam.cx + (cxT - cam.cx) * k
  cam.cy = cam.cy == null ? cyT : cam.cy + (cyT - cam.cy) * k
  cam.sc = cam.sc == null ? scT : cam.sc + (scT - cam.sc) * k
}
export function viewFromCam(cam, w, h) {
  const disp = Math.min(w / 640, h / 480)
  const S = cam.sc * disp
  return { S, ox: w / 2 - cam.cx * S, oy: h / 2 + cam.cy * S }
}

// The blow itself: a few thin streaks drifting across the half of the stage the
// push actually reaches, so the drawing says WHERE as well as which way. Phase
// comes from idx alone — seeking to a frame must paint the same picture as
// playing into it, like every other overlay here.
const WIND_STREAKS = 6
const WIND_DRAW_SPEED = 2.2      // world units/frame — readable, not literal
const WIND_BAND = [4, 36]        // inside the real box (y -10..40), above the floor
function drawWind(ctx, bundle, idx, view, dpr) {
  const tab = windTable(bundle)
  const dir = tab && tab[idx]
  if (!dir) return
  const wx = (x) => view.ox + x * view.S
  const wy = (y) => view.oy - y * view.S
  const x0 = dir > 0 ? WIND_RX0 : WIND_LX1     // the seam, where the tree stands
  const x1 = dir > 0 ? WIND_RX1 : WIND_LX0     // outer edge of that box
  const span = x1 - x0                         // signed: streaks travel with it
  const s = Math.sign(span), width = Math.abs(span)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.strokeStyle = '#7d8bb0'
  ctx.lineCap = 'round'
  ctx.lineWidth = 1.4
  for (let k = 0; k < WIND_STREAKS; k++) {
    // golden-ratio offsets spread the heights and phases so the streaks never
    // collapse into one marching row
    const g = (k * 0.6180339887) % 1
    const h = WIND_BAND[0] + g * (WIND_BAND[1] - WIND_BAND[0])
    const p = ((idx * WIND_DRAW_SPEED / width) + g) % 1
    const len = 12 + 8 * ((k * 0.3819660113) % 1)
    // travel the box MINUS the streak's own length, so no tail hangs out over
    // the blast zone claiming the wind reaches somewhere it doesn't
    const cx = x0 + p * (span - len * s)
    ctx.globalAlpha = 0.3 * Math.sin(Math.PI * p)   // no pop at either box edge
    ctx.beginPath()
    ctx.moveTo(wx(cx), wy(h))
    ctx.lineTo(wx(cx + len * s), wy(h))
    ctx.stroke()
  }
  ctx.globalAlpha = 1
}

// Item/projectile pass. Kinds are the melee decomp's ItemKind (confirmed
// against real replays by the deriver). Fighter projectiles are drawn by the
// bake's item family, sized from the game itself: data/itemSizes.json holds
// each kind's hitbox radius x item scale (per item state where a charge
// changes it) and its body radius, derived from the item tables by
// tools/liteaudit/item_sizes.mjs and small enough to load with the paint. Only
// the colours are a table here. Props a fighter holds (blasters, bows, capes,
// bats, Game & Watch's tools) are part of its own pose and are not drawn on
// their own. Common items, Pokemon and each stage's own objects take their
// shape and size from the hand-checked table in itemLooks.js; the stage's
// hit volumes (kind 160) are drawn only where they carry a hazard the game
// shows and the stage geometry does not (cars, Klaptrap, Banzai Bill).
// Only kinds that table does not know (custom m-ex content) stay a small dot
// in the owner's colour (grey without one): "something is there".
const IT_FOX_LASER = 54, IT_FALCO_LASER = 55
const IT_SAMUS_BOMB = 93, IT_CHARGESHOT = 94, IT_MISSILE = 95
const IT_TURNIP = 99
// Yoshi's thrown egg; its break: [state, blast radius (9.765 x scale 1.3), hitbox
// frames] (data/items/86.json)
const IT_EGG_THROW = 86, EGG_BREAK = [2, 12.69, 4]
const FIRE_LICKS = new Set([100, 154, 108])   // Bowser's fire breath, Kirby's copy, Din's Fire in flight
const IT_ARWING_LASER = 234, IT_GREATFOX_LASER = 235   // stage projectiles (Corneria, Venom)
// [fill, core] by kind: Mario's (and Kirby's copy) orange fireball, Luigi's
// green one; Dr. Mario's vitamin is a two-tone capsule.
const FIREBALL = { 48: ['#ff7a2f', '#ffd36a'], 130: ['#ff7a2f', '#ffd36a'], 105: ['#3fc457', '#c6ffb4'], 132: ['#3fc457', '#c6ffb4'] }
const VITAMIN = new Set([49, 131])
// fill colour, and whether it is a burst (drawn see-through), by family
const FAMILY = {
  bomb: ['#3d4f86'], boomerang: ['#d8b06a'], chef: ['#e08a4f'], charge: ['#78c8ff'],
  pkfire: ['#ff6a3d'], pkpillar: ['#ff8a3d', true], pkthunder: ['#a9dcff'], pktrail: ['#a9dcff', true],
  pkflash: ['#8bff9f'], pkexplode: ['#8bff9f', true], dinfire: ['#ff9a3d'], dinexplode: ['#ff9a3d', true],
  thunder: ['#ffe24d', true], jolt: ['#ffe24d'], joltair: ['#ffe24d'], shadow: ['#9b6bff'],
}
// The bake files these projectiles under "authored": colour and burst by kind.
const AUTHORED = {
  50: ['#9fe3ff'], 136: ['#9fe3ff'], 85: ['#c9c9d6', true], 86: ['#f4f4ee'], 88: ['#ffe24d'],
  98: ['#ff9a3d', true], 100: ['#ff7a2f'], 154: ['#ff7a2f'], 106: ['#bfeaff'], 133: ['#bfeaff'],
  107: ['#e6f6ff', true], 111: ['#ffc6e2'], 135: ['#ffc6e2'], 110: ['#9b6bff', true],
}
const ARROWS = { 64: '#e8d8a8', 140: '#e8d8a8', 65: '#ff8a3d', 141: '#ff8a3d' }
// Fox's and Falco's blaster shot (Kirby's copies too), from the item's own
// model and code (PlFx.dat / PlFc.dat item 0, itfoxlaser.c): a beam whose head
// is the item position and whose body trails back along the travel line. The
// model is four nested shells along -z, drawn here as tapered glows from their
// sizes (data/itemMetrics.js `blaster`: radius, tip ahead, where full radius
// starts and ends, tail behind, colour, alpha): red glows of radius 5.18 /
// 1.46 / 0.58 and a white core of 0.25.
// The material is vertex colour only, so the alphas are the vertices' own
// (20, 85, 190 and 255 of 255): the 5.18 shell barely tints the backdrop and
// the 1.46 one is the visible halo. The game scales the beam along z by s,
// which grows by speed / 11.25 a frame up to the attribute 3 (FoxLaserAttr
// +4), so it emerges from the gun; a reflect or shield bounce resets s to 0
// and it grows again. Read in RAM (playback Dolphin): s = min(3, (frames
// since it appeared or turned + 1) * speed / 11.25), and 0.001 on the frame
// it is reflected.
const BLASTER = new Set([IT_FOX_LASER, IT_FALCO_LASER, 136, 137])
function turned(it, a, b) {
  const ax = it.vx[a], ay = it.vy[a], bx = it.vx[b], by = it.vy[b]
  const m = Math.hypot(ax, ay) * Math.hypot(bx, by)
  return m > 1e-6 && (ax * bx + ay * by) / m < 0.7
}
export function blasterScale(it, k) {
  if (!it.vx || !it.vy) return 3
  const speed = Math.hypot(it.vx[k], it.vy[k])
  if (k + 1 < it.vx.length && turned(it, k, k + 1)) return 0   // reflected on this frame
  let j = k
  while (j > 0 && !turned(it, j - 1, j)) j--
  return Math.min(3, (k - j + 1) * speed / 11.25)
}
function drawBlasterShot(ctx, it, k, x, y, ux, uy, wx, wy, S) {
  const s = blasterScale(it, k)
  if (s < 0.01) return
  const nx = -uy, ny = ux
  const at = (z, r) => [wx(x + z * s * ux + r * nx), wy(y + z * s * uy + r * ny)]
  for (const [R, tip, front, back, tail, colour, alpha] of METRICS.blaster) {
    ctx.globalAlpha = alpha
    if (R < 0.3) {
      // the white core: a line from the head back to its tail, at least 1.2 px wide
      ctx.lineCap = 'round'; ctx.strokeStyle = colour; ctx.lineWidth = Math.max(1.2, 2 * R * S)
      ctx.beginPath(); ctx.moveTo(...at(tip, 0)); ctx.lineTo(...at(tail, 0)); ctx.stroke()
      continue
    }
    // a glow: full radius between `front` and `back`, tapering to its tips
    ctx.fillStyle = colour
    ctx.beginPath()
    ;[[tip, 0], [front, R], [back, R], [tail, 0], [back, -R], [front, -R]].forEach(([z, r], i) => {
      const [px, py] = at(z, r)
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)
    })
    ctx.closePath(); ctx.fill()
  }
  ctx.globalAlpha = 1
}
// frames since the item's state (or, with `set`, its run of states) began
function framesIn(it, k, set) {
  const s0 = it.s?.[k]
  let j = k
  while (j > 0 && (set ? set.has(it.s?.[j - 1]) : it.s?.[j - 1] === s0)) j--
  return k - j
}
// Onett's cars (GrOt.dat, item kind 160): lane A (item states 2-5 = car 0-3)
// drives right to left on the road in front of the stage; lane B (state 0, no
// hitbox, turned around) drives left to right further out. Idle cars wait
// off-screen at |x| >= 577.8. Drawn at their true size on the stage plane: the
// game's camera shows them bigger and lower because they are nearer to it. Each
// is our own car drawing at that car's size and colour (itemArt.drawCar).
function drawOnettCar(ctx, bundle, it, k, x, y, wx, wy) {
  const st = it.s?.[k]
  let car = METRICS.car[st], mirror = 1
  if (!car) {
    const moving = k > 0 ? Math.abs(it.x[k] - it.x[k - 1]) > 0.05 : Math.abs(it.vx?.[k] || 0) > 0.05
    if (st !== 0 || Math.abs(x) >= 577.8 || !moving) return
    const order = (bundle.items || []).filter(o => o.t === 160).indexOf(it)
    car = METRICS.car[2 + ((order % 4) + 4) % 4]; mirror = -1
  }
  drawCar(ctx, car, x, y, mirror, wx, wy)
}
// both lanes drive between the stage and the camera, so they cover the fighters
function drawOnettCars(ctx, bundle, idx, view, dpr) {
  const wx = (v) => view.ox + v * view.S, wy = (v) => view.oy - v * view.S
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  for (const it of bundle.items || []) {
    const k = idx - it.f
    if (it.t !== 160 || k < 0 || k >= it.x.length) continue
    drawOnettCar(ctx, bundle, it, k, it.x[k], it.y[k], wx, wy)
  }
}
const IT_ICE = new Set([106, 133])            // Popo's / Nana's ice, Kirby's copy
const IT_FIREBALL_SHAPE = { 48: '48', 130: '48', 105: '105', 132: '105' }
// Peach's turnip held in her hand: it rides her hold bone, read per action
// frame of the states the round-7 table covers; held through any other state,
// the last pose of her idle stands in.
function drawHeldTurnip(ctx, bundle, it, k, idx, wx, wy) {
  const f = bundle.frames, o = it.o
  // no holder rows: the item's own position, upright
  if (o == null || o < 0 || !f.x[o]) { drawTurnip(ctx, it.x[k], it.y[k], 0, 1, wx, wy); return true }
  void it.x[k]   // read the turnip's own record first: the draw belongs to it
  const st = f.state[o][idx], age = Math.max(0, Math.floor(f.age?.[o]?.[idx] || 0))
  const table = METRICS.turnip.held[st] || METRICS.turnip.held[14]
  const row = table[Math.min(age, table.length - 1)]
  const dir = f.dir?.[o]?.[idx] || 1
  const ox = f.x[o][idx] + row[0] * dir, oy = f.y[o][idx] + row[1]
  const ang = row[2] * Math.PI / 180 * dir
  if ((st === 352 || st === 353) && age < 14) {
    // still coming out of the ground: only what is above Peach's feet shows
    const groundY = wy(f.y[o][idx])
    ctx.save(); ctx.beginPath(); ctx.rect(-1e5, -1e5, 2e5, groundY + 1e5); ctx.clip()
    drawTurnip(ctx, ox, oy, ang, dir, wx, wy)
    ctx.restore()
    return true
  }
  drawTurnip(ctx, ox, oy, ang, dir, wx, wy)
  return true
}
// A polyline in item-local units: x along (ux, uy) scaled by `sx`, y across
// it scaled by `sy`, around (ox, oy).
function polyline(ctx, pts, ox, oy, ux, uy, sx, sy, wx, wy) {
  ctx.beginPath()
  pts.forEach(([px, py], i) => {
    const a = px * sx, b = py * sy
    const X = ox + a * ux - b * uy, Y = oy + a * uy + b * ux
    i ? ctx.lineTo(wx(X), wy(Y)) : ctx.moveTo(wx(X), wy(Y))
  })
}
// Frames since the item appeared (`born` when that was before the window).
const itemAge = (it, k) => k + it.f - (it.born ?? it.f)
// Ness's PK Thunder (itnesspkthunderball.c / itnesspkthundertrail.c): the head
// (kind 69) is a glowing ball; its tail is six items (kinds 70-73, every 2
// frames behind the head), each a 4-unit zigzag from its own position back to
// where it was 2 frames ago (the next piece), drawn as our own zigzag as high
// as that frame's texture (itemArt.pkTrailLine). Each piece hides its mesh on
// its odd frames, and all spawn on even ones, so the whole tail blinks at 30 Hz.
const PK_HEAD = 69, PK_TRAIL = new Set([70, 71, 72, 73])
function drawPkHead(ctx, x, y, wx, wy) {
  const S = wx(1) - wx(0)
  for (const [r, colour, alpha] of [[5.5, '#5a7ce6', 0.5], [3, '#6b5acb', 1], [1.5, '#bfb9e5', 1]]) {
    ctx.globalAlpha = alpha; ctx.fillStyle = colour
    ctx.beginPath(); ctx.arc(wx(x), wy(y), Math.max(1.5, r * S), 0, 7); ctx.fill()
  }
  ctx.globalAlpha = 1
}
function drawPkTrail(ctx, it, k, x, y, d, wx, wy) {
  const age = itemAge(it, k)
  if (age % 2) return
  let bx = x - 4 * d, by = y
  if (k >= 2) { bx = it.x[k - 2]; by = it.y[k - 2] }
  const len = Math.hypot(x - bx, y - by)
  if (len < 0.05) return
  ctx.strokeStyle = pkTrailColour(it.t); ctx.lineWidth = 1.2; ctx.lineJoin = 'round'
  polyline(ctx, pkTrailLine(it.t, age % 4), x, y, (x - bx) / len, (y - by) / len, len / 4, 1, wx, wy)
  ctx.stroke()
}
// Pikachu's (and Pichu's) Thunder (itpikachuthunder.c): four bolts fall from
// the cloud in a chain. A camera-facing quad 40 long hanging under the item
// point: hidden while it waits at the cloud (state 0), whole while it falls
// (1), then its top keeps falling onto the stopped bottom (2: 5 units a frame
// of lifetime left) while the quad's height scales with it, so the whole
// texture is squeezed into what is left. Four zigzag textures, one a frame,
// over a faint glow: drawn as our own zigzag across each texture's width
// (itemArt.boltShape). Squeezed past half its height the zigzag's strokes merge
// into a flat bright flash where the bolt meets the ground. Drawn in front of
// the fighters, like a held item.
const BOLT = new Set([81, 82])
function drawBolt(ctx, it, k, st, wx, wy, S) {
  if (st !== 1 && st !== 2) return
  const x = it.x[k], y = it.y[k]
  const left = it.lifetime ? it.lifetime[k] : 8 - framesIn(it, k)
  const L = st === 1 ? 40 : Math.max(0, Math.min(40, 5 * left))
  if (L < 0.1) return
  const b = boltShape(itemAge(it, k) % BOLT_TEXTURES)
  if (L < 20) {
    // the flash: a white core in a softer white halo, as wide as the zigzag
    const w = b.width
    ctx.fillStyle = '#ffffff'
    for (const [f, a] of [[1, 0.3], [0.5, 1]]) {
      ctx.globalAlpha = a
      ctx.beginPath(); ctx.ellipse(wx(x), wy(y - L / 2), Math.max(1.5, f * w * S), Math.max(1, f * L / 2 * S), 0, 0, 7); ctx.fill()
    }
    ctx.globalAlpha = 1
    return
  }
  const gx = (b.glow[0] + b.glow[1]) / 2, gr = (b.glow[1] - b.glow[0]) / 2
  ctx.globalAlpha = 0.25; ctx.fillStyle = '#fff3a0'
  ctx.beginPath(); ctx.ellipse(wx(x + gx), wy(y - L / 2), Math.max(1, gr * S), Math.max(1, L / 2 * S), 0, 0, 7); ctx.fill()
  ctx.globalAlpha = 1
  ctx.strokeStyle = '#ffffff'; ctx.lineWidth = Math.max(1, b.stroke * S); ctx.lineJoin = 'round'
  // the zigzag runs 0..-40 down from the item point: squeeze it to L
  polyline(ctx, b.line, x, y, 1, 0, 1, L / 40, wx, wy)
  ctx.stroke()
}
// Sheik's needle (PlSk.dat article 0): one spindle 3 long whose centre sits 1.5
// behind the item point (along its facing) and turns with the travel; only
// its middle 2.1 is wide enough to show. Stuck, it keeps its last angle.
const NEEDLES = new Set([79, 152])
function drawNeedle(ctx, it, k, x, y, d, wx, wy) {
  let ux = d, uy = 0
  for (let j = k; j >= 0 && it.vx && it.vy; j--) {
    const m = Math.hypot(it.vx[j], it.vy[j])
    if (m > 1e-3) { ux = it.vx[j] / m; uy = it.vy[j] / m; break }
  }
  const cx = x - 1.5 * d, cy = y
  ctx.strokeStyle = '#d7dcea'; ctx.lineWidth = 1.2; ctx.lineCap = 'round'
  ctx.beginPath(); ctx.moveTo(wx(cx - 1.05 * ux), wy(cy - 1.05 * uy)); ctx.lineTo(wx(cx + 1.05 * ux), wy(cy + 1.05 * uy)); ctx.stroke()
}
// Samus's charge shot (itsamuschargeshot.c, PlSs.dat article 1): charge level
// L = state - 1 in flight (0-7), the `charge` byte while it charges on the arm
// cannon; the ball scales by 0.5 + 1.5 L / 7: a white core of 2.52, a magenta
// ring to 3.6 and a blue rim to 5.04 (mean of its pulse), times that scale.
const CHARGE_SHOTS = new Set([IT_CHARGESHOT, 151])
function drawChargeShot(ctx, it, k, st, x, y, wx, wy) {
  const L = st >= 1 && st <= 8 ? st - 1 : (it.charge ? it.charge[k] : 0)
  const s = 0.5 + 1.5 * Math.max(0, Math.min(7, L)) / 7, S = wx(1) - wx(0)
  for (const [r, colour, alpha] of [[5.04, '#4f7dff', 0.5], [3.6, '#d25cff', 0.85], [2.52, '#ffffff', 1]]) {
    ctx.globalAlpha = alpha; ctx.fillStyle = colour
    ctx.beginPath(); ctx.arc(wx(x), wy(y), Math.max(1.5, r * s * S), 0, 7); ctx.fill()
  }
  ctx.globalAlpha = 1
}
// Yoshi's Story's Shy Guys (GrSt.dat item 210): in the game a flat sprite
// 11.4 x 11.0 at the item position, facing +x; here our own Shy Guy in that box
// (itemArt.drawShyGuy). Knocked off (state 2, itheiho.c)
// it tumbles: the game adds a random 1, 9 or 17 degrees a frame (HSD_Randi(3),
// it_80274A64) to its turn, seen mirrored when it faces left; drawn at the
// mean 9 degrees a frame from the hit.
const SHY_SPIN = 9 * Math.PI / 180
function shyGuySpin(it, k) {
  if (it.s?.[k] !== 2) return 0
  let j = k
  while (j > 0 && it.s[j - 1] === 2) j--
  return (it.d?.[k] ?? 1) * SHY_SPIN * (k - j)
}
// The revival platform (PlCo.dat common data [8], ftCo_800D4FF4): from the
// first frame of Rebirth (12) to the end of RebirthWait (13), under the
// fighter's feet, as our own deck at the game's size (itemArt.rebirthDeck); the
// Ice Climbers' is 1.6 times as wide and centred 5 behind Popo.
const REBIRTH_BACK = { 10: 5 }
function drawRebirthPlatform(ctx, cid, x, y, dir, view) {
  const wx = (v) => view.ox + v * view.S, wy = (v) => view.oy - v * view.S
  const sc = rebirthScale(cid), ox = x - dir * (REBIRTH_BACK[cid] || 0) * sc
  ctx.beginPath()
  rebirthDeck().forEach(([px, py], i) => { i ? ctx.lineTo(wx(ox + px * sc), wy(y + py * sc)) : ctx.moveTo(wx(ox + px * sc), wy(y + py * sc)) })
  ctx.closePath()
  ctx.fillStyle = '#1c1c31'; ctx.fill()
  ctx.lineWidth = 1.5; ctx.strokeStyle = '#1476b1'; ctx.stroke()
}
// Fire Fox / Fire Bird (EfFxData.dat models 3 and 4, efSync 1163 / 1164), drawn
// as our own flames at the models' sizes frame by frame (itemArt).
// Charging (SpecialHiHold 353/354): a flame crown, an inner column and a flat
// ring on the floor, at the fighter's position, never mirrored, on a 19-frame
// loop by action frame. Travelling (SpecialHi 355/356): the plume (model 4,
// joints 3/4, as the camera sees it: across the travel line and along it),
// its animation looping every 20 frames from action frame + 1, unscaled
// (efLib_Create_Attach), on the hips: the body pivot `pivot` above the
// position, the hips `up[frame]` along the body, which the game turns to the
// travel line (ftFox_SpecialHi_RotateModel). The game depth-tests the flame,
// so none of it shows inside the stage body. It is additive light around the
// fighter, who stays plainly visible inside it: drawn before the fighters
// (`travel`), the charge with the other effects after them.
const FIRE_FIGHTERS = new Set([1, 22])
function drawFireFox(ctx, cid, state, age, idx, xs, ys, dir, view, dpr, fills, travel) {
  if (!FIRE_FIGHTERS.has(cid)) return
  if (travel !== (state === 355 || state === 356)) return
  const wx = (v) => view.ox + v * view.S, wy = (v) => view.oy - v * view.S
  const x = xs[idx], y = ys[idx], a = Math.max(0, Math.floor(age || 0))
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  if (state === 353 || state === 354) {
    drawFlameCharge(ctx, a, x, y, wx, wy, view.S)
  } else if (state === 355 || state === 356) {
    const fr = plumePts(a + 1)
    // travel direction from the recorded motion: the last frame that moved
    // (hitlag freezes it), else the next one, else straight up
    let vx = 0, vy = 0
    for (let j = idx; j > 0 && idx - j < 10 && Math.hypot(vx, vy) < 1e-3; j--) { vx = xs[j] - xs[j - 1]; vy = ys[j] - ys[j - 1] }
    for (let j = idx; j + 1 < xs.length && j - idx < 10 && Math.hypot(vx, vy) < 1e-3; j++) { vx = xs[j + 1] - xs[j]; vy = ys[j + 1] - ys[j] }
    if (Math.hypot(vx, vy) < 1e-3) { vx = 0; vy = 1 }
    const hip = flameHips(cid), up = hip.up[Math.min(a, hip.up.length - 1)]
    const th = Math.atan2(vy, vx * dir)
    const hx = x - dir * up * Math.sin(th), hy = y + hip.pivot + up * Math.cos(th)
    const ang = Math.atan2(vy, vx) - Math.PI / 2
    ctx.save()
    if (fills && fills.length) {
      // everything but the stage body: a huge rectangle wound against the fills
      ctx.beginPath(); ctx.moveTo(-1e5, -1e5); ctx.lineTo(1e5, -1e5); ctx.lineTo(1e5, 1e5); ctx.lineTo(-1e5, 1e5); ctx.closePath()
      for (const poly of fills) poly.forEach(([px, py], i) => { i ? ctx.lineTo(wx(px), wy(py)) : ctx.moveTo(wx(px), wy(py)) })
      ctx.clip()
    }
    ctx.globalAlpha = 0.5; shapePath(ctx, fr.outer, hx, hy, ang, dir, wx, wy); ctx.fillStyle = '#ff7a24'; ctx.fill()
    ctx.globalAlpha = 0.9; shapePath(ctx, fr.core, hx, hy, ang, dir, wx, wy); ctx.fillStyle = '#ffd36a'; ctx.fill()
    ctx.restore()
    ctx.globalAlpha = 1
  }
}
// Held items. While a fighter holds an item the game attaches it to the
// fighter's item-hold part (Item_8026AB54) and leaves the item's own position
// alone, so the replay records where it was pulled or picked up for as long as
// it is held: drawn there, a bomb floated and then jumped to the hand on the
// throw. A held item is drawn at that hand instead, posed from the game's
// animations (data/hits `hold`, tools/liteaudit/held_items/build.py), in front
// of its holder. The state an item is held in comes from its code (the decomp):
// the ones a fighter pulls or makes in hand start held, in state 0 (Link's and
// Young Link's bombs and boomerangs, Yoshi's egg); a pulled Bob-omb is held in
// 7; the common items enter 2 when picked up (their PickedUp callbacks).
// Peach's turnip has its own table (drawHeldTurnip).
const HELD_IN = { 58: 0, 59: 0, 60: 0, 61: 0, 86: 0, 6: 7 }
const HELD_COMMON = new Set([0, 1, 2, 3, 5, 8, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 28, 29, 30, 31, 32, 33, 41, 42, 44])
const heldState = (kind, state) => (HELD_IN[kind] !== undefined ? state === HELD_IN[kind] : HELD_COMMON.has(kind) && state === 2)
// Where an item is held this frame: its holder's hand in world units, or null
// (not held, no holder row, or the holder's table is not loaded yet).
export function heldAt(bundle, it, k, idx) {
  if (!heldState(it.t, it.s?.[k])) return null
  const f = bundle.frames, o = it.o
  if (o == null || o < 0 || !f.x[o] || f.x[o][idx] == null) return null
  const H = hitDataFor(f.cid[o][idx])?.hold
  if (!H) return null
  let rows = H.states[f.state[o][idx]]
  if (typeof rows === 'number') rows = H.states[rows]
  let lx = H.rest[0], ly = H.rest[1]
  if (rows) {
    // samples every `step` action frames, looping with the animation
    const n = rows.length / 2, t = (Math.max(0, f.age?.[o]?.[idx] || 0) / H.step) % n
    const i = Math.floor(t), j = (i + 1) % n, u = t - i
    lx = rows[2 * i] + (rows[2 * j] - rows[2 * i]) * u
    ly = rows[2 * i + 1] + (rows[2 * j + 1] - rows[2 * i + 1]) * u
  }
  return [f.x[o][idx] + (f.dir?.[o]?.[idx] || 1) * lx, f.y[o][idx] + ly]
}
// The item pass: what is on its own (inHand false, before the fighters), or
// only what a fighter holds (inHand true, after them).
function drawItems(ctx, bundle, idx, view, dpr, front = null, inHand = false) {
  const items = bundle.items
  if (!items || !items.length) return
  const wx = (x) => view.ox + x * view.S
  const wy = (y) => view.oy - y * view.S
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.lineCap = 'round'
  const ball = (x, y, r, fill, alpha = 1) => {
    ctx.globalAlpha = alpha; ctx.fillStyle = fill
    ctx.beginPath(); ctx.arc(wx(x), wy(y), Math.max(1.5, r * view.S), 0, 7); ctx.fill()
    ctx.globalAlpha = 1
  }
  for (const it of items) {
    const k = idx - it.f
    if (k < 0 || k >= it.x.length) continue
    const hand = heldAt(bundle, it, k, idx)
    if (!!hand !== inHand) continue
    const rx = it.x[k], ry = it.y[k]
    const x = hand ? hand[0] : rx, y = hand ? hand[1] : ry
    const d = it.d && it.d[k] ? it.d[k] : 1
    const t = it.t
    const look = ITEM_SIZES[t]   // [family, hit radius, body radius, held, by state]
    if (look && look[3]) continue
    if (t === 160 && bundle.meta?.stage === 9) continue   // drawn in front of the fighters (drawOnettCars)
    const table = itemLook(t, bundle.meta?.stage, it.s?.[k])
    if (table === HIDDEN) continue
    const rad = look ? ((look[4] && look[4][it.s?.[k]]) || look[1] || look[2] || 1) : 1
    // Unit vector of travel. Lasers and needles fly at real angles (aerial
    // lasers dive, reflected ones climb), so they are drawn along their
    // velocity. Bundles derived from the .slp in JS carry vx/vy; older
    // Python-built bundles don't, and keep the horizontal facing fallback.
    let ux = d, uy = 0
    if (it.vx && it.vy) {
      const vx = it.vx[k], vy = it.vy[k], m = Math.hypot(vx, vy)
      if (m > 1e-3) { ux = vx / m; uy = vy / m }
    }
    const st = it.s?.[k]
    const blast = EXPLOSIONS[t]
    if (blast && st === blast[0]) {
      // a bomb blowing up: the game hides it and shows its explosion (itemArt),
      // over the fighters like the game's effects; once that is over, nothing
      const age = framesIn(it, k)
      // (reading its record first: the audit gives a deferred draw to the item last read)
      const draw = () => { void it.x[k]; drawExplosion(ctx, age, x, y, blast[1], blast[2], wx, wy) }
      if (front) front.push(draw); else draw()
      continue
    }
    if (t === IT_EGG_THROW) {
      // Yoshi's Egg Throw: in his hand (0), flying and turning with the travel
      // like a thrown ball (1), breaking (2: our shell pieces, over the
      // fighters, for as long as the state lasts)
      if (st === 2) {
        const age = framesIn(it, k)
        let end = k
        while (end + 1 < it.s.length && it.s[end + 1] === 2) end++
        const [, R, hit] = EGG_BREAK
        const draw = () => { void it.x[k]; drawEggBreak(ctx, age, x, y, R, hit, wx, wy, age + end - k + 1) }
        if (front) front.push(draw); else draw()
      } else {
        const sgn = it.vx ? (it.vx[k] < 0 ? -1 : 1) : d
        drawThrownEgg(ctx, x, y, st === 1 ? -sgn * EGG_THROW.spin * (framesIn(it, k) + 1) : 0, wx, wy)
      }
      continue
    }
    if (look && look[0] === 'boomerang') {
      // Link's and Young Link's boomerang: in his hand (0), then spinning out
      // and back, a V the size of its body radius
      const sgn = it.vx ? (it.vx[k] < 0 ? -1 : 1) : d
      drawBoomerang(ctx, x, y, look[2] || rad, st ? -sgn * BOOMERANG_SPIN * framesIn(it, k, new Set([1, 2, 3])) : 0, FAMILY.boomerang[0], wx, wy)
      continue
    }
    if (look && look[0] === 'bomb' && t !== IT_SAMUS_BOMB) {
      // Link's and Young Link's bomb before it blows: a round bomb, its fuse lit
      drawRoundBomb(ctx, x, y, look[2] || rad, itemAge(it, k), FAMILY.bomb[0], wx, wy)
      continue
    }
    if (FIRE_LICKS.has(t)) {
      // Bowser's fire breath (Kirby's copy too) and Din's Fire: fire along its flight
      drawFireLick(ctx, x, y, rad, Math.atan2(uy, ux), itemAge(it, k), wx, wy)
      continue
    }
    if (look && look[0] === 'pkfire') {
      // PK Fire in flight: a short jagged bolt along its travel
      drawPkFireBolt(ctx, x, y, rad, Math.atan2(uy, ux), wx, wy)
      continue
    }
    if (IT_FIREBALL_SHAPE[t]) {
      // a ball of flame and its bright core, off-centre as the game's quad is
      // and spun about the item point: -sign(vx) x 30 degrees a frame (RAM-checked)
      const kind = IT_FIREBALL_SHAPE[t]
      const sgn = it.vx ? (it.vx[k] < 0 ? -1 : 1) : d
      const ang = -sgn * 0.5236 * (k + 1)
      ctx.globalAlpha = 0.8; shapePath(ctx, fireballPts(kind), x, y, ang, 1, wx, wy); ctx.fillStyle = FIREBALL[t][0]; ctx.fill()
      const [cx, cy, cr] = METRICS.fireball[kind].core, c = Math.cos(ang), sn = Math.sin(ang)
      ctx.globalAlpha = 1; ball(x + cx * c - cy * sn, y + cx * sn + cy * c, cr, FIREBALL[t][1])
    } else if (t === IT_MISSILE) {
      // Samus's missile along its velocity, nose first; exploded (2, 3) it lingers hidden
      if (st === 2 || st === 3) continue
      drawMissile(ctx, x, y, Math.atan2(uy, ux), wx, wy)
    } else if (t === IT_TURNIP) {
      if (st === 0 || st === 4) {
        // in the hand (or coming out of the ground) it is in front of Peach
        const draw = () => drawHeldTurnip(ctx, bundle, it, k, idx, wx, wy)
        if (front) front.push(draw); else draw()
        continue
      }
      // thrown: spins about its origin at 0.3665 rad/frame, + when it flies the way it faces
      const sgn = it.vx ? (Math.sign(it.vx[k]) === Math.sign(d) ? 1 : -1) : 1
      drawTurnip(ctx, x, y, sgn * 0.3665 * framesIn(it, k, new Set([1, 2, 3])), 1, wx, wy)
    } else if (t === PK_HEAD) {
      drawPkHead(ctx, x, y, wx, wy)
    } else if (PK_TRAIL.has(t)) {
      drawPkTrail(ctx, it, k, x, y, d, wx, wy)
    } else if (BOLT.has(t)) {
      // it strikes in front of Pikachu
      const draw = () => drawBolt(ctx, it, k, st, wx, wy, view.S)
      if (front) front.push(draw); else draw()
    } else if (NEEDLES.has(t)) {
      drawNeedle(ctx, it, k, x, y, d, wx, wy)
    } else if (CHARGE_SHOTS.has(t)) {
      drawChargeShot(ctx, it, k, st, x, y, wx, wy)
    } else if (t === 210 && bundle.meta?.stage === 8) {
      drawShyGuy(ctx, x, y, d, wx, wy, shyGuySpin(it, k))
    } else if (IT_ICE.has(t)) {
      // a block of ice turning about its upright axis once a second
      drawIce(ctx, framesIn(it, k), x, y, wx, wy)
    } else if (FIREBALL[t]) {
      ball(x, y, rad, FIREBALL[t][0]); ball(x, y, rad * 0.5, FIREBALL[t][1])
    } else if (VITAMIN.has(t)) {
      // two-tone capsule along its travel, as long as its hitbox is wide
      const r = 0.35 * rad
      ball(x - r * ux, y - r * uy, r, '#ff5d73')
      ball(x + r * ux, y + r * uy, r, '#ffe066')
    } else if (ARROWS[t]) {
      const len = 3.5
      ctx.strokeStyle = ARROWS[t]; ctx.lineWidth = 2
      ctx.beginPath(); ctx.moveTo(wx(x - len * ux), wy(y - len * uy)); ctx.lineTo(wx(x + len * ux), wy(y + len * uy)); ctx.stroke()
    } else if (look && look[0] === 'illusion') {
      // Fox's and Falco's side-B afterimage: a streak in its owner's colour
      ctx.globalAlpha = 0.45
      ctx.strokeStyle = it.o != null && it.o >= 0 ? pcolor(bundle, it.o) : '#aab4cc'
      ctx.lineWidth = Math.max(2, rad * view.S)
      ctx.beginPath(); ctx.moveTo(wx(x - 5 * ux), wy(y - 5 * uy)); ctx.lineTo(wx(x + 5 * ux), wy(y + 5 * uy)); ctx.stroke()
      ctx.globalAlpha = 1
    } else if (t !== IT_CHARGESHOT && t !== IT_MISSILE && t !== IT_SAMUS_BOMB && look && (FAMILY[look[0]] || AUTHORED[t])) {
      const [fill, burst] = FAMILY[look[0]] || AUTHORED[t]
      const r = look[0] === 'bomb' ? look[2] || rad : rad
      ball(x, y, r, fill, burst ? 0.45 : 1)
      if (burst) ball(x, y, r * 0.45, fill)
    } else if (BLASTER.has(t)) {
      drawBlasterShot(ctx, it, k, x, y, ux, uy, wx, wy, view.S)
    } else if (t === IT_FOX_LASER || t === IT_FALCO_LASER || t === IT_ARWING_LASER || t === IT_GREATFOX_LASER ||
        (look && look[0] === 'laser')) {
      // in-game colours (fox red, falco blue) read better than owner colour;
      // the stage ships' shots have no owner and get a light neutral colour
      ctx.strokeStyle = t === IT_FOX_LASER || t === 136 ? '#ff5c5c'
        : t === IT_ARWING_LASER || t === IT_GREATFOX_LASER ? '#f2e6c4' : '#6ea8ff'
      ctx.lineWidth = t === IT_GREATFOX_LASER ? 4 : 2.5
      ctx.beginPath()
      ctx.moveTo(wx(x - 4 * ux), wy(y - 4 * uy))
      ctx.lineTo(wx(x + 4 * ux), wy(y + 4 * uy))
      ctx.stroke()
    } else if (t === IT_SAMUS_BOMB) {
      ctx.fillStyle = '#c9d2e8'
      ctx.beginPath(); ctx.arc(wx(x), wy(y), Math.max(2, 2.4 * view.S / 2), 0, 7); ctx.fill()
    } else if (table) {
      drawTableLook(ctx, table, x, y, d, wx, wy, view.S, it.s?.[k])
    } else {
      const col = it.o != null && it.o >= 0 ? pcolor(bundle, it.o) : '#aab4cc'
      ctx.fillStyle = col
      ctx.beginPath(); ctx.arc(wx(x), wy(y), Math.max(2, 2 * view.S / 2), 0, 7); ctx.fill()
    }
  }
}

// A common item, Pokemon or stage object: a plain shape or our own simple
// picture over its ECB box (itemLooks.js), mirrored with its facing.
function drawTableLook(ctx, look, x, y, d, wx, wy, S, state) {
  const [, scale, up, down, front, back, fill, shape = 'ellipse', alpha = 1] = look
  const right = (d < 0 ? back : front) * scale, left = (d < 0 ? front : back) * scale
  const top = up * scale, bottom = down * scale
  const cx = wx(x + (right - left) / 2), cy = wy(y + (top - bottom) / 2)
  const rx = Math.max(1.5, (right + left) / 2 * S), ry = Math.max(1.5, (top + bottom) / 2 * S)
  ctx.globalAlpha = alpha
  if (drawItemIcon(ctx, shape, fill, cx, cy, rx, ry, d)) { ctx.globalAlpha = 1; return }
  ctx.fillStyle = fill
  ctx.beginPath()
  if (shape === 'rect') {
    const r = Math.min(rx, ry) * 0.35
    if (ctx.roundRect) ctx.roundRect(cx - rx, cy - ry, 2 * rx, 2 * ry, r)
    else ctx.rect(cx - rx, cy - ry, 2 * rx, 2 * ry)
    ctx.fill()
  } else if (shape === 'star') {
    for (let k = 0; k < 10; k++) {
      const a = -Math.PI / 2 + k * Math.PI / 5, f = k % 2 ? 0.45 : 1
      const px = cx + Math.cos(a) * rx * f, py = cy + Math.sin(a) * ry * f
      if (k) ctx.lineTo(px, py); else ctx.moveTo(px, py)
    }
    ctx.closePath(); ctx.fill()
  } else if (shape === 'tingle') {
    // a balloon over the box's top half, Tingle hanging under it. States 0-2
    // are the balloon still up (stageSim/stage13.js); after it pops, Tingle.
    if (state == null || state <= 2) {
      const br = Math.min(rx, ry / 2)
      ctx.fillStyle = '#ff6a8a'
      ctx.arc(cx, cy - ry + br, br, 0, 7); ctx.fill()
    }
    ctx.fillStyle = fill
    ctx.beginPath(); ctx.ellipse(cx, cy + ry / 2, rx * 0.5, ry / 2, 0, 0, 7); ctx.fill()
  } else {
    ctx.ellipse(cx, cy, rx, ry, 0, 0, 7); ctx.fill()
    if (shape === 'ring' || shape === 'shyguy') {
      // a target's or coin's inner ring; a Shy Guy's white mask, facing forward
      ctx.fillStyle = shape === 'ring' ? '#0a0c12' : '#f4f0e8'
      const mx = shape === 'shyguy' ? cx + (d < 0 ? -1 : 1) * rx * 0.35 : cx
      ctx.beginPath(); ctx.ellipse(mx, cy, rx * 0.45, ry * 0.55, 0, 0, 7); ctx.fill()
    }
  }
  ctx.globalAlpha = 1
}

// Fox's and Falco's reflector ("shine"), drawn the way the game draws its
// effect: shapes, sizes, turns and centre all come from the effect models
// (meleeRender.reflectorAt). Corners sit at 30 + 60k degrees: one straight up,
// one straight down. It is a billboard, so facing never mirrors or turns it.
// It needs no animation data, so dot mode shows it too.
const HEX_CORNERS = [30, 90, 150, 210, 270, 330].map(d => d * Math.PI / 180)
function hexPath(ctx, cx, cy, R) {
  HEX_CORNERS.forEach((a, k) => {
    const px = cx + R * Math.cos(a), py = cy - R * Math.sin(a)
    k ? ctx.lineTo(px, py) : ctx.moveTo(px, py)
  })
  ctx.closePath()
}
function drawReflector(ctx, cid, states, ages, idx, x, y, facing, view, dpr) {
  const r = reflectorAt(cid, states[idx], { age: ages ? ages[idx] : 0, held: heldFrames(states, idx) })
  if (!r) return
  const S = view.S
  const cx = view.ox + (x + r.dx * (facing || 1)) * S
  const cy = view.oy - (y + r.dy) * S
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.lineJoin = 'round'
  for (const p of r.pieces) {
    const R = p.r * S
    if (p.shape === 'band') {
      // held: light blue between dark blue edges, the middle see-through
      ctx.beginPath(); hexPath(ctx, cx, cy, R); hexPath(ctx, cx, cy, p.hole * S)
      ctx.globalAlpha = 0.85; ctx.fillStyle = '#72d1ff'; ctx.fill('evenodd')
      ctx.globalAlpha = 1; ctx.strokeStyle = '#4179ff'
      ctx.lineWidth = Math.max(1, 0.09 * R); ctx.beginPath(); hexPath(ctx, cx, cy, R); ctx.stroke()
      ctx.lineWidth = Math.max(1, 0.12 * p.hole * S); ctx.beginPath(); hexPath(ctx, cx, cy, p.hole * S); ctx.stroke()
    } else if (p.shape === 'ring') {
      // starting: a light rim fading out to either side
      const mid = (R + p.rim * S) / 2, wide = (p.fade[1] - p.fade[0]) * S
      ctx.strokeStyle = '#ace8ff'
      for (const [alpha, width] of [[0.15, wide], [0.25, wide / 2], [1, Math.max(1.5, R - p.rim * S)]]) {
        ctx.globalAlpha = alpha; ctx.lineWidth = width
        ctx.beginPath(); hexPath(ctx, cx, cy, mid); ctx.stroke()
      }
    } else if (p.shape === 'half') {
      // three of the six triangles, white
      ctx.beginPath(); ctx.moveTo(cx, cy)
      for (let k = 0; k <= 3; k++) {
        const a = p.from + k * Math.PI / 3
        ctx.lineTo(cx + R * Math.cos(a), cy - R * Math.sin(a))
      }
      ctx.closePath(); ctx.globalAlpha = 0.85; ctx.fillStyle = '#ffffff'; ctx.fill()
    }
  }
  ctx.globalAlpha = 1
}

// Highest action state id that is not drawn (DeadDown..DeadUpFallHitCameraIce,
// then Sleep). Rebirth (12) and RebirthWait (13) ride the halo and are drawn.
const DEAD_MAX = 11

// Paint one frame of stage + fighters onto ANY context. Reused by the live
// canvas, the GIF exporter, and the Combo Video preview/MP4 exporter.
export function paintFrame(ctx, bundle, anim, renderer, idx, view, dpr) {
  const wx = (x) => view.ox + x * view.S
  const wy = (y) => view.oy - y * view.S
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = '#0a0c12'
  ctx.fillRect(0, 0, ctx.canvas.width / dpr, ctx.canvas.height / dpr)
  // star KOs fly far behind the stage; screen KOs come at the camera (koFlight)
  const drawFlight = (of, o) => { if (renderer && anim) renderer.draw(ctx, anim, { ...o, fill: pcolor(bundle, of), stroke: null, dpr }) }
  drawKoFlights(ctx, bundle, idx, view, dpr, 'back', drawFlight)
  const stage = stageGeometryAt(bundle, idx)
  // the half of a tech's rings behind the fighters: the stage and the fighters
  // drawn next cover it, as the game's depth test does (techEffects)
  drawTechRings(ctx, bundle, idx, view, dpr, 'back', stage)
  if (stage.fills.length) {
    // the body of every landmass, traced from its active solid collision
    // (one winding, so the nonzero fill is their union)
    ctx.beginPath()
    for (const poly of stage.fills) {
      poly.forEach((p, i) => { i ? ctx.lineTo(wx(p[0]), wy(p[1])) : ctx.moveTo(wx(p[0]), wy(p[1])) })
      ctx.closePath()
    }
    ctx.fillStyle = '#20263a'; ctx.fill()
  }
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'
  // Real walls/ceilings are strokes, including those of separate landmasses.
  // The decorative underside is never stroked as a floor.
  for (const [, flags, x0, y0, x1, y1] of stage.lines) {
    // a floor sunk into the body is hidden in game (FoD's side platforms at
    // the bottom of their travel); a real floor always has open space above.
    // A wall or ceiling with body on both sides is a seam, not an edge.
    if (flags & 1 ? buriedPlatform(stage.fills, x0, y0, x1, y1) : interiorLine(stage.fills, x0, y0, x1, y1)) continue
    ctx.strokeStyle = flags & 1 ? '#3e465f' : '#525b78'
    ctx.lineWidth = flags & 1 ? 4 : 2
    ctx.beginPath(); ctx.moveTo(wx(x0), wy(y0)); ctx.lineTo(wx(x1), wy(y1)); ctx.stroke()
  }
  if (stage.partial) {
    // Existing grounded trail remains only for unresolved random pieces or a
    // frame outside the measured animation range. Do not cover an exact floor
    // with a second, arbitrary-width bar when a fighter already fits it.
    const fr = bundle.frames
    const nearFloor = (x, y) => stage.floors.some(([x0, y0, x1, y1]) => {
      if (x < Math.min(x0, x1) - 1 || x > Math.max(x0, x1) + 1 || x0 === x1) return false
      return Math.abs(y - y0 - (y1 - y0) * (x - x0) / (x1 - x0)) <= 3
    })
    if (fr.air) {
      const TRAIL = 90
      ctx.strokeStyle = '#3e465f'
      for (let t = Math.max(0, idx - TRAIL); t <= idx; t += t === idx ? 1 : Math.min(2, idx - t)) {
        ctx.globalAlpha = t === idx ? 1 : 0.08 + 0.45 * (1 - (idx - t) / TRAIL)
        ctx.lineWidth = t === idx ? 4 : 3
        for (let i = 0; i < fr.x.length; i++) {
          // only a fighter standing on something itself; never a throw victim
          if (!groundWitness(fr, i, t)) continue
          const x = fr.x[i][t], y = fr.y[i][t]
          if (nearFloor(x, y)) continue
          const half = t === idx ? 22 : 9
          ctx.beginPath(); ctx.moveTo(wx(x - half), wy(y)); ctx.lineTo(wx(x + half), wy(y)); ctx.stroke()
        }
      }
      ctx.globalAlpha = 1
    } else if (!stage.lines.length) {
      ctx.strokeStyle = '#3e465f'; ctx.lineWidth = 4
      const edge = bundle.meta.stage_edge || 70
      ctx.beginPath(); ctx.moveTo(wx(-edge), wy(0)); ctx.lineTo(wx(edge), wy(0)); ctx.stroke()
    }
  }
  // Whispy's wind, behind the items and fighters it is pushing (Dream Land
  // only — a no-op everywhere else, and one array read per frame there).
  drawWind(ctx, bundle, idx, view, dpr)
  // what stands behind the fighters: the revival platform, the Fire Fox plume
  const fr = bundle.frames
  for (let i = 0; i < fr.x.length; i++) {
    const s = fr.state[i][idx]
    if (s === 12 || s === 13) drawRebirthPlatform(ctx, fr.cid[i][idx], fr.x[i][idx], fr.y[i][idx], fr.dir?.[i]?.[idx] || 1, view)
    // a Fire Fox / Fire Bird plume, around and behind its fighter
    if (s === 355 || s === 356) {
      drawFireFox(ctx, fr.cid[i][idx], s, fr.age?.[i]?.[idx], idx, fr.x[i], fr.y[i], fr.dir?.[i]?.[idx] || 1, view, dpr, stage.fills, true)
    }
  }
  // shield-break bursts behind the stage plane (impactEffects)
  drawImpactEffects(ctx, bundle, idx, view, dpr, true)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  // projectiles/items under the fighters, over the stage; what a fighter
  // holds is drawn in front of them, once they are all down
  const held = []
  drawItems(ctx, bundle, idx, view, dpr, held)
  // items a fighter holds ride in its hand, in front of it
  held.push(() => drawItems(ctx, bundle, idx, view, dpr, null, true))

  const f = bundle.frames
  const NP = f.x.length
  // Shields and reflectors are see-through effects the game draws after every
  // opaque model: painted once all fighters (Nana included) are down.
  const effects = []
  for (let i = 0; i < NP; i++) {
    // Dead (action states 0-10) and Sleep (11, between stocks) fighters are
    // not on screen in game: the blast has happened and the next stock has
    // not appeared. Drawing them left a dot parked at the blast zone.
    if (f.state[i][idx] <= DEAD_MAX) continue
    const col = pcolor(bundle, i)
    const x = f.x[i][idx], y = f.y[i][idx]
    const dir = (f.dir && f.dir[i]) ? f.dir[i][idx] : 1
    // a hit victim's model shakes through its hitlag (hitSparks.hitShake)
    const shake = hitShake(bundle, i, idx)
    const bx = shake ? x + shake[0] : x, by = shake ? y + shake[1] : y
    let drew = false
    if (renderer && anim) {
      drew = renderer.draw(ctx, anim, {
        cid: f.cid[i][idx], state: f.state[i][idx], age: f.age[i][idx],
        x: bx, y: by, facing: dir, fill: flashFill(bundle, i, idx, col), stroke: null, outline: invincibleOutline(f.state[i], idx), view, dpr,
        states: f.state[i], ages: f.age[i], idx,
      })
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    // the game hides the fighter here (in a barrel, swallowed, mid-vanish)
    if (drew === 'hidden') continue
    if (!drew) {
      ctx.beginPath(); ctx.arc(wx(bx), wy(by), 7, 0, 7); ctx.fillStyle = col; ctx.fill()
      ctx.lineWidth = 1.5; ctx.strokeStyle = '#0b0d13'; ctx.stroke()
    }
    // shield bubble while guarding — NOT GuardOff (180): in-game the bubble
    // is already gone during the release animation. 181 = shieldstun, stays.
    const stt = f.state[i][idx]
    if (renderer && renderer.shield && f.shield && stt >= 178 && stt <= 182 && stt !== 180) {
      const lt = (f.lt && f.lt[i]) ? f.lt[i][idx] / 100 : null
      const rows = { state: f.state[i], joyx: f.joyx?.[i], joyy: f.joyy?.[i], lt: f.lt?.[i], dir: f.dir?.[i], shield: f.shield[i], age: f.age?.[i] }
      // shield stun: the torn bubble instead of the disc, and its scribble
      const stun = shieldStun(f.state[i], f.shield[i], idx)
      const o = { cid: f.cid[i][idx], x, y, facing: dir, health: f.shield[i][idx], light: lt, color: col, view, dpr, rows, idx, shape: stun?.[0] }
      effects.push(() => { const b = renderer.shield(ctx, o); if (stun) drawShieldScribble(ctx, stun[1], b, view, dpr) })
    }
    effects.push(() => drawReflector(ctx, f.cid[i][idx], f.state[i], f.age && f.age[i], idx, x, y, dir, view, dpr))
    effects.push(() => drawFireFox(ctx, f.cid[i][idx], stt, f.age?.[i]?.[idx], idx, f.x[i], f.y[i], dir, view, dpr, null, false))
    // (no floating % label following the fighter — the HUD chips carry the
    // percents; the double display read as clutter. User call, desktop too.)
  }

  // ICs Nana — render-only follower rows (frames.fol), drawn in her leader's
  // color with the same visual language. Null entries = she's dead/absent.
  for (const [k, fo] of (f.fol || []).entries()) {
    const x = fo.x[idx], y = fo.y[idx], stt = fo.state[idx]
    if (x == null || stt == null || stt <= DEAD_MAX) continue
    const col = pcolor(bundle, fo.of)
    const dir = (fo.dir && fo.dir[idx] != null) ? fo.dir[idx] : 1
    const shake = hitShake(bundle, `fol:${k}`, idx)
    const bx = shake ? x + shake[0] : x, by = shake ? y + shake[1] : y
    let drew = false
    if (renderer && anim) {
      drew = renderer.draw(ctx, anim, {
        cid: fo.cid[idx], state: stt, age: (fo.age && fo.age[idx] != null) ? fo.age[idx] : 0,
        x: bx, y: by, facing: dir, fill: flashFill(bundle, `fol:${k}`, idx, col), stroke: null, outline: invincibleOutline(fo.state, idx), view, dpr,
        states: fo.state, ages: fo.age, idx,
      })
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    if (drew === 'hidden') continue
    if (!drew) {
      ctx.beginPath(); ctx.arc(wx(bx), wy(by), 7, 0, 7); ctx.fillStyle = col; ctx.fill()
      ctx.lineWidth = 1.5; ctx.strokeStyle = '#0b0d13'; ctx.stroke()
    }
    if (renderer && renderer.shield && fo.shield && stt >= 178 && stt <= 182 && stt !== 180) {
      // Nana's trigger isn't recorded; she echoes her leader's press depth.
      const lt = (f.lt && fo.of != null && f.lt[fo.of]) ? f.lt[fo.of][idx] / 100 : null
      // her stick is not recorded: the bubble sits untilted on her shield bone
      const rows = { state: fo.state, lt: fo.of != null ? f.lt?.[fo.of] : null, dir: fo.dir, shield: fo.shield, age: fo.age }
      const stun = shieldStun(fo.state, fo.shield, idx)
      const o = { cid: fo.cid[idx], x, y, facing: dir, health: fo.shield[idx], light: lt, color: col, view, dpr, rows, idx, shape: stun?.[0] }
      effects.push(() => { const b = renderer.shield(ctx, o); if (stun) drawShieldScribble(ctx, stun[1], b, view, dpr) })
    }
    effects.push(() => drawReflector(ctx, fo.cid[idx], fo.state, fo.age, idx, x, y, dir, view, dpr))
  }
  // sword trails: the game draws each in its fighter's see-through pass, after
  // the model (ftCo_800C2600)
  drawSwordTrails(ctx, bundle, idx, view, dpr)
  for (const draw of [...effects, ...held]) { ctx.setTransform(dpr, 0, 0, dpr, 0, 0); draw() }
  // movement dust (dashes, turns, jumps, landings, steps; movementDust), under the sparks
  drawDust(ctx, bundle, idx, view, dpr)
  // hit sparks: the game draws its particles after every model
  drawHitSparks(ctx, bundle, idx, view, dpr)
  // techs: the rings' front half (kept out of the stage's body), the glow and
  // the rays (techEffects)
  drawTechEffects(ctx, bundle, idx, view, dpr, stage)
  // missed techs and shield breaks (impactEffects)
  drawImpactEffects(ctx, bundle, idx, view, dpr)
  if (bundle.meta?.stage === 9) drawOnettCars(ctx, bundle, idx, view, dpr)
  // KO blasts: the game draws them over the stage and the fighters (koBlast)
  drawKoBlasts(ctx, bundle, idx, view, dpr)
  drawKoFlights(ctx, bundle, idx, view, dpr, 'front', drawFlight)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}

// Randall — the Yoshi's Story cloud, our mascot, drawn as our own cloud
// (itemArt.drawRandallCloud) on the moving platform on YS, sized and placed on
// the platform line as the game's model carries its quad.
export function drawRandall(ctx, slippiFrame, view, dpr) {
  const p = randallPlatform(slippiFrame)
  if (!p) return
  // under the stage the cloud is behind the landmass: the game shows nothing
  const g = collisionGeometry(8, slippiFrame)
  if (g && buriedPlatform(cachedFills(g.lines), p.left[0], p.left[1], p.right[0], p.right[1])) return
  const wx = (x) => (view.ox + x * view.S) * dpr
  const wy = (y) => (view.oy - y * view.S) * dpr
  const lx = wx(p.left[0]), rx = wx(p.right[0]), y = wy(p.left[1])
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  // the cloud's quad and the line ride the same joint (GrSt.dat, itemMetrics.js
  // randall): its width, height, centre and where the line crosses it
  const R = METRICS.randall, w = (rx - lx) * R.w, h = w * R.h
  drawRandallCloud(ctx, (lx + rx) / 2 + (rx - lx) * R.dx - w / 2, y - h * R.line, w, h)
  ctx.strokeStyle = '#d7dcea'; ctx.lineWidth = 3 * dpr; ctx.lineCap = 'round'
  ctx.beginPath(); ctx.moveTo(lx, y); ctx.lineTo(rx, y); ctx.stroke()
}

// Canvas HUD burned into exports (name, stocks, %) since the HTML overlay
// isn't part of the canvas. W/H are actual pixels (dpr already applied).
// `scale` multiplies every metric: the defaults were tuned for a ~640px
// export canvas, which renders microscopic on a 3x-dpr phone — mobile passes
// its own scale; existing callers (GIF/MP4 exporters) get 1 and are unchanged.
// `icons` ({playerIndex: HTMLImageElement}) swaps the colored dots for real
// stock icons — the big one replaces the port dot, minis replace the stock
// pips. The RIGHT chip in a 1v1 mirrors the left (% inside, icon outside) so
// the two read symmetrically. No icons -> the old dot rendering.
export function paintHudCanvas(ctx, bundle, idx, W, H, scale = 1, icons = null) {
  const f = bundle.frames, meta = bundle.meta, NP = meta.players.length
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.textBaseline = 'alphabetic'
  ctx.imageSmoothingEnabled = false
  const S = scale
  const cw = 120 * S, ch = 30 * S, y = 8 * S, m = 8 * S
  for (let i = 0; i < NP; i++) {
    const p = meta.players[i]
    const name = (p.tag || p.code || p.char_name || '').slice(0, 14)
    const stk = Math.max(0, Math.min(4, f.stk[i][idx]))
    const col = pcolor(bundle, i)
    const icon = icons && icons[i]
    const mirror = NP === 2 && i === 1   // right chip mirrors the left
    // 1v1 -> corners; doubles/FFA -> spread left-to-right along the top
    const x = NP === 2 ? (i === 0 ? m : W - cw - m)
      : Math.min(m + i * (cw + 6 * S), W - cw - m)
    // rounded chip rather than a bare rect — reads as UI, not debug overlay
    ctx.fillStyle = 'rgba(11,13,19,.72)'
    if (ctx.roundRect) {
      ctx.beginPath(); ctx.roundRect(x, y, cw, ch, 8 * S); ctx.fill()
    } else {
      ctx.fillRect(x, y, cw, ch)
    }

    const iconBox = 18 * S
    const iconX = mirror ? x + cw - 4 * S - iconBox : x + 4 * S
    if (icon) {
      ctx.drawImage(icon, iconX, y + (ch - iconBox) / 2, iconBox, iconBox)
    } else {
      ctx.fillStyle = col
      ctx.beginPath()
      ctx.arc(iconX + iconBox / 2, y + ch / 2, 4 * S, 0, 7)
      ctx.fill()
    }

    const nameX = mirror ? x + cw - 6 * S - iconBox : x + 6 * S + iconBox
    ctx.fillStyle = '#eaeef7'; ctx.font = `600 ${11 * S}px system-ui`
    ctx.textAlign = mirror ? 'right' : 'left'
    ctx.fillText(name, nameX, y + 13 * S)

    // mini stock icons under the name (fallback: the old colored dots)
    const mini = 8 * S
    for (let s = 0; s < stk; s++) {
      const sx = mirror ? nameX - (s + 1) * (mini + 1.5 * S) : nameX + s * (mini + 1.5 * S)
      if (icon) {
        ctx.drawImage(icon, sx, y + 17 * S, mini, mini)
      } else {
        ctx.fillStyle = col
        ctx.beginPath(); ctx.arc(sx + mini / 2, y + 21 * S, 3 * S, 0, 7); ctx.fill()
      }
    }

    ctx.fillStyle = '#fff'; ctx.font = `700 ${15 * S}px ui-monospace, monospace`
    ctx.textAlign = mirror ? 'left' : 'right'
    ctx.fillText(Math.round(f.pct[i][idx]) + '%', mirror ? x + 8 * S : x + cw - 8 * S, y + 24 * S)
  }
}
