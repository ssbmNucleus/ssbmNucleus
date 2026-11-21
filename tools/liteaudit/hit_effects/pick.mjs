// Pick hit frames for the hit-effect recorder (record.py) and the side-by-side
// check: newest replays first, a few frames per kind of hit.
//   node tools/liteaudit/hit_effects/pick.mjs --index <replay index.json> --out <targets.json> [--per 2] [--kinds a,b] [--skip N] [--scan 400]
// The replay index is the side-by-side tool's (index.mjs: [{p, stage, chars, ver}]).
// Kinds: the element of the attacker's hitbox nearest the victim (fighter tables,
// data/fighters), weak/strong by knockback (hitstun = 0.4 x kb; strong >= 180 kb,
// PlCo ftCommonData +0x3F0), shield hits, throws and projectiles; or (by --kinds) techs:
// tech, techroll, walltech, walljumptech, ceiltech (entering states 199-204).
// Each target: { id, type: 'hits', kind, slp, frame, subject: {port}, attacker, why, truth }.
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath, pathToFileURL } from 'node:url'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '../../..')
const REPLAYS = path.join(ROOT, 'app/frontend/src/tracker/replays')
const { deriveFromSlp } = await import(pathToFileURL(path.join(REPLAYS, 'liteDeriver/index.js')).href)
const A = {}; const argv = process.argv.slice(2)
for (let i = 0; i < argv.length; i += 2) A[argv[i].replace(/^--/, '')] = argv[i + 1]
if (!A.index || !A.out) { console.error('usage: node pick.mjs --index <index.json> --out <targets.json> [--per N] [--kinds a,b]'); process.exit(2) }
const PER = +(A.per || 2), SKIP = +(A.skip || 0), SCAN = +(A.scan || 400)
const KINDS = (A.kinds || 'normal,strong,slash,fire,electric,dark,ice,shield,throw,projectile').split(',')
const ELEMENT = { 0: 'normal', 1: 'fire', 2: 'electric', 3: 'slash', 5: 'ice', 13: 'dark' }
// techs (--kinds tech,techroll,...): the frame a fighter enters the tech state
const TECH = { 199: 'tech', 200: 'techroll', 201: 'techroll', 202: 'walltech', 203: 'walljumptech', 204: 'ceiltech' }

const tables = new Map()
function table(cid) {
  if (!tables.has(cid)) {
    let t = null
    try { t = JSON.parse(fs.readFileSync(path.join(REPLAYS, `data/fighters/${cid}.json`), 'utf8')) } catch {}
    if (t) for (const [st, v] of Object.entries(t.hitboxes)) if (typeof v === 'number') t.hitboxes[st] = t.hitboxes[v]
    tables.set(cid, t)
  }
  return tables.get(cid)
}
// active hitboxes of fighter a for the hit landing on idx: its own state on idx,
// or, if that is already a reaction (a trade), the attack it was in one frame earlier
function spheres(f, a, k) {
  for (const [st, age] of [[f.state[a][k], f.age[a][k]], [f.state[a][k - 1], f.age[a][k - 1] + 1]]) {
    const move = table(f.cid[a][k])?.hitboxes?.[st]
    const rows = move?.frames?.[Math.round(age)]
    if (rows?.length) return rows.map(([id, , dy, dx, r, dmg]) => ({ id, x: f.x[a][k] + f.dir[a][k] * dx, y: f.y[a][k] + dy, r, dmg,
      element: move.elements?.[Math.round(age)]?.find(h => h[0] === id)?.[1] ?? 0 }))
  }
  return []
}
const index = JSON.parse(fs.readFileSync(A.index, 'utf8'))
const verOk = v => { const [a, b] = v.split('.').map(Number); return a > 3 || (a === 3 && b >= 16) }
// replays the vanilla ISO can play: vanilla characters (external ids <= 25) on a
// vanilla stage (<= 32; m-ex stages are numbered past them and leave playback black)
const VANILLA_STAGE_MAX = 32
const pool = index.filter(r => verOk(r.ver) && r.chars.filter(c => c != null).length === 2 && r.chars.every(c => c == null || c <= 25) &&
  r.stage != null && r.stage <= VANILLA_STAGE_MAX).reverse().slice(SKIP)
const got = Object.fromEntries(KINDS.map(k => [k, []]))
const done = () => KINDS.every(k => got[k].length >= PER)
let scanned = 0
for (const r of pool) {
  if (done() || scanned > SCAN) break
  scanned++
  let b
  try { b = deriveFromSlp(new Uint8Array(fs.readFileSync(r.p))) } catch { continue }
  if (!(b.meta.stage <= VANILLA_STAGE_MAX)) continue
  const f = b.frames, n = b.meta.n
  const used = new Set()
  for (let k = 200; k < n - 40; k++) for (let v = 0; v < f.x.length; v++) {
    const a = 1 - v
    if (f.x.length !== 2 || used.size >= 3) continue
    let kind = null, why = ''
    const dmg = f.pct[v][k] - f.pct[v][k - 1]
    const guarding = [178, 179, 181, 182].includes(f.state[v][k - 1]) && [179, 181, 182].includes(f.state[v][k])
    if (TECH[f.state[v][k]] && f.state[v][k - 1] !== f.state[v][k]) { kind = TECH[f.state[v][k]]; why = `state ${f.state[v][k - 1]} -> ${f.state[v][k]}` }
    else if (guarding && f.shield[v][k] < f.shield[v][k - 1] - 1.5 && f.hitlag?.[v]?.[k] > 0) { kind = 'shield'; why = `shield ${f.shield[v][k - 1].toFixed(1)} -> ${f.shield[v][k].toFixed(1)}` }
    else if (dmg > 0.5 && f.state[v][k - 1] >= 239 && f.state[v][k - 1] <= 243) { kind = 'throw'; why = `thrown ${f.state[v][k - 1]} -> ${f.state[v][k]}` }
    else if (dmg > 0.5 && f.hitlag?.[v]?.[k] > 0) {
      const hs = spheres(f, a, k)
      if (!hs.length) { kind = 'projectile'; why = `attacker state ${f.state[a][k]} has no hitbox` }
      else {
        const vx = f.x[v][k], vy = f.y[v][k] + 8
        const h = hs.reduce((m, s) => Math.hypot(s.x - vx, s.y - vy) < Math.hypot(m.x - vx, m.y - vy) ? s : m)
        kind = ELEMENT[h.element] || `element${h.element}`
        if (kind === 'normal' && f.hitstun?.[v]?.[k] >= 72) kind = 'strong'
        why = `element ${h.element} hitbox ${h.id} dmg ${h.dmg}; hitstun ${f.hitstun?.[v]?.[k]}`
      }
    }
    if (!kind || !got[kind] || got[kind].length >= PER || used.has(kind)) continue
    used.add(kind)
    const frame = b.meta.start_frame + k
    const truth = {}
    for (let fr = frame - 60; fr <= frame + 30; fr++) {
      const j = fr - b.meta.start_frame
      if (j >= 0 && j < n) truth[fr] = f.x.map((_, i) => [f.x[i][j], f.y[i][j], f.state[i][j], f.age[i][j]])
    }
    const id = `${kind}-${got[kind].length + 1}`
    got[kind].push({ id, type: 'hits', kind, slp: r.p, stage: b.meta.stage, frame, subject: { port: v }, attacker: a,
      chars: b.meta.players.map(p => p.char_name), why: TECH[f.state[v][k]] ? `${b.meta.players[v].char_name} techs (${kind}): ${why}`
        : `${b.meta.players[a].char_name} hits ${b.meta.players[v].char_name}: ${why}; move ${f.move[a][k]} state ${f.state[a][k]} age ${f.age[a][k]}`,
      ports: f.x.map((_, i) => ({ port: i, x: f.x[i][k], y: f.y[i][k], state: f.state[i][k], cid: f.cid[i][k], dir: f.dir[i][k], age: f.age[i][k] })),
      point: [f.x[v][k], f.y[v][k] + 8], truth })
    console.log(`${id}: ${path.basename(r.p)} frame ${frame} ${got[kind].at(-1).why}`)
  }
}
const out = KINDS.flatMap(k => got[k])
fs.writeFileSync(A.out, JSON.stringify(out, null, 1))
console.log(`${out.length} targets from ${scanned} replays; missing: ${KINDS.filter(k => got[k].length < PER).map(k => `${k} ${got[k].length}/${PER}`).join(', ') || 'none'}`)
