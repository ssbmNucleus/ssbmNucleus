// Hit sparks: the effect the game draws where a hit lands, and the victim's
// hitlag shake. Which effect, and where, is the game's rule (melee decomp):
// - ftcoll.c ftColl_8007A06C picks the effect by the hitbox element
//   (ftColl_803C0CAC): normal (and ground, cape) 0x3E8, fire 0x3EA, electric
//   0x3E9, slash 0x3EC, ice 0x3ED, dark 0x416; sleep, grab, inert, screw and
//   the rest spawn nothing. A normal hit with knockback >= 180 (PlCo
//   ftCommonData +0x3F0) spawns 0x3F3 instead; otherwise the effect is scaled
//   0.3 + 0.04 x damage, clamped to [0.3, 1.5] (ftColl_80078538, efasync.c).
// - It sits on the victim's hurtbox surface facing the hitbox (lbcollision.c
//   lbColl_80006E58). Watch Lite has the attacker's hitboxes (data/hits/<cid>.json,
//   from the ISO; hosts load them, stageData.ensureReplayHitData) but not the
//   victim's hurtboxes, so the spark goes from the hitbox centre half its
//   radius toward the victim's middle (against the game's own contact point,
//   Fighter +0x1854 in RAM, over 84 hits: median 1.8 units off, 2.8 for the
//   hitbox centre).
// - A hit on a shield spawns generator 93 (1052) at the contact on the bubble:
//   the bubble's (meleeRender.shieldAt) surface facing the hitbox.
// - Throws spawn no spark (RAM-checked).
// The effects themselves are the game's particles, read frame by frame in
// playback Dolphin (data/hitEffects.js, tools/liteaudit/hit_effects/build.py):
// where each one is, its size, turn, colours, alpha and how long it lives, each
// drawn with EfCoData.dat's own texture, traced, and the slash with its model's
// crescents, traced. A hit on a shield draws our own shapes instead
// (sparkArt.js: the owner likes them big and easy to see), and so does shield
// stun's torn bubble, timed and sized from the game's model. Slippi records the
// damage, hitstun (0.4 x knockback), hitlag and who hit whom; a frame the
// victim's percent rises and its hitlag starts is a hit. With no hitbox or
// projectile near enough (a laser, a stage hazard, a custom fighter), the
// spark goes to the victim's side facing who hit it.
import FX from './data/hitEffects.js'
import ITEM_SIZES from './data/itemSizes.json'
import ITEM_ELEMENTS from './data/hitElements.json'
import { hitDataFor, hitDataReady } from './stageData.js'
import { shieldAt } from './meleeRender.js'
import { drawArt } from './sparkArt.js'

// element -> effect (ftColl_803C0CAC); missing: no spark
const EFFECT = { 0: 'normal', 1: 'fire', 2: 'electric', 3: 'slash', 4: 'normal', 5: 'ice', 9: 'normal', 10: 'normal', 13: 'dark' }
const STRONG_HITSTUN = 72          // knockback 180 x 0.4 (hitstun = 0.4 x kb)
const THROWN = new Set([239, 240, 241, 242, 243])
const GUARDING = new Set([178, 179, 181, 182])
const MIDDLE = 8                   // the victim's middle above its position
const NEAR_ITEM = 25               // a projectile this close to the victim's middle may have hit it
const SIDE = 4                     // the victim's side from its middle (a hit with nothing to place it by)
const SHY_GUY = 210                // Yoshi's Story's Shy Guys (It_Kind_Heiho), hit like fighters
const SHY_HIT = new Set([2, 3])    // knocked off, flinching (itheiho.c it_802D8EC8)
// Slippi records no damage for items: a Shy Guy's normal-hit effect is drawn
// at this scale (RAM: 0.77 and 0.87 on two recorded hits)
const ITEM_HIT_SCALE = 0.82
// the contact on a Shy Guy's hurtbox: this far from its position toward the
// hitbox (RAM: 3.5 and 4.0 on two recorded hits)
const SHY_HURT = 3.8

const r0 = (v) => Math.round(v)
function runsAt(runs, frame) {
  for (const [a, b, boxes] of runs) if (frame >= a && frame <= b) return boxes
  return null
}
// [{x, y, r, el}] the hitboxes a fighter row has out on idx: its own state and
// action frame, or (a trade: it is already reacting to a hit) the attack it was
// in a frame earlier
function spheres(cid, states, ages, xs, ys, dirs, idx) {
  const table = hitDataFor(cid)?.states
  if (!table) return []
  for (const [st, age] of [[states[idx], ages?.[idx]], [states[idx - 1], (ages?.[idx - 1] ?? -2) + 1]]) {
    let runs = table[st]
    if (typeof runs === 'number') runs = table[runs]
    const boxes = runs && Number.isFinite(age) ? runsAt(runs, r0(age)) : null
    if (boxes) {
      const d = dirs?.[idx] || 1
      return boxes.map(([dx, dy, r, el]) => ({ x: xs[idx] + d * dx, y: ys[idx] + dy, r, el }))
    }
  }
  return []
}
// an item's owner as a player index: its per-frame port when recorded, else
// its (physical port) owner through the players' list; -1 when unknown
function itemOwner(bundle, it, k) {
  if (Number.isInteger(it.port?.[k])) return it.port[k]
  const owner = it.owner?.[k] ?? it.o
  if (owner == null || owner < 0) return -1
  return bundle.meta?.players?.findIndex(p => p.physical_port === owner) ?? -1
}
// the point of the segment (x0, y0)-(x1, y1) nearest (mx, my)
function closestOnSegment(x0, y0, x1, y1, mx, my) {
  const dx = x1 - x0, dy = y1 - y0, l2 = dx * dx + dy * dy
  const t = l2 > 1e-9 ? Math.max(0, Math.min(1, ((mx - x0) * dx + (my - y0) * dy) / l2)) : 0
  return [x0 + dx * t, y0 + dy * t]
}
// half the radius from the centre toward (mx, my), never past it
function toward(x, y, r, mx, my) {
  const d = Math.hypot(mx - x, my - y), t = Math.min(0.5 * r, d)
  return d > 1e-6 ? [x + (mx - x) * t / d, y + (my - y) * t / d] : [x, y]
}

// Every hit in the bundle: {idx, victim (player index, or 'fol:k' for a
// follower), kind, el (hitbox element), scale, x, y, turn}. Cached once
// every fighter's table is in (paint never waits: no sparks before that).
const cache = new WeakMap()
export function hitEvents(bundle) {
  let out = cache.get(bundle)
  if (out) return out
  if (!bundle?.frames?.x || !hitDataReady(bundle)) return []
  out = []
  const f = bundle.frames, n = bundle.meta?.n ?? f.x[0]?.length ?? 0
  // attackers: every leader and follower row
  const rows = f.x.map((_, i) => ({ i, cid: f.cid[i], st: f.state[i], age: f.age?.[i], x: f.x[i], y: f.y[i], dir: f.dir?.[i] }))
  for (const fo of f.fol || []) rows.push({ i: fo.of, cid: fo.cid, st: fo.state, age: fo.age, x: fo.x, y: fo.y, dir: fo.dir })
  // victims: every leader (key: its player index) and follower (key 'fol:k')
  // (`bubble`: the rows meleeRender.shieldAt reads, as paintFrame passes them)
  const victims = f.x.map((_, i) => ({ key: i, of: i, cid: f.cid[i], x: f.x[i], y: f.y[i], dir: f.dir?.[i], st: f.state[i], pct: f.pct?.[i],
    sh: f.shield?.[i], lag: f.hitlag?.[i], stun: f.hitstun?.[i], by: f.hitby?.[i],
    bubble: { state: f.state[i], joyx: f.joyx?.[i], joyy: f.joyy?.[i], lt: f.lt?.[i], dir: f.dir?.[i], shield: f.shield?.[i], age: f.age?.[i] } }))
  ;(f.fol || []).forEach((fo, k) => victims.push({ key: `fol:${k}`, of: fo.of, cid: fo.cid, x: fo.x, y: fo.y, dir: fo.dir, st: fo.state,
    pct: fo.pct, sh: fo.shield, lag: fo.hitlag, stun: fo.hitstun, by: fo.hitby,
    bubble: { state: fo.state, lt: f.lt?.[fo.of], dir: fo.dir, shield: fo.shield, age: fo.age } }))
  for (const V of victims) {
    const { pct, sh, st } = V
    if (!pct) continue
    for (let idx = 1; idx < n; idx++) {
      if (V.x[idx] == null || pct[idx] == null || pct[idx - 1] == null) continue
      const dmg = pct[idx] - pct[idx - 1]
      // a hit freezes the victim in hitlag; damage without it (off-screen
      // magnifier damage, a throw's release) spawns no spark
      const lag = V.lag ? V.lag[idx] > 0 : !f.hitlag
      let kind = null
      if (dmg > 0.001 && lag && !THROWN.has(st[idx - 1])) kind = 'hit'
      // (a hit that breaks the shield goes straight to ShieldBreakFly, 205, its
      // shield reset, in hitlag: RAM shows its shield-hit effect too)
      else if (sh && GUARDING.has(st[idx - 1]) && ((st[idx] === 181 && sh[idx - 1] - sh[idx] > 1) || st[idx] === 205) &&
        (!V.lag || V.lag[idx] > 0)) kind = 'shield'
      if (!kind) continue
      const mx = V.x[idx], my = V.y[idx] + MIDDLE
      // the hitbox that landed: the attacker's (Slippi's "last hit by" when
      // recorded), the one nearest the victim's middle; never the victim's own
      // side (Popo does not hit Nana)
      const by = V.by?.[idx]
      let best = null
      for (const a of rows) {
        if (a.i === V.of || (by != null && by >= 0 && by !== V.of && a.i !== by) || a.x[idx] == null) continue
        for (const s of spheres(a.cid[idx], a.st, a.age, a.x, a.y, a.dir, idx)) {
          const d = Math.hypot(s.x - mx, s.y - my) - s.r
          if (!best || d < best.d) best = { ...s, d }
        }
      }
      if (!best || best.d > NEAR_ITEM) {
        // a projectile or thrown item: the nearest live item (its owner's,
        // when Slippi says who hit). Its hitbox swept from where it was a
        // frame before to where it is (or to where it was last, gone on the
        // hit): the point of that path nearest the victim's middle
        for (const it of bundle.items || []) {
          const k = Math.min(idx - it.f, it.x.length - 1)
          if (k < 0 || idx - it.f > it.x.length) continue
          const owner = itemOwner(bundle, it, k)
          if (by != null && by >= 0 && owner >= 0 && owner !== by) continue
          const [x0, y0] = k > 0 ? [it.x[k - 1], it.y[k - 1]] : [it.x[k], it.y[k]]
          const [px, py] = closestOnSegment(x0, y0, it.x[k], it.y[k], mx, my)
          const r = ITEM_SIZES[it.t]?.[1] || 2
          const d = Math.hypot(px - mx, py - my) - r
          if (d < NEAR_ITEM && (!best || d < best.d)) best = { x: px, y: py, r, el: ITEM_ELEMENTS[it.t] ?? 0, d }
        }
      }
      if (best && best.d > NEAR_ITEM) best = null
      let el = best ? best.el : 0, x = mx, y = my
      if (best) [x, y] = toward(best.x, best.y, best.r, mx, my)
      else {
        // nothing to go by (a laser: Slippi records the blaster, not its
        // shots; a stage hazard): the victim's side facing who hit it (Slippi's
        // "last hit by", else the only other player)
        const others = f.x.map((_, i) => i).filter(i => i !== V.of)
        const a = by != null && by >= 0 && by !== V.of ? by : others.length === 1 ? others[0] : -1
        const ax = a >= 0 ? f.x[a][idx] : null
        if (ax != null) x = mx + Math.sign(ax - mx) * Math.min(SIDE, Math.abs(ax - mx) / 2)
      }
      if (kind === 'shield' && best) {
        // on the bubble, facing the hitbox (the shield is the "hurtbox" here):
        // the bubble as it was when the hit landed, the frame before
        const b = shieldAt(V.cid[idx - 1], V.bubble, idx - 1)
        if (b) {
          const bx = V.x[idx - 1] + b.dx, by2 = V.y[idx - 1] + b.dy, d = Math.hypot(best.x - bx, best.y - by2)
          if (d > 1e-6) { x = bx + (best.x - bx) * b.r / d; y = by2 + (best.y - by2) * b.r / d }
        }
      }
      let fx, scale = 1
      if (kind === 'shield') fx = 'shield'
      else {
        fx = EFFECT[el]
        if (!fx) continue
        if (fx === 'normal') {
          if ((V.stun?.[idx] ?? 0) >= STRONG_HITSTUN) fx = 'strong'
          else scale = Math.max(0.3, Math.min(1.5, 0.3 + 0.04 * Math.floor(dmg + 1e-4)))
        }
      }
      if (!FX.effects[fx]) fx = 'normal'
      // the slash model's random turn (efAsync_Dispatch 0x3EC): any angle;
      // seeded from the frame so a seek paints what playing did
      const turn = ((idx * 2654435761 + (V.of + 1) * 40503) >>> 0) % 360 * Math.PI / 180
      out.push({ idx, victim: V.key, kind: fx, el, scale, x, y, turn, dmg, facing: (V.dir?.[idx] ?? 1) < 0 ? -1 : 1 })
    }
  }
  // Shy Guys: a hit knocks one off (state 2) or makes it flinch (3). The game
  // spawns the element's effect at the contact on the item (itcoll.c, table
  // it_803F1384; items have no hard-hit variant): the hitbox that landed is
  // the one nearest the Shy Guy, the contact on its hurtbox facing it
  for (const it of bundle.items || []) {
    if (it.t !== SHY_GUY || !it.s) continue
    for (let k = 1; k < it.s.length; k++) {
      if (it.s[k] === it.s[k - 1] || !SHY_HIT.has(it.s[k])) continue
      const idx = it.f + k, mx = it.x[k], my = it.y[k]
      let best = null
      for (const a of rows) {
        if (a.x[idx] == null) continue
        for (const sp of spheres(a.cid[idx], a.st, a.age, a.x, a.y, a.dir, idx)) {
          const d = Math.hypot(sp.x - mx, sp.y - my) - sp.r
          if (!best || d < best.d) best = { ...sp, d }
        }
      }
      if (best && best.d > NEAR_ITEM) best = null
      const el = best ? best.el : 0
      let fx = EFFECT[el]
      if (!fx) continue
      if (!FX.effects[fx]) fx = 'normal'
      const [x, y] = best ? toward(mx, my, 2 * SHY_HURT, best.x, best.y) : [mx, my]
      const turn = ((idx * 2654435761 + (k + 7) * 40503) >>> 0) % 360 * Math.PI / 180
      out.push({ idx, victim: `item:${it.f}`, kind: fx, el, scale: fx === 'normal' ? ITEM_HIT_SCALE : 1,
        x, y, turn, dmg: null, facing: (it.d?.[k] ?? 1) < 0 ? -1 : 1 })
    }
  }
  out.sort((a, b) => a.idx - b.idx)
  cache.set(bundle, out)
  return out
}

// ---------------------------------------------------------------- drawing
const hex = (s) => [0, 2, 4, 6].map((i) => (i < s.length ? parseInt(s.slice(i, i + 2), 16) : 255))
const PARSED = new WeakMap(), RINGS = new WeakMap()
// the effects drawn with our own shapes (sparkArt) rather than the game's
// traced textures: a hit on a shield, and a tech's rays and flash
const OWN = new Set(['shield', 'tech'])
// [prim rgba, env rgb] by an effect's colour index, parsed once
function colours(fx, i) {
  let list = PARSED.get(fx)
  if (!list) { list = fx.colours.map(([prim, env]) => [hex(prim), hex(env)]); PARSED.set(fx, list) }
  return list[i]
}
// a ring's points, from [x0, y0, dx1, dy1, ...], decoded once
function ringPoints(region) {
  let out = RINGS.get(region)
  if (!out) {
    out = region.at(-1).map((flat) => {
      const pts = [[flat[0], flat[1]]]
      for (let i = 2; i < flat.length; i += 2) pts.push([pts.at(-1)[0] + flat[i], pts.at(-1)[1] + flat[i + 1]])
      return pts
    })
    RINGS.set(region, out)
  }
  return out
}
// A particle: its texture's alpha and light maps in a square of half size
// `half`, turned, coloured env + (prim - env) x intensity at prim alpha x the
// texture's alpha, additive or not (psdisp.c). A Trail particle stretches back
// to its tail. The colour is painted exactly as min(prim, env) over the alpha,
// plus (prim - min) x intensity x alpha and (env - min) x (1 - intensity) x
// alpha of added light, so each map is filled in a single colour. Untraced
// (`own`: a shield hit, a tech's rays): our own drawing of the texture.
function drawParticle(ctx, fx, p, ox, oy, s, m, view, dpr, own, cut) {
  const tex = FX.textures[p[0]]
  if (!tex) return
  const [prim, env] = colours(fx, p[5])
  // m = -1: the effect mirrored left to right (turned by the victim's facing)
  let cx = ox + m * p[1] * s, cy = oy + p[2] * s, hw = p[3] * s, hh = hw, fade = 1
  const tail = p[7]
  if (tail) {
    const tx = m * tail[0] * s, ty = tail[1] * s, len = Math.hypot(tx, ty)
    cx += tx / 2; cy += ty / 2; hh += len / 2; fade = (1 + tail[2]) / 2
  }
  // ring points are hundredths of the half size
  const a = m * p[4] * Math.PI / 180, c = Math.cos(a), sn = Math.sin(a), S = view.S * 0.01
  ctx.setTransform(dpr * S * c * hw, -dpr * S * sn * hw, -dpr * S * sn * hh, -dpr * S * c * hh,
    dpr * (view.ox + view.S * cx), dpr * (view.oy - view.S * cy))
  if (own || !tex[3]) drawArt(ctx, tex, prim, env, prim[3] / 255 * fade, !!p[6])
  else paintTexture(ctx, tex[3], prim, env, prim[3] / 255 * fade, !!p[6], cut)
}
// A traced texture's regions (data/hitEffects.js) in the current transform
// (the square -100..100), coloured env + (prim - env) x intensity at alpha `pa`
// x the texture's, added when `additive`, blended over otherwise.
export function paintTexture(ctx, regions, prim, env, pa, additive, cut = CUT) {
  const lo = [0, 1, 2].map(j => Math.min(prim[j], env[j]))
  const up = [0, 1, 2].map(j => prim[j] - lo[j]), dn = [0, 1, 2].map(j => env[j] - lo[j])
  paintMap(ctx, regions, ALPHA, lo, pa, !additive, cut)
  if (up.some(v => v > 0)) paintMap(ctx, regions, regions.some(r => r[0] === 1) ? OWN_LIGHT : LIGHT, up, pa, false, cut)
  if (dn.some(v => v > 0)) paintMap(ctx, regions, DARK, dn, pa, false, cut)
}
// Which map paintMap fills: the alpha, the light (on the alpha's outlines or
// its own) or the alpha less the light.
const ALPHA = 0, LIGHT = 1, OWN_LIGHT = 2, DARK = 3
// How much of a traced texture's faint light is cut off: [glow, outlines]. Its
// faint parts vanish over the game's bright stages but read as a large halo on
// Watch Lite's dark background, which made the sparks look massive: most of a
// glow's tail, a little of the faintest outlines. Electric's glow and sparkles
// sit inside the victim, whose body hides most of them in game (Watch Lite
// draws them on top): its faint blue and purple light is cut harder.
const CUT = [0.3, 0.05]
const CUTS = { electric: [0.55, 0.2] }
const floor = (v, f) => Math.max(0, (v - f) / (1 - f))
// One map in one colour: its glow gradient, then its nested outlines. The
// alpha's outlines are drawn over what is under them (alpha blending); the
// light's add.
function paintMap(ctx, regions, which, rgb, pa, over, cut = CUT) {
  ctx.globalCompositeOperation = over ? 'source-over' : 'lighter'
  const col = `${rgb[0] | 0},${rgb[1] | 0},${rgb[2] | 0}`
  for (const r of regions) {
    if (r[0] === 2) {
      if (!ctx.createRadialGradient) continue
      const st = r[1], rmax = st[st.length - 3] || 1
      const g = ctx.createRadialGradient(0, 0, 0, 0, 0, rmax)
      for (let i = 0; i < st.length; i += 3) {
        const v = which === ALPHA ? st[i + 1] : which === DARK ? st[i + 1] - st[i + 2] : st[i + 2]
        g.addColorStop(st[i] / rmax, `rgba(${col},${Math.min(1, floor(pa * v, cut[0]))})`)
      }
      ctx.globalAlpha = 1
      ctx.fillStyle = g
      ctx.fillRect(-100, -100, 200, 200)
      continue
    }
    let alpha
    if (r[0] === 0 && which === ALPHA) {
      // brings its pixels from `under` to `A` (both scaled by the particle's alpha)
      const den = 1 - floor(pa * r[2], cut[1])
      alpha = den <= 0.001 ? 1 : 1 - (1 - floor(pa * r[1], cut[1])) / den
    } else if (r[0] === 0 && (which === LIGHT || which === DARK)) alpha = floor(pa * r[which === LIGHT ? 3 : 4], cut[1])
    else if (r[0] === 1 && which === OWN_LIGHT) alpha = floor(pa * r[1], cut[1])
    else continue
    if (!(alpha >= 0.004)) continue
    ctx.globalAlpha = Math.min(1, alpha)
    ctx.fillStyle = `rgb(${col})`
    ctx.beginPath()
    for (const ring of ringPoints(r)) {
      ring.forEach(([u, v], i) => (i ? ctx.lineTo(u, v) : ctx.moveTo(u, v)))
      ctx.closePath()
    }
    ctx.fill('evenodd')
  }
}

// The slash model's two crescents (EfCoData model 8), additive light, turned.
function drawCrescents(ctx, k, ox, oy, turn, view, dpr) {
  const row = FX.slash?.[k]
  if (!row) return
  const c = Math.cos(turn), sn = Math.sin(turn), S = view.S
  ctx.setTransform(dpr * S * c, -dpr * S * sn, -dpr * S * sn, -dpr * S * c, dpr * (view.ox + S * ox), dpr * (view.oy - S * oy))
  ctx.globalCompositeOperation = 'lighter'
  ctx.globalAlpha = 1
  for (const [outer, core, outerLight, coreLight] of row) {
    // the light each adds, as the model's additive render measured it
    for (const [ring, colour] of [[outer, outerLight], [core, coreLight]]) {
      if (ring.length < 3) continue
      ctx.fillStyle = colour
      ctx.beginPath()
      ring.forEach(([u, v], i) => (i ? ctx.lineTo(u, v) : ctx.moveTo(u, v)))
      ctx.closePath(); ctx.fill()
    }
  }
}

// Every spark alive on idx, after the fighters (the game draws particles last).
export function drawHitSparks(ctx, bundle, idx, view, dpr) {
  const events = hitEvents(bundle)
  if (!events.length) return
  ctx.save()
  for (const ev of events) {
    if (ev.idx > idx) break
    drawHitEffect(ctx, ev, idx - ev.idx, view, dpr)
  }
  ctx.restore()
  ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}

// One hit's effect `k` frames after it lands ({kind, x, y, scale, facing, turn}
// as hitEvents gives them). Leaves the context's transform, alpha and blend set.
export function drawHitEffect(ctx, ev, k, view, dpr) {
  const fx = FX.effects[ev.kind]
  if (!fx || k < 0 || k >= fx.frames.length) return
  const s = fx.scaled ? ev.scale : 1, m = fx.facing && ev.facing && fx.facing !== ev.facing ? -1 : 1
  if (ev.kind === 'slash') drawCrescents(ctx, k, ev.x, ev.y, ev.turn, view, dpr)
  const own = OWN.has(ev.kind), cut = CUTS[ev.kind] || CUT
  for (const p of fx.frames[k]) drawParticle(ctx, fx, p, ev.x, ev.y, s, m, view, dpr, own, cut)
}

// Shield stun's torn bubble (EfCoData model 13, effect 1049, spawned as
// shield stun begins, ftCo_80092F2C): for its first frames the game shows the
// bubble cut into thin horizontal strips, a band or two of them stretched
// sideways past the rim and sliding apart, and on alternate frames a white
// scribble over it, then the plain bubble again. Ours: as many strips, the
// bands where the game's are and reaching as far (from the game's model); each
// strip's stretch and nudge in them are our own pick.
// On a fighter row in shield stun (state 181): [outline, scribble] for the
// frames since its shield was last hit, or null once the bubble is plain. The
// outline is drawn instead of the bubble's disc (meleeRender shield's `shape`:
// rings in hundredths of the radius), the scribble over it (drawShieldScribble).
const TORN = new Map()
function tornBubble(k) {
  if (TORN.has(k)) return TORN.get(k)
  const st = FX.shieldStun, [bands, scribble] = st.frames[k], n = st.strips
  let seed = 1013 * (k + 1)
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
  const half = (y) => 100 * Math.sqrt(Math.max(0, 1 - (y / 100) ** 2))
  const rings = []
  for (let i = 0; i < n; i++) {
    const y0 = -100 + (200 * i) / n, y1 = -100 + (200 * (i + 1)) / n
    // in the band: stretched so its row reaches up to `reach` past the rim
    // (most in the band's middle), nudged a little either way
    const ym = (y0 + y1) / 200
    const band = bands.find(([mid, high]) => Math.abs(ym - mid) < high)
    let s = 1, d = 0
    if (band) {
      const [mid, high, reach] = band, t = 1 - Math.abs(ym - mid) / high
      const r = rand(), w = Math.max(half(y0), half(y1), 1)
      s = 1 + (reach * 100 / w) * (0.35 + 0.65 * t) * (0.6 + 0.4 * r)
      d = (rand() - 0.5) * 0.25 * reach * 100
    }
    const w0 = s * half(y0), w1 = s * half(y1)
    rings.push([-w0 + d, y0, 2 * w0, 0, w1 - w0, y1 - y0, -2 * w1, 0])
  }
  const out = [rings, scribble ? k + 1 : 0]
  TORN.set(k, out)
  return out
}
export function shieldStun(states, shield, idx) {
  const st = FX.shieldStun
  if (!st || states?.[idx] !== 181) return null
  let j = idx
  while (j > 0 && states[j - 1] === 181 && !(shield && shield[j - 1] - shield[j] > 1)) j--
  return idx - j < st.frames.length ? tornBubble(idx - j) : null
}
// the white scribble shield stun draws over the bubble on alternate frames
// (added light), around the bubble {cx, cy, r} meleeRender's shield drew: a
// white glow and a few quick zigzag strokes of our own
export function drawShieldScribble(ctx, scribble, b, view, dpr) {
  if (!scribble || !b) return
  const S = view.S
  ctx.save()
  ctx.setTransform(dpr * S * b.r / 100, 0, 0, -dpr * S * b.r / 100, dpr * (view.ox + S * b.cx), dpr * (view.oy - S * b.cy))
  ctx.globalCompositeOperation = 'lighter'
  ctx.globalAlpha = 1
  if (ctx.createRadialGradient) {
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, 92)
    g.addColorStop(0, 'rgba(255,255,255,0.75)'); g.addColorStop(0.7, 'rgba(255,255,255,0.45)'); g.addColorStop(1, 'rgba(255,255,255,0)')
    ctx.fillStyle = g
    ctx.beginPath(); ctx.arc(0, 0, 92, 0, 7); ctx.fill()
  }
  let seed = 7919 * scribble
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
  ctx.strokeStyle = 'rgba(255,255,255,0.9)'; ctx.lineWidth = 5; ctx.lineJoin = 'round'
  ctx.beginPath()
  for (let s = 0; s < 4; s++) {
    let x = -70 + 30 * rand(), y = -60 + 120 * rand()
    ctx.moveTo(x, y)
    for (let i = 0; i < 5; i++) { x += 22 + 10 * rand(); y += (rand() - 0.5) * 50; ctx.lineTo(x, Math.max(-80, Math.min(80, y))) }
  }
  ctx.stroke()
  ctx.restore()
  ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
}

// The victim's hitlag shake (ftCo_DamageFall.c ftCo_80090594 / ftCo_80090690):
// for 1.3 x hitlag frames (PlCo ftCommonData +0x168) the model steps through a
// pattern (PlCo common data [9]): in the air up and down, on the ground along
// the facing, electric its own zap. Returns [dx, dy] or null.
export function hitShake(bundle, victim, idx) {
  const events = hitEvents(bundle)
  let ev = null
  for (const e of events) {
    if (e.idx > idx) break
    if (e.victim === victim && e.kind !== 'shield') ev = e
  }
  // a cape's hit sets no shake (ftCo_80090594 skips element 10)
  if (!ev || !FX.shake || ev.el === 10) return null
  const f = bundle.frames, k = idx - ev.idx
  const row = typeof victim === 'number' ? { lag: f.hitlag?.[victim], air: f.air?.[victim], dir: f.dir?.[victim] }
    : (({ hitlag, air, dir }) => ({ lag: hitlag, air, dir }))(f.fol?.[Number(victim.slice(4))] || {})
  const hitlag = row.lag?.[ev.idx]
  if (!(hitlag > 0)) return null
  const frames = Math.floor(FX.shake.mul * hitlag + FX.shake.add)
  if (k >= frames) return null
  // the element decides the electric zap, and where the victim was when it was hit air or ground
  const type = ev.kind === 'electric' ? 2 : row.air?.[ev.idx - 1] ? 0 : 1
  const pat = FX.shake.patterns[type]
  const [x, y] = pat[k % pat.length]
  return [type === 1 ? x * (row.dir?.[ev.idx] || 1) : x, y]
}
