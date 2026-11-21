// Invincibility (melee decomp ftcoll.c, ft_0D4D.c): whenever the game makes a
// fighter intangible or invincible for a while (ftColl_8007B760, 8007B7A4) it
// sets a timer: grabbing a ledge, a wall tech, tumbling into a wall or ceiling
// or bouncing off the ground, every throw (for the thrower), climbing out of
// the ground, leaving Yoshi's egg and leaving the respawn platform, each with
// its own length (data/koEffects.js flash.enter, flash.leave: the action state
// entered or left -> frames). A new one restarts it; the longer timer wins. On
// the respawn platform (Rebirth 12, RebirthWait 13) the fighter is invincible
// throughout. A fighter holding an input as Rebirth ends drops in the frame
// RebirthWait begins, so the replay goes from Rebirth straight to falling:
// leaving Rebirth starts the same 120 frames as leaving RebirthWait.
// The game flickers the model white meanwhile (colour animations 9 and 10).
// On Watch Lite's flat, bright silhouettes a flicker was hard to see, so Watch
// Lite outlines the fighter instead, steadily, for as long as it lasts, and
// keeps the fill the player's own colour (owner's call).
import KO from './data/koEffects.js'

const F = KO.flash
const REBIRTH = 12, REBIRTH_WAIT = 13

// the outline: its colour and its width in screen pixels, outside the
// silhouette. White reads on all four port colours against the dark stage, on
// the desktop and at the phone's size; a light cyan was lost on blue fighters,
// and 2 px was faint at the phone's size.
export const OUTLINE = { colour: '#ffffff', px: 3 }

// 1 on every frame of a fighter row (its action states) the fighter is
// invincible, else 0. Computed once per row.
const ROWS = new WeakMap()
function invincibleRow(states) {
  let out = ROWS.get(states)
  if (out) return out
  out = new Uint8Array(states.length)
  let timer = 0
  for (let t = 0; t < states.length; t++) {
    const s = states[t], prev = t ? states[t - 1] : s
    if (s === REBIRTH || s === REBIRTH_WAIT) { timer = 0; out[t] = 1; continue }
    if (s == null || s < REBIRTH) { timer = 0; continue }                    // dead or asleep
    if (timer) timer--
    const trigger = s !== prev ? (F.enter[s] || F.leave[prev]) : 0
    if (trigger) timer = Math.max(timer, trigger)
    if (timer) out[t] = 1
  }
  ROWS.set(states, out)
  return out
}

// Is the fighter of this row invincible (or intangible) on idx?
export function invincibleAt(states, idx) {
  return !!states && states[idx] != null && invincibleRow(states)[idx] === 1
}

// The outline to draw around the fighter on idx ({colour, px}), or null.
export function invincibleOutline(states, idx) {
  return invincibleAt(states, idx) ? OUTLINE : null
}
