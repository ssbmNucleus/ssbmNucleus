// meleeRender — draw a Melee character silhouette on a 2D canvas from
// slippilab's animation data (MIT, frankborden/slippilab). Shared by the
// Watch Lite clip player. See backend/tracker/tools/RENDERER.md.
//
// charmaps { actionNameById:[...], chars:{ <internalId>:{ scale, animationMap,
//            specialsMap } } }
// animData { <internalId>: { <animName>: [ svgPathString per frame ] } }
import MOTION_NAMES from "./data/motionNames.js";
// The animation the game itself plays where the charmaps choice differs or is
// missing: state -> submotion value -> the fighter's own Pl*.dat action table
// (tools/liteaudit/game_motions.py). Tried before anything else.
import GAME_MOTIONS from "./data/gameMotions.js";
import SHIELD from "./data/shieldTable.js";
import { METRICS, eggOutline, koopaShellPts, koopaShellFrames, drawEggShell } from "./itemArt.js";

// slippilab's geometry has no animation for some (character, action) pairs
// the game really uses. Measured on 2.6 M vanilla fighter-frames, 0.64% fell
// back to a dot: mostly the victim of a throw (Thrown*, whose pose the
// thrower's animation drives in game), Yoshi's shield (Guard), Jigglypuff's
// crouch (SquatWait, stored as SquatWait1) and grab specials (CaptureCaptain,
// YoshiEgg). A close pose that every zip has beats a dot popping in mid-throw.
// `hold` draws the fallback's last frame instead of looping it.
//
// Then, measured on the owner's 25k replays (266 M drawn fighter-frames, 0.07%
// still dots), two kinds of gap:
// - the game plays an animation the zips DO have, under another name. The
//   decomp's motion tables name it: ft/ftmotionstates.c for common states
//   (GAME_ANIM below) and each fighter's table for its specials
//   (data/motionNames.js, tools/liteaudit/motion_names.py).
// - the zips lack it: the closest pose every zip has (standIns).
const GAME_ANIM = {
  FlyReflectCeil: "StopCeil",      // tumbling into a ceiling
  DownReflect: "WallDamage",       // tumbling bounce off the ground
  DamageBind: "FuraFura",          // Mewtwo's Disable
  DamageSong: "FuraSleepStart",    // Jigglypuff's Sing
  DamageSongWait: "FuraSleepLoop",
  DamageSongRv: "FuraSleepEnd",
  BuryJump: "JumpF",               // climbing out of the ground
  LiftWalk1: "HeavyWalk1",         // walking under a crate or barrel
  LiftWalk2: "HeavyWalk2",
};
function standIns(name) {
  // carried on Donkey Kong's shoulder: a held victim, like a grab
  if (name.startsWith("Shouldered")) return ["CaptureWaitHi"];
  if (name === "ShieldBreakFly") return ["DamageFlyHi"];
  if (name.startsWith("ItemParasol")) return ["Fall"];
  if (name === "HeavyGet") return ["LightGet"];
  if (name.startsWith("LiftWalk") || name.startsWith("HeavyWalk")) return ["WalkSlow"];
  if (name === "LiftTurn") return ["Turn"];
  let m = /^Heavy(Throw[A-Za-z]+?)4?$/.exec(name);
  if (m) return ["Light" + m[1], "LightThrowF"];
  // a swing of the bat, parasol, Lip's Stick, star rod or fan
  m = /^(?:Bat|Parasol|Lip[Ss]tick|StarRod|Harisen)Swing(\d)/.exec(name);
  if (m) return ["Swing" + m[1], "Swing1"];
  return [];
}
function fallbackFor(name) {
  if (!name) return null;
  if (name === "SquatWait") return { name: "SquatWait1" };
  if (name === "Guard" || name === "GuardDamage") return { name: "GuardOn", hold: true };
  if (name.startsWith("Thrown")) return { name: "DamageFlyN" };
  if (name.startsWith("Capture") || name === "YoshiEgg") return { name: "CaptureWaitHi" };
  if (GAME_ANIM[name]) return { name: GAME_ANIM[name], names: [GAME_ANIM[name], ...standIns(GAME_ANIM[name])] };
  const names = standIns(name);
  return names.length ? { name: names[0], names } : null;
}

// Action states in which the game hides the fighter's model (fp->invisible
// set on entry): in a barrel (ftCo_Barrel/BarrelWait), swallowed by Kirby
// (CaptureWaitKirby) or by Yoshi (CaptureKirbyYoshi), and mid Vanish / Farore's
// Wind / Teleport (Sheik 356/359, Zelda 350/353, Mewtwo 354/357). Nothing is
// drawn, as in game.
const HIDDEN_STATES = new Set([289, 293, 331, 340]);
// In Yoshi's egg (YoshiEgg 277, Kirby's copy KirbyYoshiEgg 332) the fighter is
// hidden too, and the game draws the egg (drawn here as our own egg at the
// model's size, itemArt.eggOutline): PlYs.dat ftData+0x48 entry 3, pinned
// to the victim's TransN (the recorded x,y; YoshiEgg has no animation), its
// bottom there, scaled by the VICTIM's egg size (ftCo_DatAttrs +0xBC) times
// 0.55 + 0.45 x min(frames in the egg, 20) / 20 (Yoshi attributes x1C/x20): it
// swells over its first 20 frames. Checked in playback Dolphin, airborne and
// resting (a resting egg's bottom is on the floor).
const EGG_STATES = new Set([277, 332]);
function drawEgg(ctx, o) {
  const size = METRICS.egg.sizes[o.cid] || 2;
  let k = 1;                          // its first frame counts 1 (RAM, round 7)
  if (o.states && o.idx != null) while (k < 20 && o.idx - k >= 0 && EGG_STATES.has(o.states[o.idx - k])) k++;
  const [x1c, x20] = METRICS.egg.grow, s = size * (1 - x1c + x1c * Math.min(k, x20) / x20);
  const S = o.view.S * o.dpr;
  ctx.save();
  ctx.setTransform(S, 0, 0, -S, o.view.ox * o.dpr, o.view.oy * o.dpr);
  ctx.beginPath();
  eggOutline().forEach(([px, py], i) => i ? ctx.lineTo(o.x + px * s, o.y + py * s) : ctx.moveTo(o.x + px * s, o.y + py * s));
  ctx.closePath();
  ctx.fillStyle = "#dcdccc"; ctx.fill();
  ctx.lineWidth = 2 / o.view.S; ctx.strokeStyle = o.fill || "#aab4cc"; ctx.stroke();
  ctx.fillStyle = "#22a820";
  for (const [sx, sy, sr] of [[-1.3, 3.6, 0.75], [1.2, 2.2, 0.85], [0.6, 4.9, 0.5]]) {
    ctx.beginPath(); ctx.arc(o.x + sx * s, o.y + sy * s, sr * s, 0, 7); ctx.fill();
  }
  ctx.restore();
}
// Yoshi's shield: in GuardHold (342) and GuardDamage (344) the game swaps his
// model part 0 for the egg (ftYs_Guard.c, ftParts_80074B0C(gobj, 0, 1)), so he
// is an egg, not a bubble: drawn as our egg instead of his pose, twice his
// shield size tall around his shield bone (shieldTable.js chars 14: s, g). The
// egg does not shrink with shield health. GuardOn (341, 345) and GuardOff
// (343) show Yoshi himself.
const YOSHI_EGG_SHIELD = new Set([342, 344]);
function drawEggShield(ctx, o) {
  const e = SHIELD.chars["14"], h = 2 * e.s, f = o.facing || 1;
  const wx = (v) => o.view.ox + v * o.view.S, wy = (v) => o.view.oy - v * o.view.S;
  ctx.save();
  ctx.setTransform(o.dpr, 0, 0, o.dpr, 0, 0);
  drawEggShell(ctx, o.x + e.g[0] * f, o.y + e.g[1], h / METRICS.egg.h, h / 2, 0, f, wx, wy, o.fill || "#aab4cc");
  ctx.restore();
}
// Bowser's Whirling Fortress (SpecialHi 359, SpecialAirHi 360): from action
// frame 6 (7 in the air) to 50 the game swaps model part 0 to its shell-only
// variant (ftKp_SpecialN_80135780 -> ftParts_80074B0C, set by the move's
// script flags): head and limbs are hidden. The animation pack's outline still
// has them, so our own shell is drawn instead, in the box the shell model
// (PlKpNr.dat) fills on that frame, fighter-local with the model scale applied.
function koopaShell(o) {
  if (o.cid !== 5) return null;
  const w = koopaShellFrames(o.state);
  if (!w) return null;
  const i = Math.floor(o.age) - w.first;
  return i >= 0 && i < w.frames.length ? koopaShellPts(w.frames[i], i) : null;
}
function drawKoopaShell(ctx, o, shell) {
  const S = o.view.S * o.dpr, f = o.facing || 1;
  ctx.save();
  ctx.setTransform(S, 0, 0, -S, o.view.ox * o.dpr, o.view.oy * o.dpr);
  ctx.beginPath();
  shell.forEach(([px, py], i) => i ? ctx.lineTo(o.x + px * f, o.y + py) : ctx.moveTo(o.x + px * f, o.y + py));
  ctx.closePath();
  ctx.fillStyle = o.fill || "#aab4cc"; ctx.fill();
  ctx.restore();
}
// A thrown or carried victim (ThrownF..ThrownLwWomen 239-243, DK's cargo
// Shouldered*/ThrownF* 266-274) hangs from the thrower: ftCo_800DB368 pins the
// victim's XRotN joint to the thrower's throw bone, and Slippi records that pin
// minus the bind offset XRotN - TransN = (dz, h) (unscaled), so the pin is
// (x + facing dz, y + h). The game plays the thrower's own victim animation
// (not in the packs), which turns the victim to face the thrower. The stand-in
// pose is drawn the same way: facing the thrower, its XRotN (model (0, h),
// scaled) on the pin. Read from Pl*.dat and checked in RAM (round 7).
const PINNED = new Set([239, 240, 241, 242, 243, 266, 267, 268, 269, 270, 271, 272, 273, 274]);
const XROTN = {"0":[5.667,0],"1":[8.3,0],"2":[13.848,-0.488],"3":[13.431,0],"4":[5,0],"5":[15.525,0],"6":[8.552,0.226],"7":[8.241,0.347],"8":[5.004,0],"9":[9.4,0],"10":[5.004,0],"11":[5.004,0],"12":[5.8,0],"13":[13.848,-0.488],"14":[5.6,0],"15":[5,0],"16":[10.308,0.226],"17":[5.667,0],"18":[9.849,0.426],"19":[9.4,0],"20":[8.553,0.233],"21":[5.667,0],"22":[8.3,0],"23":[4.6,0],"24":[6.194,0],"25":[13.848,-0.488],"26":[9.849,0.426]};
const HIDDEN_SPECIALS = { 7: [356, 359], 19: [350, 353], 16: [354, 357] };
export function hiddenAt(cid, state) {
  return HIDDEN_STATES.has(state) || !!HIDDEN_SPECIALS[cid]?.includes(state);
}
// Common states with no animation of their own (decomp submotion None): the
// game keeps the pose it was in. Frozen in ice, buried, lifting a crate,
// growing or shrinking with a mushroom, held by a boss.
const KEEP_POSE = new Set([30, 31, 174, 177, 237, 278, 280, 283, 285, 294, 295, 301, 302,
  314, 315, 316, 317, 318, 319, 320, 321, 322, 324, 325, 327, 328, 329, 330, 333, 334,
  336, 337, 338, 339]);

// Fox's and Falco's reflector ("shine"). It is an effect, and Slippi records no
// effects, so the action state and its frame counter are the only signal. What
// is drawn follows the game's own effect models, not a shape picked by eye:
// ftFx_SpecialLw.c spawns efSync 1161 as the shine starts, 1160 while it is
// held and 1162 when it reflects, all on the HipN joint; efalt.c turns them
// into effects 3001/3000/3002, i.e. models 1, 0 and 2 of EfFxData.dat's
// effFoxDataTable (Falco shares Fox's bank; there is no EfFcData.dat).
// - Orientation: every hexagon in the three models has its corners at
//   30 + 60k degrees, a corner straight up and one straight down, flat sides
//   left and right. The effect follows HipN by POSITION only
//   (efLib_Create_Attach_Scale -> RObj type 1, no rotation) and its joints
//   are billboards, so it never turns with facing, lean or a turnaround.
// - Held (model 0): a hexagonal band, corners 8.2686 out, its hole half that
//   (4.1343): dark blue edges, light blue between. Its 6-frame looping
//   AnimJoint scales it; read in RAM (playback Dolphin) the first held frame
//   shows 0.422, then 0.751, 0.751, 1.0199, 1.0199, 0.422 and around again,
//   counted from the start of the hold (Turn keeps the effect running).
// - Start (model 1), by the action frame 1-3 (hitlag holds it): a light ring
//   (corners 7.651-8.433, fading to nothing at 3.651 and 12.783) scaled 0.5,
//   0.681, 0.844, and a white half hexagon (3 of its 6 triangles, corners
//   7.6, first sector 210 degrees) scaled 0.751, 0.845, 0.939 and turned
//   60 degrees a frame.
// - Reflect (model 2), action frames 1-11: a white half hexagon (first
//   sector 30 degrees), corners 12.09 x 0.6686 out, turned 60 degrees every
//   2 frames.
// Sizes are model units times the fighter's model scale (the effect copies the
// fighter's root scale: common attributes +0x8C, Fox 0.96, Falco 1.10). The
// centre is HipN, read in RAM per state and frame, in model units, x along
// facing; Falco's equal Fox's. States (internal ids 1 Fox, 22 Falco): Start,
// Loop, Hit and Turn, grounded 360/361/362/364 and aerial 365/366/367/369. The
// reflector is gone in End (363/368).
const REFLECTOR_SCALE = { 1: 0.96, 22: 1.1 };
const HELD = new Set([361, 364, 366, 369]);
const HELD_PULSE = [0.422, 0.751, 0.751, 1.0199, 1.0199, 0.422];
const HELD_R = 8.2686;
const HELD_CENTRE = { ground: [-1.27, 5.62], air: [-0.13, 7.3] };
const START_CENTRE = {
  360: [[-0.39, 7.2], [-0.87, 6.55], [-1.16, 5.91]],
  365: [[0.03, 7.91], [0.07, 7.51], [-0.03, 7.28]],
};
const START_RING = [0.5, 0.681, 0.844], START_HALF = [0.751, 0.845, 0.939];
const REFLECT_X = {
  362: [-2.52, -3.77, -3.53, -2.98, -2.31, -1.76, -1.52],
  367: [-1.21, -2.29, -2.09, -1.63, -1.07, -0.6, -0.41],
};
const REFLECT_Y = { 362: 5.62, 367: 7.19 };
const DEG = Math.PI / 180;
// Frames since this hold began (the held effect's own clock), counting back
// through Loop and Turn; null when the hold runs off the start of the rows.
export function heldFrames(states, idx) {
  if (!states || !HELD.has(states[idx])) return null;
  let k = idx;
  while (k > 0 && HELD.has(states[k - 1])) k--;
  return k === 0 ? null : idx - k;
}
// What the game shows at this frame, in world units around the fighter:
// { dx (along facing), dy, pieces: [{ shape, ... }] }, or null. Shapes:
// 'band' (r, hole), 'ring' (r, the light rim's inner/outer corners, fade
// radii), 'half' (r, from: first corner's angle in radians). Corners are at
// 30 + 60k degrees before any turn.
export function reflectorAt(cid, state, { age = 0, held = null } = {}) {
  const s = REFLECTOR_SCALE[cid];
  if (!s) return null;
  const frame = Math.max(1, Math.floor(age || 0));
  if (HELD.has(state)) {
    const k = held != null ? held : Math.max(0, Math.floor(age || 0));
    const [x, y] = state === 361 || state === 364 ? HELD_CENTRE.ground : HELD_CENTRE.air;
    const r = HELD_R * HELD_PULSE[k % 6] * s;
    return { dx: x * s, dy: y * s, pieces: [{ shape: 'band', r, hole: r / 2 }] };
  }
  if (state === 360 || state === 365) {
    const i = Math.min(frame, 3) - 1, [x, y] = START_CENTRE[state][i];
    const g = START_RING[i] * s;
    return { dx: x * s, dy: y * s, pieces: [
      { shape: 'ring', r: 8.433 * g, rim: 7.651 * g, fade: [3.651 * g, 12.783 * g] },
      { shape: 'half', r: 7.6 * START_HALF[i] * s, from: (210 + 60 * Math.min(frame, 3)) * DEG },
    ] };
  }
  if (state === 362 || state === 367) {
    if (!(age >= 1) || frame > 11) return null;   // spawned on action frame 1
    const xs = REFLECT_X[state], x = xs[Math.min(frame, xs.length) - 1];
    return { dx: x * s, dy: REFLECT_Y[state] * s, pieces: [
      { shape: 'half', r: 12.09 * 0.6686 * s, from: (30 + 60 * Math.floor(frame / 2)) * DEG },
    ] };
  }
  return null;
}

// The shield bubble, from the game's own data (round7/shield, ftCo_Guard.c):
// it sits on the fighter's shield bone (ft_data->x8->x11), which the game poses
// every frame by blending the guard pose with a per-fighter tilt animation
// sampled at a SMOOTHED stick angle (ftCo_80091BC4: angle and tilt each move
// halfway, PlCo x44C = 0.5, toward the stick per frame). SHIELD holds, per
// fighter, that bone's centre untilted, at full tilt every 5 degrees, during
// shieldstun by action frame, and the radius at full health (model scale x
// shield size). Size = r x ((1 - 0.15) x health / 60 x (1 - 0.5 x depth) + 0.15)
// (inlineB0, PlCo x260/x264/x2D4/x2D8). Checked against the bubble's effect
// object in RAM (playback Dolphin) to within 0.005 units. Yoshi's egg (states
// 341-345) is a different model and keeps its own rule. Returns {dx, dy, r} or
// null (no bubble: GuardOff and every non-guard state).
const GUARD_STATES = new Set([178, 179, 181, 182]);
function atan2Melee(y, x) {        // lb_8000D008
  if (x < 1e-5 && x > -1e-5) return y < 1e-5 && y > -1e-5 ? 0 : (Math.PI / 2) * (y < 0 ? -1 : 1);
  if (x > 0) return Math.atan(y / x);
  return (y < 0 ? -1 : 1) * (Math.PI - Math.atan(Math.abs(y / x)));
}
function rowAt(rows, t) {          // rows sampled at integer t, linear, clamped
  const i = Math.max(0, Math.min(rows.length - 2, Math.floor(t))), u = Math.max(0, Math.min(1, t - i));
  return [rows[i][0] + (rows[i + 1][0] - rows[i][0]) * u, rows[i][1] + (rows[i + 1][1] - rows[i][1]) * u];
}
export function shieldAt(cid, rows, idx) {
  const e = SHIELD.chars[String(cid)], C = SHIELD.common;
  const st = rows.state;
  if (!e || !e.tilt || !st || !GUARD_STATES.has(st[idx])) return null;
  // the smoothing has memory: replay this guard from just before it began
  let k0 = idx;
  while (k0 > 0 && idx - k0 < 600 && GUARD_STATES.has(st[k0 - 1])) k0--;
  let g = 0, m = 0, x0 = 0, old = 1, prev = k0 > 0 ? st[k0 - 1] : null;
  const ramp = s => s === 178 || s === 182;
  const smooth = k => {
    const jx = rows.joyx ? rows.joyx[k] || 0 : 0, jy = rows.joyy ? rows.joyy[k] || 0 : 0;
    let rad = atan2Melee(jy, jx * (rows.dir ? rows.dir[k] || 1 : 1));
    if (rad < 0) rad += 2 * Math.PI;
    const deg = Math.min(359, Math.max(0, rad * 180 / Math.PI));
    let d = deg - g;
    if (d > 180) d -= 360; else if (d < -180) d += 360;
    const s = d * C.x44C + g;
    g = s > 360 ? s - 360 : s < 0 ? s + 360 : s;
    m += C.x44C * (Math.min(1, Math.hypot(jx, jy)) - m);
  };
  for (let k = k0; k <= idx; k++) {
    const s = st[k];
    if (ramp(s) && !GUARD_STATES.has(prev)) { g = 0; m = 0; x0 = 0; old = 1; smooth(k); }
    else if (ramp(prev)) { x0++; smooth(k); old *= 1 - Math.min(1, x0 / e.n); }
    else if (prev === 179) { smooth(k); old = 0; }
    else if (prev === 181 && s === 179) { smooth(k); old = 0; }
    prev = s;
  }
  const s = st[idx], f = rows.dir ? rows.dir[idx] || 1 : 1;
  let c;
  if (s === 181) c = rowAt(e.dmg, Math.max(0, rows.age ? rows.age[idx] || 0 : 0));
  else {
    const t = rowAt(e.tilt, g / 5);
    c = [e.g[0] + (t[0] - e.g[0]) * m, e.g[1] + (t[1] - e.g[1]) * m];
    if (ramp(s) && old > 0) c = [c[0] + (e.on[0] - c[0]) * old, c[1] + (e.on[1] - c[1]) * old];
  }
  const depth = rows.lt ? (rows.lt[idx] || 0) / 100 : 1;
  const health = rows.shield ? Math.max(0, rows.shield[idx] || 0) : C.x260;
  const n1 = (health / C.x260) * (depth * (C.x2D8 - C.x2D4) + C.x2D4);
  return { dx: c[0] * f, dy: c[1], r: e.s * ((1 - C.x264) * n1 + C.x264) };
}

// Every animation name a (cid, state) may draw: the mapped one, then its
// fallback. Callers that ship only the animations a clip needs must include
// all of them, or the fallback has nothing to draw.
export function animCandidates(charmaps, cid, state) {
  const ch = charmaps.chars[String(cid)];
  if (!ch) return [];
  const action = charmaps.actionNameById[state];
  const name = ch.animationMap[action] || ch.specialsMap[String(state)] || action || null;
  const own = GAME_MOTIONS[String(cid)]?.[String(state)];
  const out = own ? [own] : [];
  if (name) out.push(name);
  // a common action's own name (Captain Falcon's taunts are AppealR/AppealL,
  // not the Appeal other zips use)
  if (action && action !== name && state < 341) out.push(action);
  const game = MOTION_NAMES[String(cid)]?.[String(state)];
  if (game) out.push(game);
  const fb = fallbackFor(name) || fallbackFor(action);
  if (fb) out.push(...(fb.names || [fb.name]));
  return [...new Set(out)];
}

export function createRenderer(charmaps) {
  const cache = new Map(); // path string -> Path2D
  const p2d = (d) => {
    let p = cache.get(d);
    if (!p) { p = new Path2D(d); cache.set(d, p); }
    return p;
  };

  function animName(cid, state) {
    const ch = charmaps.chars[String(cid)];
    if (!ch) return null;
    const action = charmaps.actionNameById[state];
    return ch.animationMap[action] || ch.specialsMap[String(state)] || action || null;
  }

  // The frames to draw for (cid, state): the first candidate the zip has.
  function pose(anims, cid, state) {
    if (!anims) return null;
    const ch = charmaps.chars[String(cid)];
    const action = charmaps.actionNameById[state];
    const name = ch.animationMap[action] || ch.specialsMap[String(state)] || action || null;
    for (const n of [GAME_MOTIONS[String(cid)]?.[String(state)], name, state < 341 ? action : null, MOTION_NAMES[String(cid)]?.[String(state)]]) {
      if (n && anims[n] && anims[n].length) return { frames: anims[n], hold: false };
    }
    const fb = fallbackFor(name) || fallbackFor(action);
    for (const n of fb ? (fb.names || [fb.name]) : []) {
      if (anims[n] && anims[n].length) return { frames: anims[n], hold: !!fb.hold };
    }
    return null;
  }

  // Draw one character in world space. o = {cid, state, age, x, y, facing, fill,
  // stroke, strokeW, outline: {colour, px} (a line px screen pixels wide just
  // outside the silhouette), view:{S,ox,oy}, dpr}, plus optionally the fighter's
  // states/ages arrays and the row idx (for poses the game keeps). Returns
  // false when no animation is available (caller should draw a dot instead),
  // "hidden" when the game hides the fighter, "empty" when the pose itself
  // shows nothing (caller draws nothing either way), "egg" when it drew the
  // Yoshi egg the fighter is in. Sets/
  // restores the transform.
  function draw(ctx, animData, o) {
    const ch = charmaps.chars[String(o.cid)];
    if (!ch) return false;
    if (hiddenAt(o.cid, o.state)) return "hidden";
    if (EGG_STATES.has(o.state)) { drawEgg(ctx, o); return "egg"; }
    if (o.cid === 14 && YOSHI_EGG_SHIELD.has(o.state)) { drawEggShield(ctx, o); return "egg"; }
    const shell = koopaShell(o);
    if (shell) { drawKoopaShell(ctx, o, shell); return "shell"; }
    const anims = animData[String(o.cid)];
    let p = pose(anims, o.cid, o.state), age = o.age;
    if (!p && KEEP_POSE.has(o.state) && o.states && o.idx != null) {
      // the last drawable pose before this run of animation-less states, held
      for (let k = o.idx - 1; k >= 0 && o.idx - k <= 600; k--) {
        const st = o.states[k];
        if (st == null || hiddenAt(o.cid, st)) break;
        const q = pose(anims, o.cid, st);
        if (q) { p = q; age = o.ages ? o.ages[k] : 0; break; }
        if (!KEEP_POSE.has(st)) break;
      }
    }
    if (!p) return false;
    const frames = p.frames;
    let d = p.hold ? frames[frames.length - 1]
      : frames[Math.floor(Math.max(0, age)) % frames.length];
    // Most zips pad each animation to 201 entries and store a repeated pose as
    // "frameN", the same as entry N (loops restart, holds repeat their last
    // pose). Unresolved, Path2D("frameN") is an invalid path that draws
    // nothing: the fighter vanished on those frames.
    for (let n = 0; typeof d === "string" && /^frame\d+$/.test(d) && n < 4; n++) d = frames[+d.slice(5)];
    // An empty pose is the model showing nothing on that frame (Mewtwo
    // vanishes mid air dodge): draw nothing, and no dot either.
    if (d === "") return "empty";
    if (!d) return false;
    const S = o.view.S * o.dpr, ox = o.view.ox * o.dpr, oy = o.view.oy * o.dpr;
    let x = o.x, y = o.y, facing = o.facing || 1;
    const pin = PINNED.has(o.state) && XROTN[o.cid];
    if (pin) {                       // hung from the thrower, facing it
      const [h, dz] = pin, s = ch.scale;
      x = o.x + facing * dz * (1 + s); y = o.y - (s - 1) * h; facing = -facing;
    }
    ctx.save();
    ctx.setTransform(S, 0, 0, -S, ox, oy);
    ctx.translate(x, y);
    ctx.scale(ch.scale, ch.scale);
    ctx.scale(facing, 1);
    ctx.scale(0.1, -0.1);
    ctx.translate(-500, -500);
    const path = p2d(d);
    if (o.outline) {
      // stroked under the fill, twice as wide: only its outer half shows
      ctx.lineJoin = "round";
      ctx.lineWidth = 2 * o.outline.px * o.dpr / (S * ch.scale * 0.1);
      ctx.strokeStyle = o.outline.colour;
      ctx.stroke(path);
    }
    if (o.fill) { ctx.fillStyle = o.fill; ctx.fill(path); }
    if (o.stroke) {
      ctx.lineJoin = "round";
      ctx.lineWidth = o.strokeW || 14;
      ctx.strokeStyle = o.stroke;
      ctx.stroke(path);
    }
    ctx.restore();
    return true;
  }

  // The shield bubble where the game draws it (shieldAt below); without the
  // fighter's rows (older callers) the character's static offset.
  // o = {cid, x, y, facing, health, light, color, view, dpr, rows?, idx?,
  // shape?}: `shape`, rings in hundredths of the radius ([x0, y0, dx1, dy1,
  // ...], even-odd), is drawn instead of the disc (shield stun's torn bubble,
  // hitSparks.shieldStun). Returns the bubble {cx, cy, r}.
  function shield(ctx, o) {
    const ch = charmaps.chars[String(o.cid)];
    let cx, cy, r;
    const b = o.rows ? shieldAt(o.cid, o.rows, o.idx) : null;
    if (b) {
      cx = o.x + b.dx; cy = o.y + b.dy; r = b.r;
    } else {
      if (!ch || !ch.shieldOffset) return;
      const press = o.light == null ? 1 : o.light;
      const mult = String(o.cid) === '14' ? 1
        : (Math.max(0, o.health) / 60) * (1 - 0.5 * press) * 0.85 + 0.15;
      r = (ch.shieldSize || 12) * mult;
      cx = o.x + ch.shieldOffset[0] * (o.facing || 1);
      cy = o.y + ch.shieldOffset[1];
    }
    const S = o.view.S * o.dpr, ox = o.view.ox * o.dpr, oy = o.view.oy * o.dpr;
    ctx.save();
    ctx.setTransform(S, 0, 0, -S, ox, oy);
    ctx.globalAlpha = 0.42;
    ctx.fillStyle = o.color;
    ctx.beginPath();
    if (o.shape) {
      for (const flat of o.shape) {
        let u = flat[0], v = flat[1];
        ctx.moveTo(cx + u * r / 100, cy + v * r / 100);
        for (let i = 2; i < flat.length; i += 2) { u += flat[i]; v += flat[i + 1]; ctx.lineTo(cx + u * r / 100, cy + v * r / 100); }
        ctx.closePath();
      }
      ctx.fill('evenodd');
    } else { ctx.arc(cx, cy, r, 0, 7); ctx.fill(); }
    ctx.restore();
    ctx.globalAlpha = 1;
    return { cx, cy, r };
  }

  // every animation name draw() may use for (cid, state), for callers that
  // ship only what a clip needs (share artifacts)
  const candidates = (cid, state) => animCandidates(charmaps, cid, state);
  return { draw, animName, shield, candidates };
}
