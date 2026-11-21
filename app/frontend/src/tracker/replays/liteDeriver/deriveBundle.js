import { SlpError } from './slpParse.js'
import { sliceStageState } from './window.js'
import { ATTACK_NAMES, CHAR_NAMES, CHAR_STATE_MIN, DAMAGE_STATES, DOWN_STATES,
  GRABBED, GUARD, SHIELDSTUN, STAGE_EDGE, STAGE_NAMES, THROWN, TUMBLE,
  _CLIFF, _EXT_TO_INT } from './constants.js'

function category(state, airborne) {
  if (state <= 10) return 6
  if (DAMAGE_STATES.has(state) || GRABBED.has(state) || THROWN.has(state)
      || DOWN_STATES.has(state) || state === TUMBLE) return 4
  if (GUARD.has(state) || state === SHIELDSTUN) return 3
  if (_CLIFF.has(state)) return 5
  if ((state >= 44 && state <= 74) || state >= CHAR_STATE_MIN) return 2
  return airborne ? 1 : 0
}

function series(a, lo, hi, fallback = 0, present = null) {
  // Plain arrays keep JSON serialization portable (typed arrays stringify as
  // objects). Copy only the requested slice, without rounding float32 values.
  const out = new Array(hi - lo + 1)
  for (let i = lo; i <= hi; i++) out[i - lo] = present && !present[i] ? null : a == null ? fallback : a[i]
  return out
}

// The game's light-shield depth (fp lightshield_amount, ftCo_Guard.c): the
// analog trigger above 0.3, scaled to 0..1; a lighter-than-0.3 reading keeps
// the last depth; a fresh guard entry (GuardOn 178 / GuardReflect 182 from
// outside a guard) starts it at 0 again, and the frames after shieldstun
// (181 -> 181, 181 -> 179) do not read the trigger.
const GUARDING = new Set([178, 179, 181, 182])
function lightshield(trigger, lo, hi, state) {
  if (trigger == null) return null
  const out = new Array(hi - lo + 1)
  let last = 0
  // A released trigger holds the last depth, including a press before lo.
  // Future frames cannot affect this slice, but its entire prefix can.
  for (let i = 0; i <= hi; i++) {
    const s = state?.[i], p = i > 0 ? state?.[i - 1] : null
    if ((s === 178 || s === 182) && !GUARDING.has(p)) last = 0
    let v = p === 181 && (s === 181 || s === 179) ? -1 : ((trigger[i] || 0) - 0.3) / 0.7
    if (v < 0) v = last
    else if (v > 1) v = 1
    last = v
    if (i >= lo) {
      const depth = v * 100, floor = Math.floor(depth)
      // Python round uses ties-to-even; Math.round would change half depths.
      out[i - lo] = depth - floor === 0.5 ? floor + floor % 2 : Math.round(depth)
    }
  }
  return out
}

function formInfo(cid, lo, hi) {
  let sheik = 0, zelda = 0, first = null
  if (cid) for (const c of cid) {
    if (c === 7) { sheik++; first ??= 'Sheik' }
    else if (c === 19) { zelda++; first ??= 'Zelda' }
  }
  if (!sheik || !zelda) return { form: null, name: null }
  const letters = new Array(hi - lo + 1)
  for (let i = lo; i <= hi; i++) letters[i - lo] = cid[i] === 7 ? 'S' : cid[i] === 19 ? 'Z' : '.'
  // Counter.most_common breaks ties by first appearance, across the full game.
  return { form: letters.join(''), name: sheik === zelda ? first : sheik > zelda ? 'Sheik' : 'Zelda' }
}

const CHANNELS = {
  x: 'x', y: 'y', pct: 'pct', stk: 'stocks', air: 'airborne', state: 'state',
  move: 'lastAttack', dir: 'dir', joyx: 'joyX', joyy: 'joyY', cstickx: 'cX',
  csticky: 'cY', btn: 'buttons', shield: 'shield', cid: 'cid', age: 'age',
  // RNG seed per pre-frame (v5 only): stage simulators replay Melee's
  // "random" hazards from it (see stageSim/).
  seed: 'seed', pre_state: 'preState', seed_order: 'seedOrder',
}
const FOLLOWER = { x: 'x', y: 'y', state: 'state', cid: 'cid', age: 'age', dir: 'dir', air: 'airborne', shield: 'shield',
  seed: 'seed', pre_state: 'preState', seed_order: 'seedOrder' }

export function deriveBundle(parsed, { lo = 0, hi = parsed.n - 1 } = {}) {
  if (parsed.version[0] < 2) throw new SlpError('unsupported: pre-2.0')
  // A valid header with no events still has a useful, empty bundle. Clamping
  // also keeps reversed/outside windows from allocating negative-size arrays.
  lo = parsed.n ? Math.max(0, Math.min(parsed.n - 1, Math.trunc(lo))) : 0
  hi = parsed.n ? Math.max(lo, Math.min(parsed.n - 1, Math.trunc(hi))) : -1
  const n = hi - lo + 1, start = parsed.firstFrame + lo, end = parsed.firstFrame + hi
  const frames = Object.fromEntries(Object.keys(CHANNELS).map(k => [k, []]))
  if (parsed.ports.some(p => p.leader.hitlag != null)) frames.hitlag = []
  // who landed the last hit and its hitstun: the hit sparks (hitSparks.js)
  frames.hitby = []
  if (parsed.ports.some(p => p.leader.hitstun != null)) frames.hitstun = []
  frames.cat = []; frames.form = []; frames.lt = []
  const players = [], followers = []
  for (let i = 0; i < parsed.ports.length; i++) {
    const { leader, follower } = parsed.ports[i], p = parsed.start.players[i]
    const css = CHAR_NAMES[p.extChar] ?? `ext${p.extChar}`
    const { form, name } = formInfo(leader.cid, lo, hi)
    // physical_port: the controller port (0-3), which the game colours by;
    // cpu: a computer player (the game draws its KO blast grey)
    players.push({ port_index: i, physical_port: p.port, cpu: p.type === 1, char: p.extChar, char_name: name ?? css,
      css_char: css, costume: p.costume || 0, transforms: form !== null, team: p.team ?? null,
      code: p.code || null, tag: p.name || null })
    for (const [key, source] of Object.entries(CHANNELS)) {
      const fallback = key === 'dir' ? 1 : key === 'cid' ? (_EXT_TO_INT[p.extChar] ?? p.extChar) : 0
      frames[key].push(series(leader[source], lo, hi, fallback))
    }
    if (frames.hitlag) frames.hitlag.push(series(leader.hitlag, lo, hi))
    // a physical port in the replay; the bundle keeps player indices (-1: none)
    const byPort = new Map(parsed.start.players.map((pl, k) => [pl.port, k]))
    frames.hitby.push(series(leader.hitBy, lo, hi, 6).map(p => byPort.get(p) ?? -1))
    if (frames.hitstun) frames.hitstun.push(series(leader.hitstun, lo, hi))
    const cats = new Array(n)
    for (let f = lo; f <= hi; f++) cats[f - lo] = category(leader.state[f], leader.airborne?.[f])
    frames.cat.push(cats); frames.form.push(form); frames.lt.push(lightshield(leader.trigger, lo, hi, leader.state))
    if (follower) {
      const row = { of: i }
      if (follower.hitlag != null) row.hitlag = series(follower.hitlag, lo, hi)
      for (const [key, source] of Object.entries(FOLLOWER)) {
        const pre = ['seed', 'pre_state', 'seed_order'].includes(key)
        row[key] = series(follower[source], lo, hi, key === 'cid' ? 11 : key === 'dir' ? 1 : 0,
          pre ? (follower.seedOrder ?? new Uint8Array(parsed.n)) : follower.present)
      }
      // Nana gets hit too: her percent, hitstun and attacker, for the hit sparks
      row.pct = series(follower.pct, lo, hi, 0, follower.present)
      if (follower.hitstun != null) row.hitstun = series(follower.hitstun, lo, hi, 0, follower.present)
      row.hitby = series(follower.hitBy, lo, hi, 6, follower.present).map(p => p == null ? null : byPort.get(p) ?? -1)
      followers.push(row)
    }
  }
  if (followers.length) frames.fol = followers
  // Single-row channels follow the existing port-major windowing contract.
  if (parsed.frameSeeds) frames.frame_seed = [series(parsed.frameSeeds, lo, hi)]
  if (parsed.sceneFrames) frames.scene_frame = [series(parsed.sceneFrames, lo, hi)]
  const items = []
  for (const t of parsed.items) {
    const a = Math.max(start, t.start), b = Math.min(end, t.start + t.x.length - 1)
    if (b < a) continue
    const item = { t: t.type, o: t.owner, f: a - start }
    // born before the window: where it first appeared, so its age is known
    // (PK Thunder's tail and Pikachu's bolt blink and cycle by age)
    if (t.start < a) item.born = t.start - start
    for (const [key, source] of [['x', 'x'], ['y', 'y'], ['d', 'dir'], ['s', 'state'], ['vx', 'vx'], ['vy', 'vy']]) {
      item[key] = series(t[source], a - t.start, b - t.start)
    }
    // Additive v5 channels: o remains the original birth owner for existing
    // consumers; owner follows reflection/pickup changes in physical ports.
    for (const [key, source] of [['lifetime', 'lifetime'], ['subtype', 'subtype'],
      ['face', 'face'], ['launched', 'launched'], ['charge', 'charge'], ['owner', 'owners']]) {
      if (t[source] != null) item[key] = series(t[source], a - t.start, b - t.start)
    }
    if (t.owners != null) item.port = item.owner.map(owner => parsed.start.players.findIndex(p => p.port === owner))
    items.push(item)
  }
  const stage = parsed.start.stage
  const bundle = {
    meta: { v: 5, finalized: true, deriver: 'lite-js-1', slp_version: parsed.version.join('.'),
      // A byte buffer has no filename. A caller with a file can attach it here.
      file: '', stage, stage_name: STAGE_NAMES[stage] ?? `stage ${stage}`,
      stage_edge: STAGE_EDGE[stage] ?? 70, start_frame: start, start_seed: parsed.start.seed ?? null, n, fps: 60,
      players, teams: !!parsed.start.isTeams, attack_names: { ...ATTACK_NAMES },
      ...(parsed.start.itemFrequency != null ? { item_frequency: parsed.start.itemFrequency } : {}) },
    frames, conversions: {}, items,
  }
  const stageState = sliceStageState(parsed.stage, start, end)
  if (Object.keys(stageState).length) bundle.stage_state = stageState
  return bundle
}
