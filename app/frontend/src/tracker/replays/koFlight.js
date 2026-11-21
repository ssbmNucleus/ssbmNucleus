// Star KOs and screen KOs: a fighter KO'd through the top blast zone is not
// blasted; its own model flies (melee decomp ft_0D31.c, ftdrawcommon.c;
// data/koEffects.js star, screen):
// - star KO (DeadUpStar 4, ice 5): after a frame it flies on a straight line
//   into the background, to z = -350 over 130 frames while the replay's own
//   x, y take it down to 0.6 of the camera's top bound, tumbling (DamageFall);
//   then it hides and a twinkle (effect 0x42D) flashes where it went;
// - screen KO (DeadUpFall 6, ice 9): its model is put in camera space, coming
//   from above and behind the camera's view toward it (50 frames), held on the
//   camera (DeadUpFallHitCamera 7, flat 8, ice 10; 3 frames), then falling away
//   down the screen (40 frames); then it hides.
// Watch Lite is flat, so the depth is drawn as the game camera shows it: a
// camera with the game's 30 degree field of view that sees exactly Watch Lite's
// view at z = 0, pitched and turned as the game turns its camera for where it
// looks (camera.c Camera_80029CF8, data/koEffects.js camera): a point at depth
// z is moved as that camera shows it moved from z = 0, and scaled by how much
// farther it is. The tumble is DamageFall's pose, the animation the game
// plays (ftmotionstates.c); the hit-the-camera animation is not in Watch
// Lite's packs, so its last DamageFall pose is held, and the ice versions
// hold the frozen pose.
import KO from './data/koEffects.js'
import { drawEffectParticle } from './koBlast.js'

const STAR = new Set([4, 5]), SCREEN = new Set([6, 7, 8, 9, 10]), ICE = new Set([5, 9, 10])
const DAMAGE_FALL = 38
const TAN = Math.tan(KO.fovy * Math.PI / 360), RAD = Math.PI / 180
const ST = KO.star, SC = KO.screen, CAM = KO.camera
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const STAR_SHOWN = ST.wait + ST.frames, SCREEN_SHOWN = SC.wait + SC.lerp + SC.hold + SC.fall

// The screen KO's point in camera space k frames after it began (ftCo_DeadUpFall_Anim / _Phys).
export function screenPoint(k) {
  if (k <= 0) return SC.start
  if (k <= SC.lerp) return SC.start.map((a, i) => a + (SC.end[i] - a) * k / SC.lerp)
  let [x, y, z] = SC.end, v = SC.vy
  for (let j = SC.lerp + SC.hold + 1; j <= k; j++) { v = Math.max(v - SC.gravity, -SC.terminal); y += v; z += SC.vz }
  return [x, y, z]
}
// The star KO's depth k frames after it began.
export function starDepth(k) {
  return ST.z * Math.max(0, Math.min(ST.frames, k - ST.wait + 1)) / ST.frames
}

// The action state whose animation a star or screen KO'd fighter shows
// (DamageFall), or null: whoever narrows a replay's animation packs to the
// states it uses keeps this one too, as the replay never records it.
export function flightPoseState(state) {
  return STAR.has(state) || SCREEN.has(state) ? DAMAGE_FALL : null
}

function runStart(states, idx, set) {
  let j = idx
  while (j > 0 && set.has(states[j - 1])) j--
  return j
}

// Every fighter row (leaders and Nana) with its player for the colour.
function rows(bundle) {
  const f = bundle.frames
  const out = f.state.map((st, i) => ({ st, x: f.x[i], y: f.y[i], dir: f.dir?.[i], age: f.age?.[i], cid: f.cid[i], of: i }))
  for (const fo of f.fol || []) out.push({ st: fo.state, x: fo.x, y: fo.y, dir: fo.dir, age: fo.age, cid: fo.cid, of: fo.of })
  return out
}

// What a star or screen KO'd fighter shows on idx: {kind ('star' | 'screen'),
// of, cid, state, age, x, y, facing, scale} with x, y where it appears on Watch
// Lite's z = 0 plane, or {kind, of, twinkle: k, x, y, scale}. `cam` = {cx, cy, D}: the view's centre and the
// game camera's distance for it.
export function koFlightsAt(bundle, idx, cam) {
  const out = []
  if (!bundle?.frames?.state) return out
  for (const r of rows(bundle)) {
    const s = r.st[idx]
    if (STAR.has(s)) {
      const j = runStart(r.st, idx, STAR), k = idx - j
      const [x, y, sc] = atDepth(cam, r.x[idx], r.y[idx], starDepth(k))
      if (k < STAR_SHOWN) out.push({ ...pose(r, idx, j, s, Infinity), kind: 'star', of: r.of, x, y, scale: sc })
      else out.push({ kind: 'star', of: r.of, twinkle: k - STAR_SHOWN, x, y, scale: sc })
    } else if (SCREEN.has(s)) {
      const j = runStart(r.st, idx, SCREEN), k = idx - j
      if (k >= SCREEN_SHOWN) continue
      const [px, py, pz] = screenPoint(k), sc = cam.D / -pz
      out.push({ ...pose(r, idx, j, s, j + SC.lerp), kind: 'screen', of: r.of, x: cam.cx + px * sc, y: cam.cy + py * sc, scale: sc })
    }
  }
  return out
}
// the pose to draw: DamageFall as the game plays it, held from `holdFrom` on;
// the ice versions keep the frozen pose from before the KO
function pose(r, idx, j, s, holdFrom) {
  if (ICE.has(s) && j > 0) return { cid: r.cid[j - 1], state: r.st[j - 1], age: r.age?.[j - 1] || 0, facing: r.dir?.[j - 1] || 1 }
  const at = Math.min(idx, holdFrom)
  return { cid: r.cid[idx], state: DAMAGE_FALL, age: r.age?.[at] || 0, facing: r.dir?.[idx] || 1 }
}

// The game camera for Watch Lite's view on stage `stage`: looking at the
// view's centre from the distance at which a 30 degree field of view sees the
// view's height at z = 0, pitched and turned by the game's rule for where it
// looks (the view stands in for the game's camera bounds).
export function viewCamera(view, w, h, stage) {
  const S = view.S, cx = (w / 2 - view.ox) / S, cy = (view.oy - h / 2) / S, D = h / S / 2 / TAN
  const [yawK, pitchK, pan, offX, offY] = CAM.stages[stage] || [0, 0, -10, 0, 0]
  const len = Math.max(w, h) / S, [b0, b1, l0, l1] = CAM.blend
  const blend = len > l1 ? b1 : len < l0 ? b0 : b0 + (b1 - b0) * (len - l0) / (l1 - l0)
  const pitch = (clamp(-((2 * (cy - offY) * (0.5 - blend) + offY + CAM.pitch[0]) * pitchK), CAM.pitch[1], CAM.pitch[2]) + pan) * RAD
  const yaw = clamp(-((cx - offX) * yawK), CAM.yaw[0], CAM.yaw[1]) * RAD
  const eye = [cx + CAM.aspect * D * Math.tan(yaw), cy - D * Math.sin(pitch), D * Math.cos(pitch)]
  const d = [cx - eye[0], cy - eye[1], -eye[2]], n = Math.hypot(...d), f = d.map((v) => v / n)
  const a = Math.atan2(f[0], -f[2]), r = [Math.cos(a), 0, Math.sin(a)]
  const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
  return { cx, cy, D, eye, f, r, u }
}
// where a point at (x, y, z) shows on the z = 0 plane, and its size there
function atDepth(cam, x, y, z) {
  const proj = (pz) => {
    const v = [x - cam.eye[0], y - cam.eye[1], pz - cam.eye[2]]
    const d = v[0] * cam.f[0] + v[1] * cam.f[1] + v[2] * cam.f[2]
    return [(v[0] * cam.r[0] + v[1] * cam.r[1] + v[2] * cam.r[2]) * cam.D / d,
      (v[0] * cam.u[0] + v[1] * cam.u[1] + v[2] * cam.u[2]) * cam.D / d, d]
  }
  const [x0, y0, d0] = proj(0), [x1, y1, d1] = proj(z)
  return [x + x1 - x0, y + y1 - y0, d0 / d1]
}

// Star KOs ('back': far behind the stage, with their twinkles) or screen KOs
// ('front': in front of everything). `drawFighter(of, o)` draws a silhouette
// for player `of` (o = {cid, state, age, x, y, facing, view}).
export function drawKoFlights(ctx, bundle, idx, view, dpr, layer, drawFighter) {
  const w = ctx.canvas.width / dpr, h = ctx.canvas.height / dpr
  const cam = viewCamera(view, w, h, bundle.meta?.stage)
  for (const f of koFlightsAt(bundle, idx, cam)) {
    if ((layer === 'front') !== (f.kind === 'screen')) continue
    if (f.twinkle != null) {
      const fr = ST.twinkle.frames[f.twinkle]
      if (!fr) continue
      ctx.save()
      for (const p of fr) drawEffectParticle(ctx, ST.twinkle, p, { x: f.x, y: f.y, turn: 0 }, f.scale, view, dpr)
      ctx.restore()
      ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
      continue
    }
    // the silhouette scaled about where it appears
    const v = { S: view.S * f.scale, ox: view.ox + view.S * f.x * (1 - f.scale), oy: view.oy - view.S * f.y * (1 - f.scale) }
    drawFighter(f.of, { cid: f.cid, state: f.state, age: f.age, x: f.x, y: f.y, facing: f.facing, view: v })
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}
