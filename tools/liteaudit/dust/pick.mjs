// Pick movement-dust frames for the recorder (hit_effects/record.py) and the
// side-by-side check: newest replays first, a few frames per kind, each the frame
// a fighter enters a state whose script spawns dust (build.py DUST), with the
// other fighter far away and no other dust from the same fighter for a while.
//   node tools/liteaudit/dust/pick.mjs --index <replay index.json> --out <targets.json> [--per 1] [--kinds a,b] [--skip N] [--scan 400] [--gap 30]
// The replay index is the side-by-side tool's (index.mjs: [{p, stage, chars, ver}]).
// Each target: { id, type: 'dust', kind, slp, frame, stage, subject: {port, cid}, why }.
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath, pathToFileURL } from 'node:url'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '../../..')
const REPLAYS = path.join(ROOT, 'app/frontend/src/tracker/replays')
const { deriveFromSlp } = await import(pathToFileURL(path.join(REPLAYS, 'liteDeriver/index.js')).href)
const A = {}; const argv = process.argv.slice(2)
for (let i = 0; i < argv.length; i += 2) A[argv[i].replace(/^--/, '')] = argv[i + 1]
if (!A.index || !A.out) { console.error('usage: node pick.mjs --index <index.json> --out <targets.json> [--per N] [--kinds a,b]'); process.exit(2) }
const PER = +(A.per || 1), SKIP = +(A.skip || 0), SCAN = +(A.scan || 400), GAP = +(A.gap || 30)
// the states a kind is entered by (ftCommon action states)
const KIND_STATES = { dash: [20], turnrun: [19], runbrake: [23], jump: [25, 26], airjump: [27, 28], landing: [42],
  airlanding: [70, 71, 72, 73, 74], run: [21] }
const KINDS = (A.kinds || Object.keys(KIND_STATES).join(',')).split(',')
const DUSTY = new Set(Object.values(KIND_STATES).flat())
const VANILLA_STAGE_MAX = 32
const verOk = v => { const [a, b] = v.split('.').map(Number); return a > 3 || (a === 3 && b >= 16) }
const index = JSON.parse(fs.readFileSync(A.index, 'utf8'))
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
  if (!(b.meta.stage <= VANILLA_STAGE_MAX) || b.frames.x.length !== 2) continue
  const f = b.frames, n = b.meta.n
  let used = 0
  for (let k = 200; k < n - GAP - 5 && used < 2; k++) for (let v = 0; v < 2; v++) {
    const st = f.state[v][k]
    if (st === f.state[v][k - 1]) continue
    const kind = KINDS.find(K => KIND_STATES[K].includes(st))
    if (!kind || got[kind].length >= PER) continue
    // alone: the other fighter stays 50+ units away, and this one spawns no other dust for GAP frames
    let alone = true
    for (let j = k - 20; j <= k + GAP && alone; j++) {
      if (Math.abs(f.x[1 - v][j] - f.x[v][j]) < 50) alone = false
      // (a turn while running goes on into the run: its steps are another kind, told apart by generator)
      const next = f.state[v][j]
      if (j > k && DUSTY.has(next) && next !== f.state[v][j - 1] && !(kind === 'turnrun' && (next === 21 || next === 22))) alone = false
      if (j < k && j >= k - 12 && KIND_STATES[kind].includes(f.state[v][j]) && f.state[v][j] !== f.state[v][j - 1]) alone = false
    }
    if (!alone) continue
    const id = `${kind}${got[kind].length ? '-' + (got[kind].length + 1) : ''}`
    got[kind].push({ id, type: 'dust', kind, slp: r.p, frame: b.meta.start_frame + k, stage: b.meta.stage,
      subject: { port: b.meta.players?.[v]?.physical_port ?? v, index: v, cid: f.cid[v][k] },
      why: `state ${f.state[v][k - 1]} -> ${st}, facing ${f.dir[v][k]}, at (${f.x[v][k].toFixed(1)}, ${f.y[v][k].toFixed(1)})` })
    used++
  }
}
const out = KINDS.flatMap(k => got[k])
fs.writeFileSync(A.out, JSON.stringify(out, null, 1))
console.log(`${out.length} targets from ${scanned} replays: ` + KINDS.map(k => `${k} ${got[k].length}`).join(', '))
