// Pick replay frames for the side-by-side check, by target type.
//   node pick.mjs --index <index.json> --out <targets.json> [--types shine,stages] [--n 30]
//                 [--exclude old/targets.json,...] [--only id,id]
// Each target: { id, type, label, slp, stage, frame (true Slippi frame), subject: {port} | {item, x, y} | null, why }.
// The choice is mechanical (newest replay first with a qualifying frame), never by looking.
// Every replay is used once. Types take turns, so each requested type is represented;
// once every definition of a type has a frame, the next round finds it again in another game.
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath, pathToFileURL } from 'node:url'
import { register } from 'node:module'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '../../..')
const { deriveFromSlp } = await import(pathToFileURL(path.join(ROOT, 'app/frontend/src/tracker/replays/liteDeriver/index.js')).href)
// the paint modules' own imports (JSON tables, extensionless paths) as the bundler
// resolves them, for movementDust.dustEvents and meleeStages.randallPlatform
register(new URL('../loader.mjs', import.meta.url))
const { dustEvents } = await import(pathToFileURL(path.join(ROOT, 'app/frontend/src/tracker/replays/movementDust.js')).href)
const { randallPlatform } = await import(pathToFileURL(path.join(ROOT, 'app/frontend/src/tracker/replays/meleeStages.js')).href)
const A = {}; const argv = process.argv.slice(2)
for (let i = 0; i < argv.length; i += 2) A[argv[i].replace(/^--/, '')] = argv[i + 1]
if (!A.index || !A.out) { console.error('usage: node pick.mjs --index <index.json> --out <targets.json> [--types a,b] [--n N] [--exclude f.json] [--only id,id]'); process.exit(2) }

const index = JSON.parse(fs.readFileSync(A.index, 'utf8'))
const verOk = v => { const [a, b] = v.split('.').map(Number); return a > 3 || (a === 3 && b >= 18) }   // stage events, item owners
const two = r => r.chars.filter(c => c != null).length === 2 && r.chars.every(c => c == null || c <= 25)   // vanilla fighters only: playback runs the vanilla ISO
const pool = index.filter(r => verOk(r.ver) && two(r)).reverse()
const oldPool = index.filter(r => !verOk(r.ver) && two(r) && +r.ver.split('.')[0] >= 3).reverse()
const cache = new Map()
function bundleOf(p) {
  if (!cache.has(p)) {
    let b = null
    try { b = deriveFromSlp(new Uint8Array(fs.readFileSync(p))) } catch {}
    cache.set(p, b)
    if (cache.size > 16) cache.delete(cache.keys().next().value)
  }
  return cache.get(p)
}
// external (CSS) character ids, as in the replay header
const EXT = { falcon: 0, dk: 1, fox: 2, gw: 3, bowser: 5, link: 6, luigi: 7, mario: 8, marth: 9, ness: 11, peach: 12, pikachu: 13,
  ics: 14, puff: 15, samus: 16, yoshi: 17, sheik: 19, falco: 20, ylink: 21, roy: 23, ganon: 25 }
const F = b => b.frames, N = b => b.meta.n
// a run of `states` for port i: return the idx `into` frames after the run starts (run >= minLen), facing filter
function stateRun(b, i, states, { into = 6, minLen = 12, dir = null, from = 600 } = {}) {
  const f = F(b), st = f.state[i]
  for (let k = from; k < N(b); k++) {
    if (!states.includes(st[k]) || states.includes(st[k - 1])) continue
    let e = k; while (e < N(b) && states.includes(st[e])) e++
    if (e - k < minLen) continue
    const idx = k + into
    if (dir != null && f.dir[i][idx] !== dir) continue
    return idx
  }
  return null
}
// ports whose internal character id is cid
function portsOf(b, cid) { return b.frames.cid.map((c, i) => (c.find(v => v != null) === cid ? i : -1)).filter(i => i >= 0) }
function fighterTarget(cid, states, opts, why) {
  return b => {
    for (const i of portsOf(b, cid)) {
      const idx = stateRun(b, i, states, opts)
      if (idx != null) return { idx, subject: { port: i }, why: `${why}; state ${b.frames.state[i][idx]} facing ${b.frames.dir[i][idx]} age ${b.frames.age[i][idx]}` }
    }
    return null
  }
}
function itemTarget(kinds, why, { stateIn = null, into = 4, box = [-140, 140, -60, 140], near = [55, 45] } = {}) {
  return b => {
    for (const it of b.items || []) {
      if (!kinds.includes(it.t)) continue
      // the first qualifying item; of its frames, the one closest to a fighter
      // (the game camera frames the fighters, so that is the one most on screen)
      let best = null
      for (let k = into; k < it.x.length; k++) {
        if (it.f + k < 400) continue
        if (stateIn && !stateIn.includes(it.s?.[k])) continue
        if (it.x[k] < box[0] || it.x[k] > box[1] || it.y[k] < box[2] || it.y[k] > box[3]) continue
        const idx = it.f + k, xs = b.frames.x.map(r => r[idx]), ys = b.frames.y.map(r => r[idx])
        const d = Math.min(...xs.map((v, i) => Math.abs(it.x[k] - v) < near[0] && Math.abs(it.y[k] - ys[i]) < near[1]
          ? Math.hypot(it.x[k] - v, it.y[k] - ys[i]) : Infinity))
        if (d < Infinity && (!best || d < best.d)) best = { d, k }
      }
      if (best) {
        const k = best.k
        return { idx: it.f + k, subject: { item: it.t, x: it.x[k], y: it.y[k] }, why: `${why}; item ${it.t} state ${it.s?.[k]}, ${best.d.toFixed(1)} from a fighter` }
      }
    }
    return null
  }
}
// shield frames with the stick held a given way for at least `hold` frames (pre-frame joystick)
const shieldTilt = (test, why, { hold = 8, health = null, light = null } = {}) => b => {
  const f = b.frames
  for (let i = 0; i < f.x.length; i++) {
    let run = 0
    for (let k = 600; k < b.meta.n; k++) {
      const ok = f.state[i][k] === 179 && test(f.joyx[i][k], f.joyy[i][k]) && (health == null || health(f.shield[i][k]))
        && (light == null || (f.lt && light(f.lt[i][k])))
      run = ok ? run + 1 : 0
      if (run === hold) return { idx: k, subject: { port: i }, why: `${why}; stick ${f.joyx[i][k].toFixed(2)},${f.joyy[i][k].toFixed(2)} shield ${f.shield[i][k].toFixed(1)} light ${f.lt ? f.lt[i][k] : '-'}` }
    }
  }
  return null
}
// the thrower is cid; the subject is the victim
const throwBy = (cid, states, why) => b => {
  for (const i of portsOf(b, cid)) for (const st of states) {
    const idx = stateRun(b, i, [st], { minLen: 10, into: 5 })
    if (idx != null) return { idx, subject: { port: 1 - i }, why: `${why} state ${st}` }
  }
  return null
}
// any fighter in one of `states`; the subject is that fighter
const anyIn = (states, opts, why) => b => {
  for (let i = 0; i < b.frames.x.length; i++) {
    const idx = stateRun(b, i, states, opts)
    if (idx != null) return { idx, subject: { port: i }, why: `${why}; cid ${b.frames.cid[i][idx]} state ${b.frames.state[i][idx]}` }
  }
  return null
}
// the subject inside the usual camera: over the stage, not far below it
const nearStage = (cid, states, opts, why) => b => {
  for (const i of portsOf(b, cid)) {
    const st = b.frames.state[i]
    for (let k = 600; k < b.meta.n; k++) {
      if (!states.includes(st[k]) || states.includes(st[k - 1])) continue
      let e = k; while (e < b.meta.n && states.includes(st[e])) e++
      if (e - k < opts.minLen) continue
      const idx = Math.min(e - 1, k + opts.into)
      if (Math.abs(b.frames.x[i][idx]) < 75 && b.frames.y[i][idx] > -12)
        return { idx, subject: { port: i }, why: `${why}; state ${st[idx]} at ${b.frames.x[i][idx].toFixed(1)},${b.frames.y[i][idx].toFixed(1)} age ${b.frames.age[i][idx]}` }
    }
  }
  return null
}
const neutral = why => b => (N(b) > 3600 ? { idx: 1800, subject: null, why } : null)
// Yoshi's Story: Randall beside the stage (not hidden under it), a fighter on or
// just above him so the game camera has him in view
const randallBeside = why => b => {
  const f = F(b)
  for (let k = 900; k < N(b); k += 3) {
    const p = randallPlatform(b.meta.start_frame + k)
    if (!p) continue
    const cx = (p.left[0] + p.right[0]) / 2, cy = p.left[1], half = Math.abs(p.right[0] - p.left[0]) / 2
    if (Math.abs(cx) < 64 || Math.abs(cx) > 92 || cy < -16) continue
    if (f.x.some((r, i) => Math.abs(r[k] - cx) < half + 4 && f.y[i][k] - cy > -1 && f.y[i][k] - cy < 14 && f.state[i][k] > 11))
      return { idx: k, subject: null, why: `${why}; platform centre ${cx.toFixed(1)},${cy.toFixed(1)}` }
  }
  return null
}
const stadiumForm = (form, why) => b => {
  const done = (b.stage_state?.stadium || []).find(e => e[0] > 600 && e[1] === 6 && e[2] === form)
  return done ? { idx: done[0] + 240 - b.meta.start_frame, subject: null, why: `${why}: 240 frames after event ${JSON.stringify(done)}` } : null
}
const fodAt = (pickEv, why, after = 200) => b => {
  const e = pickEv((b.stage_state?.fod || []).filter(x => x[0] > 900))
  return e ? { idx: Math.min(N(b) - 1, e[0] - b.meta.start_frame + after), subject: null, why: `${why}: platform ${e[1]} to ${(+e[2]).toFixed(1)} at ${e[0]}, +${after}` } : null
}
// Sword trails (data/hits/<cid>.json `trail`, tools/liteaudit/sword_trails/build.py):
// a frame `into` action frames after a trail window opens in one of `states` (into 2 or
// more: two or three samples), the action frame moving (not frozen in hitlag), the
// fighter over the stage where the game camera frames it.
const TRAILS = Object.fromEntries([6, 18, 20, 26].map(c => [c, JSON.parse(fs.readFileSync(
  path.join(ROOT, 'app/frontend/src/tracker/replays/data/hits', `${c}.json`), 'utf8')).trail]))
const swordSwing = (cid, states, { dir = null, into = 3 } = {}, why) => b => {
  const T = TRAILS[cid], f = F(b)
  for (const i of portsOf(b, cid)) {
    const st = f.state[i], age = f.age[i]
    for (let k = 600; k < N(b); k++) {
      if (!states.includes(st[k]) || st[k - 1] !== st[k] || age[k] === age[k - 1]) continue
      let w = T.states[st[k]]
      if (typeof w === 'number') w = T.states[w]
      if (!w || !w.some(([a]) => Math.floor(age[k]) === a + into)) continue
      if ((dir != null && f.dir[i][k] !== dir) || Math.abs(f.x[i][k]) > 80 || f.y[i][k] < -10) continue
      return { idx: k, subject: { port: i }, why: `${why}; state ${st[k]} age ${age[k]} facing ${f.dir[i][k]}` }
    }
  }
  return null
}
// KO blasts (koBlast.js): `into` frames after a fighter is first in one of `states`
// (DeadDown 0, DeadLeft 1, DeadRight 2) straight from being alive; `ports` keeps
// players on those controller ports (the blast takes the port's colour). The blast
// fills the screen edge, so there is no subject to close in on.
const koAt = (states, into, why, ports = null) => b => {
  const f = F(b)
  for (let i = 0; i < f.x.length; i++) {
    if (ports && !ports.includes(b.meta.players[i]?.physical_port)) continue
    const st = f.state[i]
    for (let k = 600; k + into < N(b); k++) {
      if (!states.includes(st[k]) || !(st[k - 1] > 11)) continue
      return { idx: k + into, subject: null, why: `${why}; player ${i + 1} (port ${(b.meta.players[i]?.physical_port ?? i) + 1}) state ${st[k]} at ${f.x[i][k].toFixed(1)},${f.y[i][k].toFixed(1)}, +${into}` }
    }
  }
  return null
}
// The respawn (invincible.js): `into` frames after Rebirth (12) began, or
// after RebirthWait (13) ended (`after`), the fighter alive throughout.
const respawnAt = (into, why, { after = false } = {}) => b => {
  const f = F(b)
  for (let i = 0; i < f.x.length; i++) {
    const st = f.state[i]
    for (let k = 600; k + into < N(b); k++) {
      if (after ? !(st[k - 1] === 13 && st[k] !== 13) : !(st[k] === 12 && st[k - 1] !== 12)) continue
      if (st.slice(k, k + into + 1).some(s => s <= 11) || (!after && ![12, 13].includes(st[k + into]))) continue
      return { idx: k + into, subject: { port: i }, why: `${why}; state ${st[k + into]} at +${into}` }
    }
  }
  return null
}
// `into` frames after a fighter enters one of `states` (from outside them), still in
// `stay` (default: `states`) then; the subject is the fighter (`subject: false`: none).
// Star and screen KOs (koFlight.js) and what makes a fighter invincible (invincible.js).
const enterAt = (states, into, why, { stay = states, subject = true, from = 600 } = {}) => b => {
  const f = F(b)
  for (let i = 0; i < f.x.length; i++) {
    const st = f.state[i]
    for (let k = from; k + into < N(b); k++) {
      if (!states.includes(st[k]) || states.includes(st[k - 1]) || !(st[k - 1] > 11)) continue
      if (!st.slice(k, k + into + 1).every(s => stay.includes(s))) continue
      return { idx: k + into, subject: subject ? { port: i } : null, why: `${why}; player ${i + 1} state ${st[k]} from ${st[k - 1]}, +${into}` }
    }
  }
  return null
}
// Movement dust (movementDust.js, tools/liteaudit/dust/build.py): `into` frames after a puff of
// `kind` spawns (in one of `states` when given), where the game camera frames it over the stage,
// with no other puff from the same fighter in the 20 frames around it, so the one judged is that one.
// The close-up is centred on the puff (point).
const dustPuff = (kind, into, why, { states = null } = {}) => b => {
  const evs = dustEvents(b), f = F(b)
  for (const e of evs) {
    if (e.kind !== kind || e.idx < 600 || e.idx + into >= N(b)) continue
    const i = f.x.indexOf(e.row.x)
    if (i < 0 || (states && !states.includes(f.state[i][e.idx]))) continue
    if (Math.abs(e.x) > 80 || e.y < -5 || e.y > 60) continue
    if (evs.some(o => o !== e && o.row === e.row && Math.abs(o.idx - e.idx) < 20)) continue
    const idx = e.idx + into
    return { idx, subject: { port: i, point: [e.x, e.y + 5] },
      why: `${why}; puff at idx ${e.idx} (${e.x.toFixed(1)}, ${e.y.toFixed(1)}) facing ${e.facing}, +${into}; state ${f.state[i][e.idx]}` }
  }
  return null
}
const has = (r, ...cs) => cs.some(c => r.chars.includes(c))
const any = () => true
const fox = r => has(r, EXT.fox), falco = r => has(r, EXT.falco), spacie = r => has(r, EXT.fox, EXT.falco)
const stage = id => r => r.stage === id

// The catalogue: [type, id, label, header filter, scan, replay limit]
const DEFS = [
  // --- the reflector (shine): held and starting, both facings, grounded and airborne, Fox and Falco ---
  ['shine', 'fox-shine-ground-right', 'Fox held shine, grounded, facing right', fox, fighterTarget(1, [361], { dir: 1 }, 'SpecialLwLoop')],
  ['shine', 'fox-shine-ground-left', 'Fox held shine, grounded, facing left', fox, fighterTarget(1, [361], { dir: -1 }, 'SpecialLwLoop')],
  ['shine', 'fox-shine-air', 'Fox held shine, airborne', fox, fighterTarget(1, [366], { minLen: 8, into: 4 }, 'SpecialAirLwLoop')],
  ['shine', 'fox-shine-start', 'Fox shine first frames (start effect), grounded', fox, fighterTarget(1, [360], { minLen: 3, into: 1 }, 'SpecialLwStart')],
  ['shine', 'fox-shine-start-air', 'Fox shine first frames (start effect), airborne', fox, fighterTarget(1, [365], { minLen: 3, into: 1 }, 'SpecialAirLwStart')],
  ['shine', 'fox-shine-turn', 'Fox turning around inside a held shine', fox, fighterTarget(1, [364, 369], { minLen: 4, into: 2 }, 'SpecialLwTurn')],
  ['shine', 'fox-shine-reflect', 'Fox reflecting a projectile (reflect flash)', fox, fighterTarget(1, [362, 367], { minLen: 4, into: 2 }, 'SpecialLwHit')],
  ['shine', 'falco-shine-ground', 'Falco held shine, grounded', falco, fighterTarget(22, [361], {}, 'SpecialLwLoop')],
  ['shine', 'falco-shine-air', 'Falco held shine, airborne', falco, fighterTarget(22, [366], { minLen: 8, into: 4 }, 'SpecialAirLwLoop')],
  ['shine', 'falco-shine-start', 'Falco shine first frames (start effect)', falco, fighterTarget(22, [360, 365], { minLen: 3, into: 1 }, 'SpecialLwStart')],
  // --- stages and their moving parts ---
  ['stages', 'battlefield', 'Battlefield, whole stage', stage(31), neutral('30 s in')],
  ['stages', 'dreamland', 'Dream Land, whole stage', stage(28), neutral('30 s in')],
  ['stages', 'fod', 'Fountain of Dreams, side platforms moving', stage(2), fodAt(ev => ev[0], 'first move', 120)],
  ['stages', 'fod-high', 'Fountain of Dreams, a side platform at its highest', stage(2), fodAt(ev => ev.reduce((a, e) => (!a || e[2] > a[2] ? e : a), null), 'highest')],
  ['stages', 'fod-sunk', 'Fountain of Dreams, a side platform fully sunk', stage(2), fodAt(ev => ev.reduce((a, e) => (!a || e[2] < a[2] ? e : a), null), 'lowest')],
  ['stages', 'stadium-start', 'Pokemon Stadium, transformation starting (event 4 + 20)', stage(3), b => {
    const e = (b.stage_state?.stadium || []).find(x => x[0] > 600 && x[1] === 4)
    return e ? { idx: e[0] + 20 - b.meta.start_frame, subject: null, why: `event ${JSON.stringify(e)} + 20` } : null
  }],
  ['stages', 'stadium-transform', 'Pokemon Stadium mid-transformation', stage(3), b => {
    // Slippi's transformation events: 2 start, 3, 4, 5, 6 done. Mid-way = halfway from 4 to 5 of the first one.
    const ev = (b.stage_state?.stadium || []).filter(e => e[0] > 600)
    const four = ev.find(e => e[1] === 4), five = four && ev.find(e => e[1] === 5 && e[0] > four[0])
    return five ? { idx: Math.round((four[0] + five[0]) / 2) - b.meta.start_frame, subject: null, why: `halfway between stadium events ${JSON.stringify(four)} and ${JSON.stringify(five)}` } : null
  }],
  ['stages', 'stadium-end', 'Pokemon Stadium, transformation ending (event 5 + 100)', stage(3), b => {
    const e = (b.stage_state?.stadium || []).find(x => x[0] > 600 && x[1] === 5 && x[2] !== 5)
    return e ? { idx: e[0] + 100 - b.meta.start_frame, subject: null, why: `event ${JSON.stringify(e)} + 100` } : null
  }],
  ['stages', 'stadium-fire', 'Pokemon Stadium, fire form', stage(3), stadiumForm(3, 'fire')],
  ['stages', 'stadium-grass', 'Pokemon Stadium, grass form', stage(3), stadiumForm(4, 'grass')],
  ['stages', 'stadium-rock', 'Pokemon Stadium, rock form', stage(3), stadiumForm(6, 'rock')],
  ['stages', 'stadium-water', 'Pokemon Stadium, water form', stage(3), stadiumForm(9, 'water')],
  ['stages', 'yoshis-shyguys', "Yoshi's Story with Shy Guys", stage(8), itemTarget([210], 'Shy Guy', { into: 30, box: [-90, 90, -20, 120] })],
  ['stages', 'corneria-plain', 'Corneria, whole stage (Great Fox, gun)', stage(7), neutral('30 s in'), 60],
  ['stages', 'corneria', 'Corneria with an Arwing or Great Fox laser', stage(7), itemTarget([234, 235], 'stage ship laser', { box: [-400, 400, -200, 600], near: [60, 45], stateIn: [0, 1] }), 60],
  ['stages', 'corneria-arwing', 'Corneria, an Arwing firing on the stage plane', stage(7), itemTarget([234], 'Arwing laser just fired', { into: 0, box: [-400, 400, -200, 600], near: [80, 60] }), 60],
  ['stages', 'venom-plain', 'Venom, whole stage', stage(22), neutral('30 s in'), 60],
  ['stages', 'venom', 'Venom with an Arwing laser', stage(22), itemTarget([234], 'Arwing laser'), 60],
  ['stages', 'randall', "Yoshi's Story, Randall (the cloud) beside the stage", stage(8), randallBeside('Randall beside the stage')],
  ['stages', 'onett-car', 'An Onett car driving through', stage(9), itemTarget([160], 'car', { stateIn: [2, 3, 4, 5], into: 0 }), 60],
  ['stages', 'onett-edge', 'An Onett car at the edge of the stage', stage(9), b => {
    for (const it of b.items || []) if (it.t === 160) for (let k = 0; k < it.x.length; k++) {
      const idx = it.f + k
      if ([2, 3, 4, 5].includes(it.s?.[k]) && Math.abs(it.x[k]) > 70 && Math.abs(it.x[k]) < 110 && idx > 600 && b.frames.x.some(r => Math.abs(r[idx] - it.x[k]) < 45))
        return { idx, subject: { item: 160, x: it.x[k], y: it.y[k] }, why: `car at x ${it.x[k].toFixed(1)} by a fighter` }
    }
    return null
  }, 60],
  // --- items and projectiles ---
  ['items', 'fox-laser', "Fox's laser", fox, itemTarget([54], 'laser')],
  ['items', 'falco-laser', "Falco's laser", falco, itemTarget([55], 'laser')],
  ['items', 'laser-fired', 'A blaster shot just fired (still growing)', spacie, itemTarget([54, 55], 'laser age 1', { into: 1 })],
  ['items', 'laser-aerial', 'An aerial (angled) blaster shot', spacie, b => {
    for (const it of b.items || []) if ([54, 55].includes(it.t) && it.vy) for (let k = 6; k < it.x.length; k++)
      if (Math.abs(it.vy[k]) > 1 && it.f + k > 400) return { idx: it.f + k, subject: { item: it.t, x: it.x[k], y: it.y[k] }, why: `angled laser vy ${it.vy[k].toFixed(2)}` }
    return null
  }],
  ['items', 'laser-reflected', 'A blaster shot just reflected', spacie, b => {
    for (const it of b.items || []) if ([54, 55].includes(it.t) && it.vx) for (let k = 1; k < it.x.length - 3; k++)
      if (Math.sign(it.vx[k]) !== Math.sign(it.vx[k - 1]) && Math.abs(it.vx[k]) > 0.5 && it.f + k > 400)
        return { idx: it.f + k + 2, subject: { item: it.t, x: it.x[k + 2], y: it.y[k + 2] }, why: `reflected at age ${k}, shown 2 frames after` }
    return null
  }],
  ['items', 'laser-impact', 'A blaster shot on its last frame (impact or expiry)', spacie, b => {
    for (const it of b.items || []) if ([54, 55].includes(it.t) && it.x.length > 6 && it.x.length < 30 && it.f + it.x.length > 400) {
      const k = it.x.length - 1, idx = it.f + k
      if (Math.abs(it.x[k]) > 110 || !b.frames.x.some((r, i) => Math.abs(r[idx] - it.x[k]) < 30 && Math.abs(b.frames.y[i][idx] - it.y[k]) < 30)) continue
      return { idx, subject: { item: it.t, x: it.x[k], y: it.y[k] }, why: `last of ${it.x.length} frames, by a fighter` }
    }
    return null
  }],
  ['items', 'mario-fireball', "Mario's fireball", r => has(r, EXT.mario), itemTarget([48], 'fireball')],
  ['items', 'luigi-fireball', "Luigi's fireball", r => has(r, EXT.luigi), itemTarget([105], 'fireball')],
  ['items', 'samus-missile', "Samus's missile", r => has(r, EXT.samus), itemTarget([95], 'missile in flight', { stateIn: [0, 1] })],
  ['items', 'charge-shot', "Samus's charge shot in flight", r => has(r, EXT.samus), itemTarget([94], 'charge shot', { into: 6 })],
  ['items', 'peach-turnip', "Peach's turnip in flight", r => has(r, EXT.peach), itemTarget([99], 'turnip in flight', { stateIn: [1, 2, 3], into: 10 })],
  ['items', 'thunder', "Pikachu's Thunder bolt", r => has(r, EXT.pikachu), itemTarget([81, 82], 'thunder', { into: 4, box: [-200, 200, -60, 300], near: [40, 200] })],
  ['items', 'arrow', "Link's or Young Link's arrow", r => has(r, EXT.link, EXT.ylink), itemTarget([64, 65], 'arrow', { into: 4 })],
  ['items', 'needle', "Sheik's needles", r => has(r, EXT.sheik), itemTarget([79], 'needle', { into: 3 })],
  ['items', 'peach-turnip-held', 'Peach holding a turnip', r => has(r, EXT.peach), itemTarget([99], 'held turnip', { stateIn: [0], into: 20 })],
  ['items', 'ic-ice', "The Ice Climbers' ice block", r => has(r, EXT.ics), itemTarget([106], 'ice', { into: 12 })],
  ['items', 'pk-thunder', "Ness's PK Thunder and its tail", r => has(r, EXT.ness), itemTarget([69], 'PK Thunder', { into: 15 })],
  // --- grabs, throws and carries (the victim's exact pose is out of scope; that it is drawn, and where, is not) ---
  ['throws', 'throw-forward', 'A forward throw, mid-throw', any, anyIn([219], { minLen: 10, into: 6 }, 'ThrowF')],
  ['throws', 'throw-back', 'A back throw, mid-throw', any, anyIn([220], { minLen: 10, into: 6 }, 'ThrowB')],
  ['throws', 'throw-marth', 'Marth throwing', r => has(r, EXT.marth), throwBy(18, [219, 220, 221, 222], 'Marth throw')],
  ['throws', 'throw-sheik', 'Sheik throwing', r => has(r, EXT.sheik), throwBy(7, [222, 219, 220, 221], 'Sheik throw')],
  ['throws', 'throw-fox-up', "Fox's up-throw", fox, throwBy(1, [221], 'Fox ThrowHi')],
  ['throws', 'dk-cargo', "Donkey Kong's cargo carry (victim on his shoulders)", r => has(r, EXT.dk), b => {
    for (const i of portsOf(b, 3)) {
      const idx = stateRun(b, i, [351, 352, 353, 354, 356], { minLen: 10, into: 6 })
      if (idx != null) return { idx, subject: { port: 1 - i }, why: 'DK cargo walk/wait' }
    }
    return null
  }],
  ['throws', 'yoshi-egg', "A fighter inside Yoshi's egg", r => has(r, EXT.yoshi), anyIn([277, 332], { minLen: 6, into: 3 }, 'egg')],
  // --- effects Watch Lite draws ---
  ['effects', 'firefox-charge', 'Fox charging Fire Fox', fox, nearStage(1, [353, 354], { minLen: 20, into: 15 }, 'SpecialHiHold')],
  ['effects', 'firefox-travel', 'Fox travelling in Fire Fox', fox, nearStage(1, [355, 356], { minLen: 15, into: 8 }, 'SpecialHi')],
  ['effects', 'firebird-charge', 'Falco charging Fire Bird', falco, nearStage(22, [353, 354], { minLen: 20, into: 30 }, 'SpecialHiHold')],
  ['effects', 'firebird-travel', 'Falco travelling in Fire Bird', falco, nearStage(22, [355, 356], { minLen: 15, into: 8 }, 'SpecialHi')],
  ['effects', 'rebirth', 'A fighter waiting on the revival platform', any, anyIn([13], { minLen: 20, into: 12 }, 'RebirthWait')],
  ['effects', 'bowser-fortress', "Bowser's Whirling Fortress (the shell)", r => has(r, EXT.bowser), nearStage(5, [359, 360], { minLen: 30, into: 20 }, 'SpecialHi')],
  ['effects', 'falcon-punch', 'Captain Falcon punching (Falcon Punch)', r => has(r, EXT.falcon), fighterTarget(2, [347, 348], { minLen: 40, into: 50 }, 'SpecialN')],
  // --- sword trails: Marth, Roy, Link and Young Link swings, both facings, ground and air ---
  ['swords', 'marth-fair-right', 'Marth forward air, facing right', r => has(r, EXT.marth), swordSwing(18, [66], { dir: 1 }, 'AttackAirF')],
  ['swords', 'marth-fair-left', 'Marth forward air, facing left', r => has(r, EXT.marth), swordSwing(18, [66], { dir: -1 }, 'AttackAirF')],
  ['swords', 'marth-bair', 'Marth back air', r => has(r, EXT.marth), swordSwing(18, [67], {}, 'AttackAirB')],
  ['swords', 'marth-uair', 'Marth up air', r => has(r, EXT.marth), swordSwing(18, [68], {}, 'AttackAirHi')],
  ['swords', 'marth-dair', 'Marth down air', r => has(r, EXT.marth), swordSwing(18, [69], { into: 2 }, 'AttackAirLw')],
  ['swords', 'marth-nair', 'Marth neutral air', r => has(r, EXT.marth), swordSwing(18, [65], {}, 'AttackAirN')],
  ['swords', 'marth-fsmash', 'Marth forward smash', r => has(r, EXT.marth), swordSwing(18, [60], {}, 'AttackS4')],
  ['swords', 'marth-utilt', 'Marth up tilt', r => has(r, EXT.marth), swordSwing(18, [56], { into: 4 }, 'AttackHi3')],
  ['swords', 'marth-ftilt', 'Marth forward tilt', r => has(r, EXT.marth), swordSwing(18, [53], {}, 'AttackS3')],
  ['swords', 'marth-dtilt', 'Marth down tilt', r => has(r, EXT.marth), swordSwing(18, [57], { into: 2 }, 'AttackLw3')],
  ['swords', 'marth-blade', 'Marth Dancing Blade', r => has(r, EXT.marth), swordSwing(18, [349, 350, 351, 352, 353, 354, 355, 356, 358, 359, 360, 361, 362, 363, 364, 365], {}, 'SpecialS')],
  ['swords', 'roy-fair', 'Roy forward air', r => has(r, EXT.roy), swordSwing(26, [66], {}, 'AttackAirF')],
  ['swords', 'roy-fsmash', 'Roy forward smash', r => has(r, EXT.roy), swordSwing(26, [60], { into: 4 }, 'AttackS4')],
  ['swords', 'roy-ftilt', 'Roy forward tilt or down tilt', r => has(r, EXT.roy), swordSwing(26, [53, 57], {}, 'AttackS3/Lw3')],
  ['swords', 'link-fsmash', 'Link forward smash', r => has(r, EXT.link), swordSwing(6, [60, 341], {}, 'AttackS41/S42')],
  ['swords', 'link-ftilt', 'Link forward tilt or dash attack', r => has(r, EXT.link), swordSwing(6, [53, 50], { into: 2 }, 'AttackS3/Dash')],
  ['swords', 'link-fair', 'Link forward air', r => has(r, EXT.link), swordSwing(6, [66], {}, 'AttackAirF')],
  ['swords', 'ylink-fair', 'Young Link forward air', r => has(r, EXT.ylink), swordSwing(20, [66], {}, 'AttackAirF')],
  ['swords', 'ylink-tilt', 'Young Link forward, up or down tilt', r => has(r, EXT.ylink), swordSwing(20, [53, 56, 57], { into: 2 }, 'AttackS3/Hi3/Lw3')],
  // --- KO blasts: off each side and the bottom, the first flash and the flame after it, ports 3 and 4 ---
  ['ko', 'ko-left-flash', 'KO off the left side, the first flash (+1)', any, koAt([1], 1, 'DeadLeft')],
  ['ko', 'ko-right-flash', 'KO off the right side, the first flash (+2)', any, koAt([2], 2, 'DeadRight')],
  ['ko', 'ko-bottom-flash', 'KO off the bottom, the first flash (+1)', any, koAt([0], 1, 'DeadDown')],
  ['ko', 'ko-left-flame', 'KO off the left side, the flame (+7)', any, koAt([1], 7, 'DeadLeft')],
  ['ko', 'ko-right-flame', 'KO off the right side, the flame (+11)', any, koAt([2], 11, 'DeadRight')],
  ['ko', 'ko-bottom-flame', 'KO off the bottom, the flame (+5)', any, koAt([0], 5, 'DeadDown')],
  ['ko', 'ko-side-late', 'KO off a side, the flame going (+16)', any, koAt([1, 2], 16, 'DeadLeft/Right')],
  ['ko', 'ko-port34', 'KO of a player on port 3 or 4 (its colour), the flame (+8)', any, koAt([0, 1, 2], 8, 'Dead', [2, 3])],
  // --- the respawn: on the platform, then invincible after it ---
  ['respawn', 'respawn-rebirth', 'Respawn: coming down on the platform (Rebirth +45)', any, respawnAt(45, 'Rebirth')],
  ['respawn', 'respawn-wait', 'Respawn: waiting on the platform (Rebirth +70)', any, respawnAt(70, 'RebirthWait')],
  ['respawn', 'respawn-leave', 'Respawn: the first frame off the platform', any, respawnAt(0, 'left RebirthWait', { after: true })],
  ['respawn', 'respawn-fade', 'Respawn: invincible, 4 frames off the platform', any, respawnAt(4, 'left RebirthWait', { after: true })],
  ['respawn', 'respawn-off', 'Respawn: invincible, 8 frames off the platform', any, respawnAt(8, 'left RebirthWait', { after: true })],
  ['respawn', 'respawn-mid', 'Respawn: invincible, 56 frames off the platform', any, respawnAt(56, 'left RebirthWait', { after: true })],
  ['respawn', 'respawn-end', 'Respawn: 121 frames off the platform (invincibility over)', any, respawnAt(121, 'left RebirthWait', { after: true })],
  // --- star KOs: flying into the background, then the twinkle ---
  ['starko', 'star-far', 'Star KO, flying away (+80)', any, enterAt([4, 5], 80, 'DeadUpStar', { subject: false }), 2000],
  ['starko', 'star-farther', 'Star KO, small in the background (+105)', any, enterAt([4, 5], 105, 'DeadUpStar', { subject: false }), 2000],
  ['starko', 'star-end', 'Star KO, at the end of its flight (+125)', any, enterAt([4, 5], 125, 'DeadUpStar', { subject: false }), 2000],
  ['starko', 'star-twinkle', 'Star KO, the twinkle (+133)', any, enterAt([4, 5], 133, 'DeadUpStar', { subject: false }), 2000],
  // --- screen KOs: coming at the camera, on it, falling away ---
  ['screenko', 'screen-coming', 'Screen KO, coming at the camera (+38)', any, enterAt([6, 9], 38, 'DeadUpFall', { stay: [6, 7, 8, 9, 10], subject: false }), 3000],
  ['screenko', 'screen-hit', 'Screen KO, on the camera (+53)', any, enterAt([6, 9], 53, 'DeadUpFall', { stay: [6, 7, 8, 9, 10], subject: false }), 3000],
  ['screenko', 'screen-fall', 'Screen KO, falling away (+72)', any, enterAt([6, 9], 72, 'DeadUpFall', { stay: [6, 7, 8, 9, 10], subject: false }), 3000],
  // --- invincibility: ledge grabs, throws, wall bounces and wall techs ---
  ['flash', 'ledge-on', 'Grabbing the ledge (CliffWait +2)', any, enterAt([253], 2, 'CliffWait')],
  ['flash', 'ledge-off', 'Holding the ledge (CliffWait +9)', any, enterAt([253], 9, 'CliffWait')],
  ['flash', 'ledge-again', 'Holding the ledge (CliffWait +13)', any, enterAt([253], 13, 'CliffWait')],
  ['flash', 'ledge-over', 'Holding the ledge (CliffWait +32)', any, enterAt([253], 32, 'CliffWait')],
  ['flash', 'throw', 'Throwing (+3, the thrower)', any, enterAt([219, 220, 221, 222], 3, 'Throw')],
  ['flash', 'wall-bounce', 'Tumbling into a wall or ceiling (+4)', any, enterAt([247, 248], 4, 'FlyReflect'), 1500],
  // --- movement dust: dashes, run turns, jumps, landings (aerial, wavedash), steps, rolls, ledge jumps ---
  ['dust', 'dust-dash-start', 'Dash dust, just spawned', any, dustPuff('dash', 2, 'dash start (0x3FF)', { states: [20] })],
  ['dust', 'dust-dash', 'Dash dust, a few frames on', any, dustPuff('dash', 8, 'dash start (0x3FF)', { states: [20] })],
  ['dust', 'dust-dash-late', 'Dash dust, fading', any, dustPuff('dash', 15, 'dash start (0x3FF)', { states: [20] })],
  ['dust', 'dust-turn', 'Run turn or brake dust', any, dustPuff('turn', 2, 'run turn / brake (0x401)', { states: [19, 23] })],
  ['dust', 'dust-jump', 'Ground jump dust', any, dustPuff('jump', 4, 'jump (0x402)', { states: [25, 26] })],
  ['dust', 'dust-airjump', 'Double jump puff', any, dustPuff('airjump', 2, 'double jump (0x403)', { states: [27, 28] })],
  ['dust', 'dust-landing', 'Landing dust', any, dustPuff('landing', 1, 'landing (0x404)', { states: [42] })],
  ['dust', 'dust-landing-late', 'Landing dust, later', any, dustPuff('landing', 5, 'landing (0x404)', { states: [42] })],
  ['dust', 'dust-airlanding', 'Aerial landing clouds', any, dustPuff('airlanding', 3, 'aerial landing (0x407)', { states: [70, 71, 72, 73, 74] })],
  ['dust', 'dust-airlanding-late', 'Aerial landing clouds, later', any, dustPuff('airlanding', 10, 'aerial landing (0x407)', { states: [70, 71, 72, 73, 74] })],
  ['dust', 'dust-wavedash', 'Wavedash / special-fall landing clouds', any, dustPuff('airlanding', 4, 'special-fall landing (0x407)', { states: [43] })],
  ['dust', 'dust-step', 'Run step dust', any, dustPuff('step', 3, 'run step (0x3FE)', { states: [21, 22] })],
  ['dust', 'dust-roll', 'Roll dust', any, dustPuff('dash', 4, 'roll (0x3FF)', { states: [233, 234] })],
  ['dust', 'dust-ledge', 'Ledge jump or roll dust', any, dustPuff('dash', 4, 'ledge option (0x3FF)', { states: [258, 259, 261, 263] })],
  // --- shields ---
  ['shields', 'shield-up', 'Shield tilted up (stick up)', any, shieldTilt((x, y) => y > 0.8, 'Guard, stick up')],
  ['shields', 'shield-side', 'Shield tilted sideways (stick left or right)', any, shieldTilt((x, y) => Math.abs(x) > 0.8 && Math.abs(y) < 0.3, 'Guard, stick sideways')],
  ['shields', 'shield-down', 'Shield tilted down (stick down)', any, shieldTilt((x, y) => y < -0.8, 'Guard, stick down')],
  ['shields', 'shield-damaged', 'A small, worn-down shield (low shield health)', any, shieldTilt(() => true, 'Guard, shield health under 30', { health: h => h < 30, hold: 3 })],
  ['shields', 'shield-light', 'A light shield (trigger barely pressed)', any, shieldTilt(() => true, 'Guard, light press', { light: l => l > 0 && l < 60 })],
  ['shields', 'shield-yoshi', "Yoshi's shield (the egg)", r => has(r, EXT.yoshi), fighterTarget(14, [179, 341, 178, 181], { minLen: 4, into: 3 }, 'Guard')],
  // --- fighter bodies (capes, hair and tails are out of scope; the body is not) ---
  ['fighters', 'gw-idle', 'Game & Watch standing idle', r => has(r, EXT.gw), fighterTarget(24, [14], { minLen: 20, into: 10 }, 'Wait')],
  ['fighters', 'marth-wait', 'Marth standing idle', r => has(r, EXT.marth), fighterTarget(18, [14], { minLen: 30, into: 20 }, 'Wait')],
  ['fighters', 'marth-run', 'Marth running', r => has(r, EXT.marth), fighterTarget(18, [21], { minLen: 15, into: 10 }, 'Run')],
  ['fighters', 'marth-fair', 'Marth forward air', r => has(r, EXT.marth), fighterTarget(18, [66], { minLen: 15, into: 8 }, 'AttackAirF')],
  ['fighters', 'roy-wait', 'Roy standing idle', r => has(r, EXT.roy), fighterTarget(26, [14], { minLen: 30, into: 20 }, 'Wait')],
  ['fighters', 'ganon-wait', 'Ganondorf standing idle', r => has(r, EXT.ganon), fighterTarget(25, [14], { minLen: 30, into: 20 }, 'Wait')],
  ['fighters', 'ganon-fall', 'Ganondorf falling', r => has(r, EXT.ganon), fighterTarget(25, [29], { minLen: 15, into: 10 }, 'Fall')],
].map(([type, id, label, header, scan, limit = 400]) => ({ type, id, label, header, scan, limit }))
const TYPES = [...new Set(DEFS.map(d => d.type))]

const only = A.only ? new Set(A.only.split(',').filter(Boolean)) : null
const types = A.types && A.types !== 'all' ? A.types.split(',').filter(Boolean) : TYPES
const unknown = [...types.filter(t => !TYPES.includes(t)), ...[...(only || [])].filter(id => !DEFS.some(d => d.id === id))]
if (unknown.length) { console.error(`unknown type or id: ${unknown.join(', ')}; types are ${TYPES.join(', ')}`); process.exit(2) }
const N_WANTED = +(A.n || (only ? only.size : 30))

const used = new Set()
// replays of earlier runs stay out, so a new run brings new games
for (const f of (A.exclude || '').split(',').filter(Boolean)) for (const t of JSON.parse(fs.readFileSync(f, 'utf8'))) used.add(t.slp)

function find(id, d) {
  let tried = 0
  for (const r of [...pool, ...oldPool]) {
    if (used.has(r.p) || !d.header(r)) continue
    if (++tried > d.limit) break
    const b = bundleOf(r.p)
    if (!b) continue
    let hit = null
    try { hit = d.scan(b, r) } catch { hit = null }
    if (!hit || !(hit.idx >= 0 && hit.idx < b.meta.n)) continue
    used.add(r.p)
    const t = { id, type: d.type, label: d.label, slp: r.p, stage: b.meta.stage, frame: b.meta.start_frame + hit.idx, subject: hit.subject ?? null, why: hit.why }
    console.log(`${id} -> ${path.basename(r.p)} frame ${t.frame} ${JSON.stringify(t.subject)} ${hit.why}`)
    return t
  }
  console.log(`${id} -> NOT FOUND`)
  return null
}

const queues = types.map(type => ({ type, defs: DEFS.filter(d => d.type === type && (!only || only.has(d.id))), next: 0 }))
  .filter(q => q.defs.length)
const T = [], times = new Map(), dead = new Set()
while (T.length < N_WANTED) {
  let progress = false
  for (const q of queues) {
    for (let tries = 0; T.length < N_WANTED && tries < q.defs.length; tries++) {
      const d = q.defs[q.next++ % q.defs.length]
      if (dead.has(d.id)) continue
      const k = (times.get(d.id) || 0) + 1
      const t = find(k === 1 ? d.id : `${d.id}-${k}`, d)
      if (!t) { dead.add(d.id); continue }
      times.set(d.id, k); T.push(t); progress = true
      break
    }
  }
  if (!progress) break
}
fs.writeFileSync(A.out, JSON.stringify(T, null, 1))
console.log(`${T.length} targets (${types.join(', ')})`)
