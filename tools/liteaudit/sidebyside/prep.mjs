// Add each target's Slippi truth at its frame: every port's x/y/state/cid/facing, and
// the subject's world point (fighter: its position; item: the item's position; or the target's own point).
//   node prep.mjs <targets.json> <targets-ext.json>
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath, pathToFileURL } from 'node:url'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '../../..')
const { deriveFromSlp } = await import(pathToFileURL(path.join(ROOT, 'app/frontend/src/tracker/replays/liteDeriver/index.js')).href)
const [inFile, outFile] = process.argv.slice(2)
if (!inFile || !outFile) { console.error('usage: node prep.mjs <targets.json> <targets-ext.json>'); process.exit(2) }
const targets = JSON.parse(fs.readFileSync(inFile, 'utf8'))
for (const t of targets) {
  const b = deriveFromSlp(new Uint8Array(fs.readFileSync(t.slp)))
  const idx = t.frame - b.meta.start_frame, f = b.frames
  t.n = b.meta.n
  t.ports = f.x.map((_, i) => ({ port: i, x: f.x[i][idx], y: f.y[i][idx], state: f.state[i][idx], cid: f.cid[i][idx], dir: f.dir[i][idx], age: f.age[i][idx] }))
    .filter(p => p.x != null && p.cid != null)
  // truth for the frame check: every port's x/y/state/age over F-60..F+30
  t.truth = {}
  for (let fr = t.frame - 60; fr <= t.frame + 30; fr++) {
    const k = fr - b.meta.start_frame
    if (k < 0 || k >= b.meta.n) continue
    t.truth[fr] = f.x.map((_, i) => [f.x[i][k], f.y[i][k], f.state[i][k], f.age[i][k]])
  }
  // reflector targets also log the effect objects frame by frame around the shot (seq.mjs prints them)
  if (t.type === 'shine') { t.seq_pre = 14; t.seq_post = 14 }
  const s = t.subject
  const p = s && s.port != null ? t.ports.find(q => q.port === s.port) : null
  if (s && s.point) t.point = s.point            // a world point of its own (a dust puff)
  else if (p) t.point = [p.x, p.y + 8]
  else if (s && s.item != null) t.point = [s.x, s.y]
  else t.point = null
}
fs.writeFileSync(outFile, JSON.stringify(targets, null, 1))
console.log(`${targets.length} targets prepared`)
