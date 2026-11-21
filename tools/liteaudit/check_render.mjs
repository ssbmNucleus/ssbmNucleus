import fs from 'node:fs';
import path from 'node:path';
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';
import { ROOT, REPLAYS, args, outDir, selection, readJSON, writeJSON, produce, Flags,
  trueFrame, itemFrames, matchItems, direct } from './common.mjs';
import { RecordingContext, RecordingPath2D, segments } from './recording_context.mjs';

register('./loader.mjs', import.meta.url);
globalThis.Path2D = RecordingPath2D;
const paint = await import(pathToFileURL(path.join(REPLAYS, 'litePaint.js')).href);
const { EXPLOSIONS, explosionLength, modelHidden } = await import(pathToFileURL(path.join(REPLAYS, 'itemArt.js')).href);
const { createRenderer } = await import(pathToFileURL(path.join(REPLAYS, 'meleeRender.js')).href);
const stages = await import(pathToFileURL(path.join(REPLAYS, 'meleeStages.js')).href);
const { stageGeometryAt, cachedFills, buriedPlatform } = await import(pathToFileURL(path.join(REPLAYS, 'liteStageInference.js')).href);const charmaps = readJSON(path.join(ROOT, 'app/backend/tracker/tools/charmaps.json'));

// Game facts the checks below compare paint against; never read from the paint code.
// Hit sparks: every hit effect lasts at least 4 frames (EfCoData; the strong
// flash is shortest); a throw's release spawns none; the spark sits on the
// victim's hurtbox, so well within 20 units of its middle.
const HIT_SPARK_FRAMES = 2, HIT_SPARK_REACH = 20;
// Sword trails (ftafterimage.c): a start command opens a trail in the move's
// script, a stop command or any motion change ends it; every frame whose action
// frame moves (not frozen in hitlag) pushes the sword joint into a ring of 3,
// drawn from 2 samples. The strip's newest outer edge is the blade's tip,
// joint + axis x outer, from the ISO's tables (data/hits/<cid>.json `trail`,
// tools/liteaudit/sword_trails/build.py).
// A held Beam Sword's trail (`beam`, every fighter's Swing states) is the same
// rule on the sword item's bone 5, its blade out to the newest push's length.
const HIT_TABLES = Array.from({ length: 27 }, (_, c) => readJSON(path.join(REPLAYS, `data/hits/${c}.json`)));
const SWORD_TRAIL_REACH = 1.5;
const THROWN_STATES = new Set([239, 240, 241, 242, 243]);
const vanillaFighter = cid => cid != null && cid >= 0 && cid <= 26;
// Fox (1) / Falco (22) reflector states, ftFx_SpecialLw.c: Start, Loop, Hit, Turn,
// grounded then aerial. What the game draws is its effect (EfFxData.dat
// effFoxDataTable models 1/0/2 for start/held/reflect): every hexagon has its
// corners at 30 + 60k degrees, one straight up. Held: corners 8.2686 x pulse
// (0.422 / 0.751 / 1.0199) x model scale (0.96 / 1.10) from HipN, which RAM puts
// at (-1.27, 5.62) grounded and (-0.13, 7.3) aerial, model units along facing.
// The reflect flash shows on action frames 1-11 only.
const REFLECT_STATES = new Set([360, 361, 362, 364, 365, 366, 367, 369]);
const REFLECT_SCALE = { 1: 0.96, 22: 1.1 };
const REFLECT_HELD_CENTRE = { 361: [-1.27, 5.62], 364: [-1.27, 5.62], 366: [-0.13, 7.3], 369: [-0.13, 7.3] };
const REFLECT_HELD_R = [0.422, 0.751, 1.0199].map(p => 8.2686 * p);
const reflectShown = (s, age) => !(s === 362 || s === 367) || (age >= 1 && Math.floor(age) <= 11);
// corners at 30 + 60k degrees around (cx, cy)
const cornersUpright = (pts, cx, cy) => pts.every(([x, y]) => Math.hypot(x - cx, y - cy) < 1e-6
  || Math.abs(((Math.atan2(y - cy, x - cx) * 180 / Math.PI - 30) % 60 + 60) % 60) < 1e-3
  || Math.abs(((Math.atan2(y - cy, x - cx) * 180 / Math.PI - 30) % 60 + 60) % 60 - 60) < 1e-3);
// Blaster shots (Fox 54, Falco 55, Kirby's copies 136/137): itfoxlaser.c grows the
// beam's z scale by speed / 11.25 a frame up to FoxLaserAttr +4 (3), from 0 on a
// reflect or shield bounce; checked against RAM in playback Dolphin.
const BLASTER_KINDS = new Set([54, 55, 136, 137]);
const PK_TRAIL_KINDS = new Set([70, 71, 72, 73]);
function blasterTruth(it, k) {
  const turn = (a, b) => { const m = Math.hypot(it.vx[a], it.vy[a]) * Math.hypot(it.vx[b], it.vy[b]);
    return m > 1e-6 && (it.vx[a] * it.vx[b] + it.vy[a] * it.vy[b]) / m < 0.7; };
  if (k + 1 < it.vx.length && turn(k, k + 1)) return 0;
  let j = k; while (j > 0 && !turn(j - 1, j)) j--;
  return Math.min(3, (k - j + 1) * Math.hypot(it.vx[k], it.vy[k]) / 11.25);
}
// States that set fp->invisible on entry (melee decomp): CaptureWaitKirby 289,
// BarrelWait 293, CaptureKirbyYoshi 331, Barrel 340; Sheik's and Zelda's up-B
// travel (ftSk/ftZd_SpecialHi 356/359, 350/353) and Mewtwo's teleport
// (ftMt_SpecialHi 354/357). YoshiEgg 277 and KirbyYoshiEgg 332 hide the
// fighter but show Yoshi's egg (an accessory, ftCo_800BBED4): no item record
// carries it, so the egg must be drawn in the fighter's place.
const INVISIBLE = new Set([289, 293, 331, 340]);
const EGGED = new Set([277, 332]);
const INVISIBLE_SPECIAL = { 7: [356, 359], 19: [350, 353], 16: [354, 357] };
const invisibleFighter = (cid, state) => INVISIBLE.has(state) || !!INVISIBLE_SPECIAL[cid]?.includes(state);
// A grabbed or thrown fighter, by the game's own action names (not the bundle's cat).
const capturedName = state => /^(Capture|Thrown)/.test(charmaps.actionNameById[state] || '');
// Host canvas shapes, CSS pixels: the desktop clip and modal (16:9,
// WatchLiteModal.css .wl-clip-stage), a wide card (2.5:1) and the phone
// player in portrait (services/mobile .dcanvas: width 100%, 40vh).
const HOST_SIZES = [[960, 540, 'wide16x9'], [615, 250, 'wide2_5'], [390, 338, 'portrait']];
// Item names from the baked item tables (game data), for the held-prop rule.
const itemNames = new Map();
for (const file of fs.readdirSync(path.join(REPLAYS, 'data/items')).filter(f => /^\d+\.json$/.test(f))) {
  const d = JSON.parse(fs.readFileSync(path.join(REPLAYS, 'data/items', file), 'utf8'));
  itemNames.set(d.kind, `${d.family === 'attached' ? 'attached:' : ''}${d.name || ''}`);
}
// Two held props have no baked table; their ItemKind names (it/forward.h).
itemNames.set(84, 'It_Kind_DrMario_Sheet');
itemNames.set(123, 'It_Kind_CLink_Milk');
const heldProp = kind => /^attached:|(Blaster|Bow|Kirby_Hammer|Mario_Cape|DrMario_Sheet|CLink_Milk|Ness_Bat|Ness_Yoyo|Peach_Parasol|Peach_Toad|PeachToad|NeedleHeld|IceClimber_GumStrings|GameWatchChefPan|HShot|GBeam|Seak_Chain)$/
  .test(itemNames.get(kind) || '');
// Kind 0xA0 on a stage is the ground "yaku" item (grMaterial -> it_802E6AEC):
// its ItCo.dat article has no model. It may be drawn only as the hazard it
// carries where that hazard has no collision of its own, in a state whose
// ALDYakuAll script has a hitbox: Peach's Castle 3/4, Onett 2-5, Mute City 2,
// Jungle Japes 2 (GrCs/GrOt/GrMc/GrGd.dat).
const YAKU_HAZARD_STATES = { 4: [3, 4], 9: [2, 3, 4, 5], 10: [2], 12: [2] };
// Samus's missile after it explodes (states 2 homing / 3 super) lingers 80
// frames with every joint hidden (it_8026BB44); Onett's lane-B cars (GrOt.dat,
// state 0, no hitbox) are visible while they drive (|x| < 577.8, moving).
const invisibleItem = (kind, stage, state, item) => {
  if (kind === 95) return state === 2 || state === 3;
  if (kind !== 160) return false;
  if (YAKU_HAZARD_STATES[stage]?.includes(state)) return false;
  return !(stage === 9 && state === 0 && item && Math.abs(item.x) < 577.8 && item.moving);
};
// The last vanilla ItemKind (It_Kind_Kyasarin_Egg); higher kinds are m-ex
// fighters' own items.
const LAST_VANILLA_KIND = 236;
// Vanilla kinds the game itself shows as a plain round ball, so one filled
// circle is their honest look (render_item_dot does not apply): Samus's bomb,
// the Thunder Jolt (Pikachu's, Pichu's and Kirby's copies), Mewtwo's Shadow
// Ball and Kirby's copy, Ness's PK Flash and Kirby's copy.
const DOT_OK = new Set([93, 89, 90, 91, 92, 147, 148, 149, 150, 112, 144, 68, 145]);

// Device-space fill subpaths of a recorded call, back in world units for a view.
function fillPolygons(calls, view) {
  const polys = [];
  for (const c of calls) {
    if (c.op !== 'fill' || !c.path?.length || c.alpha <= 0) continue;
    let cur = null;
    for (const p of c.path) {
      if (p.op === 'moveTo') polys.push(cur = []);
      if ((p.op === 'moveTo' || p.op === 'lineTo') && cur)
        cur.push([(p.point[0] - view.ox) / view.S, (view.oy - p.point[1]) / view.S]);
    }
  }
  return polys.filter(p => p.length >= 3);
}
const STAGE_FILL = '#20263a';   // litePaint.paintFrame's landmass colour
// Where two non-adjacent edges of the outline cross (null: they never do).
const checkedPolys = new WeakSet();
function selfCrossing(poly) {
  const n = poly.length, cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  for (let i = 0; i < n; i++) for (let j = i + 2; j < n; j++) {
    if (i === 0 && j === n - 1) continue;
    const a = poly[i], b = poly[(i + 1) % n], c = poly[j], d = poly[(j + 1) % n];
    if (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0) return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  }
  return null;
}
// Canvas' default nonzero rule over every subpath of the fill.
function insideNonzero(polys, x, y) {
  let winding = 0;
  for (const p of polys) for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const [xi, yi] = p[i], [xj, yj] = p[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) winding += yi > yj ? 1 : -1;
  }
  return winding !== 0;
}
const vkey = (x, y) => `${Math.round(x * 100)},${Math.round(y * 100)}`;
// A group of solid lines with no wall or ceiling is a surface (a platform, a
// raft top), whatever its drop-through bit says: some simulator tables omit it.
export function surfaceLines(lines) {
  const solid = lines.filter(l => !(l[1] & 256) && l[1] & 15), parent = solid.map((_, i) => i);
  const find = i => parent[i] === i ? i : (parent[i] = find(parent[i]));
  const at = new Map();
  solid.forEach((l, i) => { for (const k of [vkey(l[2], l[3]), vkey(l[4], l[5])]) {
    if (at.has(k)) parent[find(i)] = find(at.get(k)); else at.set(k, i);
  } });
  const body = new Set();
  solid.forEach((l, i) => { if (l[1] & 14) body.add(find(i)); });
  return new Set(solid.filter((_, i) => !body.has(find(i))));
}
// Floors on a closed clockwise run of collision: following the stored
// direction (each line continues into one starting where it ends) leads back
// to the floor's own start, and the loop found winds clockwise, i.e. with the
// solid side (always on a line's right) inside. Those top a body for certain.
export function enclosedFloors(lines) {
  const solid = lines.filter(l => !(l[1] & 256) && l[1] & 15), starts = new Map();
  for (const l of solid) { const k = vkey(l[2], l[3]); if (!starts.has(k)) starts.set(k, []); starts.get(k).push(l); }
  const out = new Set();
  for (const f of solid) {
    if ((f[1] & 15) !== 1 || out.has(f)) continue;
    const home = vkey(f[2], f[3]), parent = new Map([[f, null]]), queue = [f];
    let last = null;
    while (queue.length && !last) {
      const c = queue.shift();
      for (const n of starts.get(vkey(c[4], c[5])) || []) {
        if (parent.has(n)) continue;
        parent.set(n, c);
        if (vkey(n[4], n[5]) === home) { last = n; break; }
        queue.push(n);
      }
      if (!last && vkey(c[4], c[5]) === home) last = c;
    }
    if (!last) continue;
    const loop = [];
    for (let c = last; c; c = parent.get(c)) loop.push(c);
    let area = 0;
    for (const l of loop) area += (l[4] - l[2]) * (l[5] + l[3]);
    if (area > 0) for (const l of loop) if ((l[1] & 15) === 1) out.add(l);   // clockwise
  }
  return out;
}
// Solid lines grouped by shared endpoints.
function components(lines) {
  const solid = lines.filter(l => !(l[1] & 256) && l[1] & 15), parent = solid.map((_, i) => i);
  const find = i => parent[i] === i ? i : (parent[i] = find(parent[i]));
  const at = new Map();
  solid.forEach((l, i) => { for (const k of [vkey(l[2], l[3]), vkey(l[4], l[5])]) {
    if (at.has(k)) parent[find(i)] = find(at.get(k)); else at.set(k, i);
  } });
  const groups = new Map();
  solid.forEach((l, i) => { const r = find(i); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(l); });
  return [...groups.values()];
}
// The fill must lie under every floor of a closed clockwise loop; every group
// of lines that has walls and floors must show a body under at least one of
// its floors (an open landmass such as Fountain of Dreams' still has one);
// and no fill may lie under an underside (a ceiling with no floor on it).
// Lines narrower than one unit or steeper than 45 degrees (walls; legacy
// outlines label them 2) are not judged. A wing, a bridge or a deck with a
// free end is not required to have a body.
export function stageFillFindings(lines, fills) {
  const surfaces = surfaceLines(lines), enclosed = enclosedFloors(lines);
  const out = { floors: 0, ceilings: 0, missing: [], outside: [] };
  const flat = l => Math.abs(l[4] - l[2]) >= 1 && Math.abs(l[5] - l[3]) <= Math.abs(l[4] - l[2]);
  const bodyUnder = l => insideNonzero(fills, (l[2] + l[4]) / 2, (l[3] + l[5]) / 2 - .3);
  for (const group of components(lines)) {
    const floors = group.filter(l => (l[1] & 15) === 1 && flat(l));
    if (!group.some(l => l[1] & 14) || !floors.length) continue;
    out.floors++;
    if (!floors.some(bodyUnder)) out.missing.push(floors[0]);
  }
  const floorAt = (x, y) => lines.some(l => (l[1] & 15) === 1 && !(l[1] & 256) &&
    x >= Math.min(l[2], l[4]) && x <= Math.max(l[2], l[4]) && Math.abs(l[3] + (l[5] - l[3]) * (x - l[2]) / (l[4] - l[2] || 1) - y) < .05);
  for (const l of lines) {
    if (l[1] & 256 || Math.abs(l[4] - l[2]) < 1 || Math.abs(l[5] - l[3]) > Math.abs(l[4] - l[2])) continue;
    const kind = l[1] & 15, mx = (l[2] + l[4]) / 2, my = (l[3] + l[5]) / 2;
    if (kind === 1 && enclosed.has(l)) {
      out.floors++;
      if (!insideNonzero(fills, mx, my - .3)) out.missing.push(l);
    } else if (kind === 2 && !floorAt(mx, my)) {
      out.ceilings++;
      if (insideNonzero(fills, mx, my - .3)) out.outside.push(l);
    }
  }
  return { ...out, surfaces };
}

export function loadAnimations(bundle, out, shard = '1/1') {
  const cids = new Set(bundle.frames.cid.flatMap(v => Array.from(v)));
  for (const f of bundle.frames.fol || []) for (const cid of f.cid) if (cid != null) cids.add(cid);
  const anim = {}, unavailable = [];
  for (const cid of cids) {
    try { anim[cid] = readJSON(path.join(out, 'anims', shard.replace('/', '-'), `${cid}.json.gz`)); }
    catch { anim[cid] = {}; unavailable.push(cid); }
    if (!Object.keys(anim[cid]).length && !unavailable.includes(cid)) unavailable.push(cid);
  }
  return { anim, unavailable };
}

export function checkRender(bundle, rowFids, truth, assets, { every = 30, traces = 0 } = {}) {
  const flags = new Flags(), ctx = new RecordingContext(), base = createRenderer(charmaps);
  const view = { S: 2, ox: 320, oy: 240 }, fallbacks = {}, drawTraces = [];
  for (const cid of assets.unavailable) flags.flag('animation_asset_unavailable', { cid });
  const rawItems = itemFrames(truth.raw.items, t => t.start);
  const actualItems = itemFrames(bundle.items || []);
  // Read-only proxies label the actual item pass. No source instrumentation and
  // no substitute drawItems implementation: removing a draw really is detected.
  const instrumented = { ...bundle, items: (bundle.items || []).map((it, index) => ({ ...it,
    x: new Proxy(it.x, { get(target, property) {
      if (/^\d+$/.test(String(property))) ctx.tag = `item:${index}`;
      return Reflect.get(target, property);
    } }),
  })) };
  let actors = [];
  const renderer = {
    draw(context, anim, options) {
      const tag = `fighter:${actors.length}`;
      context.tag = tag;
      const drew = base.draw(context, anim, options);
      actors.push({ tag, cid: options.cid, state: options.state, drew });
      return drew;
    },
    shield(context, options) { context.tag = 'shield'; return base.shield(context, options); },
  };
  const f = bundle.frames, NPL = f.x.length;
  // Hits: a frame a fighter's percent rises in hitlag, unless a throw released
  // it (the game spawns no spark for a throw, RAM-checked). [victim, hit row].
  const hitsNear = idx => {
    const out = [];
    for (let i = 0; i < NPL; i++) {
      for (let k = 0; k <= HIT_SPARK_FRAMES; k++) {
        const j = idx - k;
        if (j < 1 || !(f.pct?.[i]?.[j] - f.pct?.[i]?.[j - 1] > 0.001) || THROWN_STATES.has(f.state[i][j - 1])) continue;
        if (f.hitlag && !(f.hitlag[i][j] > 0)) continue;   // no hitlag, no collision: off-screen damage
        out.push([i, j]);
        break;
      }
    }
    return out;
  };
  // A sword trail (kind 'trail' or 'beam') due on idx for row i: { tip: [x, y]
  // of its newest sample, samples } or null (fewer than two samples in the ring).
  const trailDue = (i, idx, kind = 'trail') => {
    const T = HIT_TABLES[f.cid[i][idx]]?.[kind], st = f.state[i], age = f.age?.[i];
    if (!T || !age || !Number.isFinite(age[idx])) return null;
    let w = T.states[st[idx]];
    if (typeof w === 'number') w = T.states[w];
    w = w?.find(([a, b]) => Math.floor(age[idx]) >= a && Math.floor(age[idx]) <= b);
    if (!w) return null;
    const pushed = [];
    for (let j = idx; j >= 0 && pushed.length < 3; j--) {
      if (st[j] !== st[idx] || !(Math.floor(age[j]) >= w[0]) || (j < idx && age[j] > age[j + 1])) break;
      if (!(j > 0 && st[j - 1] === st[idx] && age[j - 1] === age[j])) pushed.push(j);
    }
    if (pushed.length < 2) return null;
    const j = pushed[0], r = w[2][Math.floor(age[j]) - w[0]], d = f.dir?.[i]?.[j] || 1, outer = kind === 'beam' ? r[6] : T.outer;
    return { tip: [f.x[i][j] + d * (r[0] + r[3] * outer), f.y[i][j] + r[1] + r[4] * outer], samples: pushed.length };
  };
  // Short events a stride would skip: reflector states, grab/throw victims, hits,
  // the first frame each sword trail is drawn.
  const eventFrame = idx => {
    for (let i = 0; i < NPL; i++) if (trailDue(i, idx)?.samples === 2 || trailDue(i, idx, 'beam')?.samples === 2) return true;
    for (let i = 0; i < NPL; i++) {
      const s = f.state[i][idx];
      if ((REFLECT_SCALE[f.cid[i][idx]] && REFLECT_STATES.has(s)) || capturedName(s)) return true;
    }
    return hitsNear(idx).length > 0;
  };
  // Simulators read item histories (to build their caches, or every frame, as
  // Great Bay's Tingle does). Those reads must not relabel the stage pass as
  // an item's draw: the loader reports when paint's stage geometry is done.
  if (bundle.meta.n) stageGeometryAt(instrumented, 0);
  globalThis.__liteauditAfterStageGeometry = () => { ctx.tag = 'stage'; };
  // The hosts' camera, stepped every row as in playback (WatchLiteClip.draw),
  // and the target it eases toward (the same step, snapped).
  const cam = {}, hostViews = Object.fromEntries(HOST_SIZES.map(([, , host]) => [host, []]));
  const targetViews = Object.fromEntries(HOST_SIZES.map(([, , host]) => [host, []]));
  for (let idx = 0; idx < bundle.meta.n; idx++) {
    paint.stepCamera(cam, f, idx, idx === 0);
    const target = {};
    paint.stepCamera(target, f, idx, true);
    for (const [w, h, host] of HOST_SIZES) {
      hostViews[host].push(paint.viewFromCam(cam, w, h));
      targetViews[host].push(paint.viewFromCam(target, w, h));
    }
  }
  for (let idx = 0; idx < bundle.meta.n; idx++) {
    const frame = trueFrame(bundle, rowFids, idx);
    const expected = rawItems.get(frame) || [], actual = actualItems.get(idx) || [];
    if (idx % every && !expected.length && !actual.length && idx !== bundle.meta.n - 1 && !eventFrame(idx)) continue;
    flags.metric('sampled_frames');
    ctx.reset(); actors = []; globalThis.__liteauditStageCalls = [];
    paint.paintFrame(ctx, instrumented, assets.anim, renderer, idx, view, 1);
    // Randall is called by the host after paintFrame, with this exact public
    // frame-basis contract. This audits that contract, not the React/mobile host.
    if (bundle.meta.stage === 8) {
      ctx.tag = 'randall';
      paint.drawRandall(ctx, bundle.meta.start_frame + idx, view, 1);
    }
    const callsByTag = new Map();
    for (const call of ctx.calls) {
      if (!callsByTag.has(call.tag)) callsByTag.set(call.tag, []);
      callsByTag.get(call.tag).push(call);
    }
    const { pairs, missing, extra } = matchItems(expected, actual);
    for (const item of missing) flags.flag('render_item_missing', { frame, idx, type: item.t, reason: 'absent from producer' });
    for (const item of extra) flags.flag('render_item_ghost', { frame, idx, type: item.t });
    // Items still painted as the generic owner-coloured dot: one filled arc in
    // the owner's port colour (grey without an owner) and nothing else.
    for (const a of actual) {
      const calls = (callsByTag.get(`item:${a.track}`) || []).filter(c => ['fill', 'stroke', 'drawImage'].includes(c.op) && c.alpha > 0);
      // The game shows nothing for an invisible item: nothing may be drawn.
      const itemState = a.s;
      const bi = bundle.items[a.track], bk = idx - bi.f;
      const moving = bk > 0 ? Math.abs(bi.x[bk] - bi.x[bk - 1]) > 0.05 : Math.abs(bi.vx?.[bk] || 0) > 0.05;
      if (invisibleItem(a.t, bundle.meta.stage, itemState, { x: a.x, moving }) && calls.length) flags.flag('render_item_invisible_drawn', { frame, idx, type: a.t, state: itemState });
      // A bomb that blew up (itemArt EXPLOSIONS): the game hides it and shows its
      // explosion, then keeps the item alive about 80 frames. Once our burst is
      // over nothing may be drawn for it (it lingered as a dot in 0.8.14).
      const blast = EXPLOSIONS[a.t];
      if (blast && itemState === blast[0]) {
        flags.metric('exploded_item_checks');
        let j = bk;
        while (j > 0 && bi.s?.[j - 1] === itemState) j--;
        if (bk - j >= explosionLength(blast[2]) && calls.length) flags.flag('render_exploded_item_drawn', { frame, idx, type: a.t, state: itemState, age: bk - j });
      }
      // Fox's and Falco's blaster shot (and Kirby's copies), itfoxlaser.c + RAM:
      // a white core from the head (item position) back 11.152 x s along the
      // travel line, s = min(3, (frames since it appeared or turned + 1) x
      // speed / 11.25), nothing on the frame it is reflected.
      if (BLASTER_KINDS.has(a.t)) {
        const it = bundle.items[a.track], k = idx - it.f;
        if (it.vx && it.vy && Math.hypot(it.vx[k], it.vy[k]) > 1e-6) {
          flags.metric('blaster_length_checks');
          const s = blasterTruth(it, k), m = Math.hypot(it.vx[k], it.vy[k]);
          const head = [a.x, a.y], tail = [a.x - 11.152 * s * it.vx[k] / m, a.y - 11.152 * s * it.vy[k] / m];
          const core = segments(calls.filter(c => c.strokeStyle === '#ffffff')).map(([p, q, r, t]) =>
            [(p - view.ox) / view.S, (view.oy - q) / view.S, (r - view.ox) / view.S, (view.oy - t) / view.S]);
          const ok = s < 0.01 ? !core.length : core.some(g => Math.hypot(g[0] - head[0], g[1] - head[1]) < .05 && Math.hypot(g[2] - tail[0], g[3] - tail[1]) < .05);
          if (!ok) flags.flag('blaster_length_wrong', { frame, idx, type: a.t, expectedScale: s });
        }
      }
      const owner = a.o != null && a.o >= 0 ? paint.pcolor(bundle, a.o) : '#aab4cc';
      // one filled circle and nothing else: a dot
      const dot = calls.length === 1 && calls[0].op === 'fill' && calls[0].path?.length === 1 && calls[0].path[0].op === 'arc';
      if (dot && calls[0].fillStyle === owner) {
        flags.metric('item_generic_dots');
        flags.metric(`item_generic_dot_kind_${a.t}`);
      }
      // A vanilla item drawn as a dot (the generic owner-coloured one or any
      // other plain circle) is a failure: every vanilla kind has a look of its
      // own, except the round balls in DOT_OK.
      if (dot && a.t <= LAST_VANILLA_KIND && !DOT_OK.has(a.t)) {
        flags.flag('render_item_dot', { frame, idx, type: a.t, state: itemState });
        flags.metric(`item_dot_kind_${a.t}`);
      }
    }
    for (const [e, a] of pairs) {
      flags.metric('live_item_draw_checks');
      const calls = callsByTag.get(`item:${a.track}`) || [];
      const drawn = calls.some(c => ['fill', 'stroke', 'drawImage'].includes(c.op) && c.alpha > 0);
      // A prop held by its fighter (blaster, bow, cape, bat, Game & Watch's
      // tools...) is part of the fighter's own pose and is deliberately not
      // drawn on its own; judged by the game's item name.
      // Painting nothing is right where the game draws nothing, by its item code:
      // the model is gone in this state (itemArt.modelHidden: exploded), a PK
      // Thunder tail piece hides its mesh on its odd frames
      // (itnesspkthundertrail.c), a blaster shot is scaled to 0.001 on the frame
      // it is reflected (itfoxlaser.c).
      const bi = bundle.items[a.track], bk = idx - bi.f;
      const blank = modelHidden(e.t, a.s) || (PK_TRAIL_KINDS.has(e.t) && (idx - (bi.born ?? bi.f)) % 2 === 1)
        || (BLASTER_KINDS.has(e.t) && bi.vx && bi.vy && blasterTruth(bi, bk) < 0.01);
      if (!drawn && !blank && !heldProp(e.t) && !invisibleItem(e.t, bundle.meta.stage, a.s, { x: a.x, moving: true })) {
        flags.flag('render_item_missing', { frame, idx, type: e.t, state: a.s, reason: 'no paint command' });
        flags.metric(`item_missing_kind_${e.t}`);
      }
      if (e.t !== 54 && e.t !== 55) continue;
      const segs = segments(calls);
      flags.metric('laser_segments_checked');
      if (!segs.length) { if (!blank) flags.flag('laser_no_segment', { frame, idx, type: e.t }); continue; }
      if (!Number.isFinite(e.vx) || !Number.isFinite(e.vy) || Math.hypot(e.vx, e.vy) < 1e-6) {
        flags.metric('laser_velocity_indeterminate'); continue;
      }
      const [x0, y0, x1, y1] = segs[0];
      const angle = Math.atan2(-(y1 - y0), x1 - x0), expectedAngle = Math.atan2(e.vy, e.vx);
      // A line segment has no arrowhead: orientation is modulo 180 degrees.
      const error = Math.acos(Math.min(1, Math.abs(Math.cos(angle - expectedAngle)))) * 180 / Math.PI;
      if (error > 3) flags.flag('laser_angle', { frame, idx, type: e.t, degrees: error,
        actualDegrees: angle * 180 / Math.PI, expectedDegrees: expectedAngle * 180 / Math.PI });
    }
    for (const actor of actors) {
      flags.metric('fighters_drawn');
      if (actor.state > 10) flags.metric('live_fighters_drawn');
      const calls = callsByTag.get(actor.tag) || [];
      if (EGGED.has(actor.state)) {
        flags.metric('eggs');
        if (actor.drew !== 'egg' || !calls.some(c => c.op === 'fill')) flags.flag('fighter_egg_not_drawn', { frame, idx, cid: actor.cid, state: actor.state });
        continue;
      }
      if (actor.drew === 'shell') {
        // Bowser inside Whirling Fortress: the game shows only the shell model
        flags.metric('koopa_shells');
        if (!calls.some(c => c.op === 'fill')) flags.flag('fighter_shell_not_drawn', { frame, idx, cid: actor.cid, state: actor.state });
        continue;
      }
      if (actor.drew === 'hidden') {
        // Only where the game itself hides the model, and then nothing drawn.
        flags.metric('hidden_fighters');
        if (!invisibleFighter(actor.cid, actor.state) || calls.some(c => ['fill', 'stroke'].includes(c.op)))
          flags.flag('fighter_hidden_wrong', { frame, idx, cid: actor.cid, state: actor.state });
        continue;
      }
      // An animation frame stored as "frameN" (a reference to entry N of the
      // same animation) is not SVG path data: drawn as is, the fighter vanishes.
      if (calls.some(c => c.op === 'fill' && /^frame\d+$/.test(c.args[0]?.svg || '')))
        flags.flag('fighter_frame_reference_drawn', { frame, idx, cid: actor.cid, state: actor.state });
      if (actor.drew === 'empty') {
        // The pose's own geometry is empty (Mewtwo mid air dodge): nothing drawn.
        flags.metric('empty_poses');
        if (calls.some(c => ['fill', 'stroke'].includes(c.op))) flags.flag('fighter_empty_pose_drawn', { frame, idx, cid: actor.cid, state: actor.state });
        continue;
      }
      if (actor.drew && calls.some(c => c.op === 'fill' && c.args[0]?.svg)) flags.metric('silhouettes');
      else if (!actor.drew && calls.some(c => c.op === 'fill' && c.path?.some(p => p.op === 'arc' && p.radius === 7))) {
        flags.metric('dot_fallbacks');
        if (actor.state > 10) flags.metric('live_dot_fallbacks');
        const key = `${actor.cid}/${actor.state}`;
        fallbacks[key] = (fallbacks[key] || 0) + 1;
        flags.flag('fighter_dot_fallback', { frame, idx, cid: actor.cid, state: actor.state });
      } else flags.flag('fighter_no_draw', { frame, idx, cid: actor.cid, state: actor.state, returned: actor.drew });
    }
    // Stages are drawn from the dumped live collision (collisionGeometry, via
    // liteStageInference). Judge what was DRAWN: every floor the collision
    // says exists at this frame must appear among the stage's segments.
    const live = stages.collisionGeometry(bundle.meta.stage, frame);
    if (live && live.covered && !live.partial) {
      // Yoshi's Story's cloud is a collision floor drawn by drawRandall.
      const drawn = segments([...(callsByTag.get('stage') || []), ...(callsByTag.get('randall') || [])]).map(([a, b, c, d]) =>
        [(a - view.ox) / view.S, (view.oy - b) / view.S, (c - view.ox) / view.S, (view.oy - d) / view.S]);
      flags.metric('collision_floors_checked', live.floors.length);
      // A floor with solid body just above it is inside the landmass and the
      // game shows nothing there (FoD's sunk platforms, Randall under the stage).
      const body = cachedFills(live.lines);
      const buried = f => insideNonzero(body, (f[0] + f[2]) / 2, (f[1] + f[3]) / 2 + 0.5);
      for (const f of live.floors) {
        const hit = drawn.some(s => (Math.hypot(s[0] - f[0], s[1] - f[1]) < .05 && Math.hypot(s[2] - f[2], s[3] - f[3]) < .05)
          || (Math.hypot(s[0] - f[2], s[1] - f[3]) < .05 && Math.hypot(s[2] - f[0], s[3] - f[1]) < .05));
        if (buried(f)) {
          flags.metric('collision_floors_buried');
          if (hit) flags.flag('buried_floor_drawn', { frame, idx, floor: f });
        } else if (!hit) flags.flag('collision_floor_not_drawn', { frame, idx, floor: f });
      }
    }
    // What the stage looks like, not only which floors exist. The body fill
    // must lie under every floor that tops a body and never under an underside:
    // a missing fill (simulated stages) or a slab to the lowest point both fail.
    const geometry = stageGeometryAt(instrumented, idx);
    const stageCalls = callsByTag.get('stage') || [];
    // the stage body is its own colour; the revival platform and the Fire Fox
    // plume are drawn in the same phase, under the fighters
    const fills = fillPolygons(stageCalls.filter(c => !c.args?.[0]?.svg && (c.op !== 'fill' || c.fillStyle === STAGE_FILL)), view);
    const findings = stageFillFindings(geometry.lines, fills);
    const platform = l => l[1] & 256 || findings.surfaces.has(l);
    flags.metric('fill_floor_checks', findings.floors);
    flags.metric('fill_ceiling_checks', findings.ceilings);
    for (const line of findings.missing) flags.flag('stage_fill_missing', { frame, idx, line });
    for (const line of findings.outside) flags.flag('stage_fill_outside_collision', { frame, idx, line });
    // A self-crossing body outline cancels part of itself out of the nonzero
    // fill (a hole in the ground) where the camera can see it. Each traced
    // polygon is checked once.
    for (const poly of geometry.fills || []) {
      if (checkedPolys.has(poly)) continue;
      checkedPolys.add(poly);
      flags.metric('fill_polygons_checked');
      const at = selfCrossing(poly);
      if (at && Math.abs(at[0]) < 300 && at[1] > -250 && at[1] < 300) flags.flag('stage_fill_self_crossing', { frame, idx, points: poly.length, at });
    }
    // A wall or ceiling stroked with body on both sides is a seam inside the
    // landmass the game does not show (Stadium's base walls under a terrain).
    const strokedLines = segments(stageCalls.filter(c => c.alpha >= .99)).map(([a, b, c, d]) => [(a - view.ox) / view.S, (view.oy - b) / view.S,
      (c - view.ox) / view.S, (view.oy - d) / view.S]);
    for (const l of geometry.lines) {
      const len = Math.hypot(l[4] - l[2], l[5] - l[3]);
      if (l[1] & 1 || !(len > 1)) continue;
      if (!strokedLines.some(s => [[0, 1, 2, 3], [2, 3, 0, 1]].some(o => o.every((k, n) => Math.abs(s[k] - l[2 + n]) < .05)))) continue;
      flags.metric('stroke_seam_checks');
      const mx = (l[2] + l[4]) / 2, my = (l[3] + l[5]) / 2, nx = -(l[5] - l[3]) / len * 0.5, ny = (l[4] - l[2]) / len * 0.5;
      if (insideNonzero(fills, mx + nx, my + ny) && insideNonzero(fills, mx - nx, my - ny)) flags.flag('stage_interior_stroke', { frame, idx, line: l });
    }
    // Frames drawn from the authored fallback shapes (no collision dump and no
    // simulator result) and frames whose geometry is known only in part. An
    // authored outline is open (Great Bay's turtle arcs), so the fill rule
    // above cannot judge it: this count is what shows how often that happens.
    if (/^legacy/.test(geometry.source || '')) flags.metric('stage_authored_frames');
    if (geometry.partial) flags.metric('stage_partial_frames');
    // Shapes that are not collision: a grabbed/thrown fighter keeps the
    // grabber's grounded flag, so nothing opaque (this frame's mark, not a
    // fading trail of where it stood before) may be stroked centred on its feet.
    const strokes = segments(stageCalls.filter(c => c.alpha >= .99)).map(([a, b, c, d]) => [(a - view.ox) / view.S, (view.oy - b) / view.S,
      (c - view.ox) / view.S, (view.oy - d) / view.S]);
    const isLine = s => geometry.lines.some(l => [[2, 3, 4, 5], [4, 5, 2, 3]].some(o => o.every((k, n) => Math.abs(l[k] - s[n]) < .05)));
    for (let i = 0; i < NPL; i++) {
      const s = f.state[i][idx];
      if (!capturedName(s) || !f.air || f.air[i][idx]) continue;
      flags.metric('captured_grounded_checks');
      const x = f.x[i][idx], y = f.y[i][idx];
      for (const g of strokes) {
        if (Math.abs(g[1] - y) > 1e-3 || Math.abs(g[3] - y) > 1e-3 || Math.abs((g[0] + g[2]) / 2 - x) > 1e-3 || isLine(g)) continue;
        flags.flag('stray_stroke_under_captured', { frame, idx, port: i, state: s, y, segment: g });
      }
    }
    // Effects Slippi never records still have to be drawn: the reflector, the
    // way the game draws it (upright corners; held: its size and centre).
    const allFills = fillPolygons(ctx.calls.filter(c => !c.args?.[0]?.svg), view);
    for (let i = 0; i < NPL; i++) {
      const c = f.cid[i][idx], s = f.state[i][idx], k = REFLECT_SCALE[c];
      if (!k || !REFLECT_STATES.has(s) || !reflectShown(s, f.age?.[i]?.[idx])) continue;
      flags.metric('reflector_checks');
      const x = f.x[i][idx], y = f.y[i][idx], dir = f.dir?.[i]?.[idx] || 1;
      // a hexagon (6 corners, centre = their mean) or a half hexagon (centre first, then 4 corners) near the hips
      const shapes = allFills.filter(p => p.length === 6 || p.length === 5).map(p => {
        const [cx, cy] = p.length === 6 ? [p.reduce((a, q) => a + q[0], 0) / 6, p.reduce((a, q) => a + q[1], 0) / 6] : p[0];
        return { p, cx, cy };
      }).filter(q => Math.hypot(q.cx - x, q.cy - (y + 6.5 * k)) < 6 * k);
      const held = REFLECT_HELD_CENTRE[s];
      const right = shapes.filter(q => !held || (Math.hypot(q.cx - (x + dir * held[0] * k), q.cy - (y + held[1] * k)) < 1e-3
        && q.p.length === 6 && REFLECT_HELD_R.some(r => q.p.every(([px, py]) => Math.abs(Math.hypot(px - q.cx, py - q.cy) - r * k) < 1e-3))));
      if (!right.length) flags.flag('reflector_not_drawn', { frame, idx, port: i, cid: c, state: s });
      else if (!right.some(q => cornersUpright(q.p, q.cx, q.cy))) flags.flag('reflector_turned', { frame, idx, port: i, cid: c, state: s });
    }
    // Hit sparks: for the first frames after a hit, a spark is filled near the
    // victim (its contact point is on the victim's hurtbox, within a hitbox
    // radius of the hitbox; HIT_SPARK_REACH covers both).
    const sparkFills = fillPolygons(callsByTag.get('spark') || [], view);
    for (const [i, j] of hitsNear(idx)) {
      if (!vanillaFighter(f.cid[i][idx])) continue;
      flags.metric('hit_spark_checks');
      const x = f.x[i][idx], y = f.y[i][idx] + 8;
      const near = sparkFills.some(p => p.some(([px, py]) => Math.hypot(px - x, py - y) < HIT_SPARK_REACH));
      if (!near) flags.flag('hit_spark_missing', { frame, idx, port: i, hit_idx: j, damage: f.pct[i][j] - f.pct[i][j - 1] });
    }
    // Sword trails: while the game's ring holds two or more samples, a trail is
    // filled out to the blade's tip at the newest one.
    const trailFills = fillPolygons(callsByTag.get('trail') || [], view);
    for (let i = 0; i < NPL; i++) for (const kind of ['trail', 'beam']) {
      const due = trailDue(i, idx, kind);
      if (!due) continue;
      flags.metric('sword_trail_checks');
      const [tx, ty] = due.tip;
      if (!trailFills.some(p => p.some(([px, py]) => Math.hypot(px - tx, py - ty) < SWORD_TRAIL_REACH)))
        flags.flag('sword_trail_missing', { frame, idx, port: i, kind, cid: f.cid[i][idx], state: f.state[i][idx], age: f.age[i][idx] });
    }
    // Framing, through the hosts' own camera at every host shape: every living
    // fighter must be inside the view the camera aims for (it eases toward it,
    // like Melee's, so a fast launch can briefly lead it); and, with every
    // living fighter standing on one level, a platform up to 56 units above
    // them (Battlefield's top one is 54.4) over their stretch of stage must be
    // on the screen actually shown.
    const living = [...Array(NPL).keys()].filter(i => f.state[i][idx] > 13 && !(f.cat && f.cat[i][idx] === 6));
    const levels = living.map(i => f.y[i][idx]);
    const standing = f.air && living.length && Math.max(...levels) - Math.min(...levels) < 10 &&
      living.every(i => !f.air[i][idx] && !capturedName(f.state[i][idx]));
    for (const [w, h, host] of HOST_SIZES) {
      const tv = targetViews[host][idx];
      for (const i of living) {
        flags.metric(`fighter_framing_checks_${host}`);
        const x = (f.x[i][idx] * tv.S + tv.ox), y = (tv.oy - f.y[i][idx] * tv.S);
        if (x < 0 || x > w || y < 0 || y > h)
          flags.flag('fighter_out_of_frame', { frame, idx, host, port: i, px: [x, y] });
      }
      const hv = hostViews[host][idx];
      const left = -hv.ox / hv.S, right = (w - hv.ox) / hv.S, yTop = hv.oy / hv.S, yBottom = (hv.oy - h) / hv.S;
      if (!standing) continue;
      const xs = living.map(i => f.x[i][idx]), top = Math.max(...levels);
      for (const l of geometry.lines) {
        if (!platform(l) || !(l[1] & 1)) continue;
        const px0 = Math.min(l[2], l[4]), px1 = Math.max(l[2], l[4]), py = (l[3] + l[5]) / 2;
        if (px1 < Math.min(...xs) - 30 || px0 > Math.max(...xs) + 30 || py <= top + 5 || py > top + 56) continue;
        flags.metric(`platform_framing_checks_${host}`);
        if (!(py < yTop && py > yBottom && px1 > left && px0 < right))
          flags.flag('platform_out_of_frame', { frame, idx, host, platform: l.slice(2), view: [left, right, yBottom, yTop] });
      }
    }
    const requiredStageCall = bundle.meta.stage === 8 ? 'randall' : null;
    if (requiredStageCall && !globalThis.__liteauditStageCalls.some(call => call.kind === requiredStageCall))
      flags.flag(`${requiredStageCall}_call_missing`, { frame, idx });
    for (const call of globalThis.__liteauditStageCalls) {
      if (call.kind === 'movers') continue;   // superseded by 'collision'
      flags.metric(`${call.kind}_frame_checks`);
      if (call.frame !== frame) flags.flag(`${call.kind}_frame_basis`, { idx, trueFrame: frame, suppliedFrame: call.frame });
      // Randall passing under the stage is behind the landmass: the game shows
      // nothing and drawRandall draws nothing there (buriedPlatform)
      const expectedSegments = call.kind === 'randall' ? (() => {
        const p = stages.randallPlatform(frame), g = stages.collisionGeometry(8, frame);
        if (!p || (g && buriedPlatform(cachedFills(g.lines), p.left[0], p.left[1], p.right[0], p.right[1]))) return [];
        return [[...p.left, ...p.right]];
      })() : [];
      flags.metric(`${call.kind}_segments_checked`, expectedSegments.length);
      const drawnSegments = segments(call.kind === 'randall' ? callsByTag.get('randall') || [] : callsByTag.get('stage') || []);
      const world = drawnSegments.map(([a, b, c, d]) => [(a - view.ox) / view.S, (view.oy - b) / view.S,
        (c - view.ox) / view.S, (view.oy - d) / view.S]);
      for (const segment of expectedSegments) if (!world.some(s => s.every((v, i) => Math.abs(v - segment[i]) < .05)))
        flags.flag(`${call.kind}_geometry`, { frame, idx, expectedSegment: segment });
    }
    if (drawTraces.length < traces) drawTraces.push({ frame, idx, calls: ctx.calls });
  }
  return { ...flags.result(), fallbacks, drawTraces };
}

export async function main() {
  const options = args(), out = outDir(options.out), records = [];
  for (const game of selection(options, out).games) {
    try {
      const truth = readJSON(path.join(out, 'truth', `${game.id}.json.gz`));
      const { bundle, rowFids } = await produce(game, truth, options.producer || 'python', out);
      records.push({ id: game.id, path: game.path, ...checkRender(bundle, rowFids, truth, loadAnimations(bundle, out, options.shard), { every: Number(options.every || 30) }) });
    } catch (error) { records.push({ id: game.id, path: game.path, flags: { audit_error: { count: 1, examples: [{ error: String(error) }] } } }); }
  }
  writeJSON(path.join(out, `render-${options.producer || 'python'}-${String(options.shard || '1/1').replace('/', '-')}.json`), records);
  console.log(`Render: ${records.length} replay reports (findings never set a failing exit status)`);
}
if (direct(import.meta)) await main();
