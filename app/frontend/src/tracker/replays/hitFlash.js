// The victim's body flash: the colour a hit blends the victim's model to (melee
// decomp). A hit that puts the victim in a damage state starts a colour
// animation (ftCo_Damage.c ftCo_8008DA4C, argument order from the asm at
// 8008E1BC): fire 11, electric 15, ice 31, dark (element 13) 35, plus the
// knockback class; any other element 4. The class is the hitstun (0.4 x the
// knockback) below data/hitFlash.js `classes`: 0, 1, 2, else 3, and always 3
// for a hit while lying down (ftCo_8009F184 passes the damage code a motion).
// - The animations are PlCo.dat's scripts, stepped by the game's interpreter
//   rule (tools/liteaudit/hit_flash/build.py): normal white at alpha 170 fading
//   to 20 over 7 frames; fire orange and red pulses, then dark red; electric
//   blue and white on alternate frames; ice one blue and one white frame;
//   dark purples. Fire, electric and dark repeat 4 to 24 times by class.
// - Timing, read in RAM (playback Dolphin, Fighter +0x408): one step on the hit
//   frame, then one a frame (hitlag too, fighter.c Fighter_8006A360) and one
//   more on each frame the victim changes state (Fighter_ChangeMotionState
//   steps it as well), except into the states entered without their animation
//   (Ft_MF_SkipAnim: shielding, held in a grab).
// - The model's material is blended to the colour by its alpha (ftmaterial.c
//   ftMaterial_800BF6BC: a TEV stage model x (1 - a) + colour x a), so the
//   silhouette's fill is blended the same way (flashFill).
// A throw's release goes through the same damage entry (ftCo_Thrown.c
// ftCo_800DE7C0 -> ftCo_8008DCE0; an upward throw passes motion 90, class 3):
// the victim flashes as from a normal hit, a step ahead (RAM: two steps on the
// release frame, the throw being run before the victim's own update).
// hitEvents leaves throws out (they spawn no spark), so they are found here.
// The fire, electric and dark scripts also spawn small particles on the body
// (effects 1042-1046); those are not drawn.
import FLASH from './data/hitFlash.js'
import { hitEvents } from './hitSparks.js'

const BASE = { 1: 11, 2: 15, 5: 31, 13: 35 }
const DOWN_DAMAGE = new Set([185, 193])
const THROWN = new Set([239, 240, 241, 242, 243])
// GuardOn, Guard, GuardReflect; CapturePulled, CaptureWait, CaptureDamage (Hi, Lw)
const NO_STEP = new Set([178, 179, 182, 223, 224, 225, 226, 227, 228])
const DIGITS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
// The darkness animations also turn on the overlay's light (data `lights`):
// the game lights the fighter by it in place of part of the stage's lights
// (ftCo_09F4.c ftCo_8009F5AC). Measured on game frames (Falco and Fox, 28
// frames 14-27 after a darkness hit, the body's pixels against before the
// hit, the overlay taken out): the body shows 0.51 of its brightness (0.52,
// 0.56, 0.44 in red, green, blue), no added purple. A silhouette has no
// surfaces to light: its fill is dimmed by that much.
const LIGHT_DIM = 0.5

// the colour animation a hit starts: its element, the victim's hitstun and state on the hit frame
export function flashAnim(el, hitstun, state) {
  const base = BASE[el]
  if (base == null) return 4
  let cls = FLASH.classes.findIndex(c => (hitstun ?? 0) < c)
  if (cls < 0 || DOWN_DAMAGE.has(state)) cls = 3
  return base + cls
}

// a victim's rows: a leader by player index, a follower as 'fol:k' (hitEvents' keys)
function rows(bundle, victim) {
  const f = bundle.frames
  if (typeof victim === 'number') return { st: f.state?.[victim], stun: f.hitstun?.[victim], pct: f.pct?.[victim] }
  const fo = f.fol?.[Number(String(victim).slice(4))]
  return fo ? { st: fo.state, stun: fo.hitstun, pct: fo.pct } : null
}

// each victim's hits, by frame
const cache = new WeakMap()
function hitsBy(bundle) {
  let out = cache.get(bundle)
  if (out) return out
  const events = hitEvents(bundle)
  out = new Map()
  const add = (victim, ev) => { if (!out.has(victim)) out.set(victim, []); out.get(victim).push(ev) }
  for (const ev of events) {
    if (ev.kind === 'shield' || String(ev.victim).startsWith('item:')) continue
    add(ev.victim, ev)
  }
  // throw releases: the percent rises as the victim leaves a thrown state
  const f = bundle.frames
  for (const victim of [...(f.x || []).keys(), ...(f.fol || []).map((_, k) => `fol:${k}`)]) {
    const R = rows(bundle, victim)
    if (!R?.st || !R.pct) continue
    for (let idx = 1; idx < R.st.length; idx++) {
      if (THROWN.has(R.st[idx - 1]) && !THROWN.has(R.st[idx]) && R.pct[idx] - R.pct[idx - 1] > 0.001) add(victim, { idx, el: 0, first: 2 })
    }
  }
  for (const list of out.values()) list.sort((a, b) => a.idx - b.idx)
  // hitEvents is empty until the hit tables are in: cache only a real answer
  if (events.length) cache.set(bundle, out)
  return out
}

// The animation running on `victim` at idx and how many steps in: {id, steps}, or null.
function running(bundle, victim, idx) {
  const list = hitsBy(bundle).get(victim)
  if (!list) return null
  let ev = null
  for (const e of list) {
    if (e.idx > idx) break
    ev = e
  }
  const R = ev && rows(bundle, victim)
  if (!R?.st) return null
  const id = flashAnim(ev.el, R.stun?.[ev.idx], R.st[ev.idx])
  const anim = FLASH.anims[id]
  if (!anim) return null
  let steps = idx - ev.idx + (ev.first || 1)
  for (let j = ev.idx + 1; j <= idx && steps <= anim.length; j++) if (R.st[j] !== R.st[j - 1] && !NO_STEP.has(R.st[j])) steps++
  return steps <= anim.length ? { id, steps } : null
}
const rgbOf = (c) => [0, 2, 4, 6].slice(0, c.length / 2).map(i => parseInt(c.slice(i, i + 2), 16))

// The overlay on `victim` at idx: [r, g, b, a] (0-255), or null.
export function bodyFlash(bundle, victim, idx) {
  const run = running(bundle, victim, idx)
  const ch = run ? FLASH.anims[run.id][run.steps - 1] : '.'
  return ch === '.' ? null : rgbOf(FLASH.palette[DIGITS.indexOf(ch)])
}

// The light the darkness animations turn on, on `victim` at idx: [r, g, b], or null.
export function flashLight(bundle, victim, idx) {
  const run = running(bundle, victim, idx)
  const light = run && FLASH.lights?.[run.id]
  return light ? rgbOf(light) : null
}

// The fighter's fill on idx: its colour `col` ('#rrggbb') dimmed while the
// animation's light is on (LIGHT_DIM) and blended to the flash's colour by its
// alpha, or `col` itself.
export function flashFill(bundle, victim, idx, col) {
  if (typeof col !== 'string' || !/^#[0-9a-f]{6}$/i.test(col)) return col
  const fl = bodyFlash(bundle, victim, idx), light = flashLight(bundle, victim, idx)
  if (!fl && !light) return col
  const a = fl ? fl[3] / 255 : 0
  const mix = [1, 3, 5].map((i, j) => {
    const lit = parseInt(col.slice(i, i + 2), 16) * (light ? LIGHT_DIM : 1)
    return Math.round(lit * (1 - a) + (fl ? fl[j] : 0) * a)
  })
  return '#' + mix.map(v => v.toString(16).padStart(2, '0')).join('')
}
