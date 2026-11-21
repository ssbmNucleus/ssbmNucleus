// Render Watch Lite's picture of one replay frame for each requested fixed camera
// (no camera smoothing: the camera is set to match the game's), stacked in one PNG.
//   node wlshot.mjs <job.json> <out.png> --lib <paintlib.js> --cache <dir> [--python <exe>] [--chrome <exe>]
// job.json = { slp, frame, views: [{ cx, cy, S, w, h }] }
// --cache holds the animation packs (anims/), the browser profile and the page's job scripts.
import fs from 'node:fs'; import path from 'node:path'; import { execFileSync } from 'node:child_process'
import { pathToFileURL, fileURLToPath } from 'node:url'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '../../..')
const [jobPath, outPng, ...rest] = process.argv.slice(2)
const A = {}
for (let i = 0; i < rest.length; i += 2) A[rest[i].replace(/^--/, '')] = rest[i + 1]
if (!jobPath || !outPng || !A.lib || !A.cache) { console.error('usage: node wlshot.mjs <job.json> <out.png> --lib <paintlib.js> --cache <dir> [--python <exe>] [--chrome <exe>]'); process.exit(2) }
const R = path.join(ROOT, 'app/frontend/src/tracker/replays')
const PY = A.python || path.join(ROOT, 'app/venv/Scripts/python.exe')
const CHROME = A.chrome || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  path.join(process.env.LOCALAPPDATA || '', 'Google/Chrome/Application/chrome.exe'),
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
].find(p => fs.existsSync(p))
if (!CHROME) { console.error('no Chrome or Edge found; pass --chrome <exe>'); process.exit(2) }
const cache = path.resolve(A.cache), animDir = path.join(cache, 'anims'), jobDir = path.join(cache, 'jobs')
fs.mkdirSync(jobDir, { recursive: true })

const spec = JSON.parse(fs.readFileSync(jobPath, 'utf8'))
const { deriveFromSlp } = await import(pathToFileURL(path.join(R, 'liteDeriver/index.js')).href)
const bundle = JSON.parse(JSON.stringify(deriveFromSlp(new Uint8Array(fs.readFileSync(spec.slp))), (_, v) => ArrayBuffer.isView(v) ? [...v] : v))
const idx = spec.frame - bundle.meta.start_frame
const cids = new Set()
for (const row of bundle.frames.cid) for (const c of row) if (c != null) cids.add(c)
for (const fo of bundle.frames.fol || []) for (const c of fo.cid) if (c != null) cids.add(c)
execFileSync(PY, ['-B', path.join(HERE, 'anims.py'), '--out', animDir, ...[...cids].map(String)], { stdio: 'pipe' })
const packs = {}
for (const c of cids) {
  const p = path.join(animDir, `${c}.json`)
  packs[c] = fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : {}
}
const stage = bundle.meta.stage, data = { stages: {}, fighters: {}, items: {}, hits: {} }
const sp = path.join(R, 'data/stages', `${stage}.json`)
if (fs.existsSync(sp)) data.stages[stage] = JSON.parse(fs.readFileSync(sp, 'utf8'))
for (const c of cids) {
  const fp = path.join(R, 'data/fighters', `${c}.json`)
  if (fs.existsSync(fp)) data.fighters[c] = JSON.parse(fs.readFileSync(fp, 'utf8'))
  const hp = path.join(R, 'data/hits', `${c}.json`)
  if (fs.existsSync(hp)) data.hits[c] = JSON.parse(fs.readFileSync(hp, 'utf8'))
}
for (const f of fs.readdirSync(path.join(R, 'data/items'))) data.items[parseInt(f)] = JSON.parse(fs.readFileSync(path.join(R, 'data/items', f), 'utf8'))
const charmaps = JSON.parse(fs.readFileSync(path.join(ROOT, 'app/backend/tracker/tools/charmaps.json'), 'utf8'))
const jobJs = path.join(jobDir, `job-${process.pid}-${Date.now()}.js`)
fs.writeFileSync(jobJs, 'window.JOB=' + JSON.stringify({ bundle, packs, charmaps, data, idx, views: spec.views }))
const W = Math.max(...spec.views.map(v => v.w)), H = spec.views.reduce((a, v) => a + v.h, 0)
const q = new URLSearchParams({ job: pathToFileURL(jobJs).href, lib: pathToFileURL(path.resolve(A.lib)).href })
const page = pathToFileURL(path.join(HERE, 'page.html')).href + '?' + q
try {
  execFileSync(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--allow-file-access-from-files', `--user-data-dir=${path.join(cache, 'chrome-profile')}`, '--virtual-time-budget=30000',
    `--window-size=${W},${H}`, `--screenshot=${path.resolve(outPng)}`, page], { stdio: 'pipe' })
} finally { fs.unlinkSync(jobJs) }
console.log('wrote', outPng, `${spec.views.length} views, frame ${spec.frame} (idx ${idx}), stage ${stage}`)
