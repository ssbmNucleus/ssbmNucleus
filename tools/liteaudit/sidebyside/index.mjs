// Header index of a Slippi replay folder: stage, external character ids, version, size.
//   node index.mjs --root <replay folder> --out <cache>/index-<name>.json
// Reads the first 1 KB of every .slp in the folder and in its direct subfolders
// (Slippi's monthly folders), never deeper. Entries already in --out are reused
// by path, so only new replays are opened on a rerun.
import fs from 'node:fs'; import path from 'node:path'
const A = {}; const argv = process.argv.slice(2)
for (let i = 0; i < argv.length; i += 2) A[argv[i].replace(/^--/, '')] = argv[i + 1]
if (!A.root || !A.out) { console.error('usage: node index.mjs --root <replay folder> --out <index.json>'); process.exit(2) }
const root = A.root.replace(/\\/g, '/').replace(/\/+$/, '')
const old = new Map()
try { for (const r of JSON.parse(fs.readFileSync(A.out, 'utf8'))) old.set(r.p, r) } catch {}

function header(p) {
  try {
    const fd = fs.openSync(p); const b = Buffer.alloc(1024); fs.readSync(fd, b, 0, 1024, 0); fs.closeSync(fd)
    // raw element starts at 15; 0x35 event-sizes payload, then 0x36 GameStart
    const raw = 15
    if (b[raw] !== 0x35) return null
    const gp = raw + b[raw + 1] + 1
    if (b[gp] !== 0x36) return null
    const ver = [b[gp + 1], b[gp + 2], b[gp + 3]]
    const stage = b.readUInt16BE(gp + 0x13)
    const chars = []
    for (let i = 0; i < 4; i++) {
      const o = gp + 0x65 + i * 0x24
      chars.push(b[o + 1] === 3 ? null : b[o])
    }
    return { p, stage, chars, ver: ver.join('.'), size: fs.statSync(p).size }
  } catch { return null }
}

const files = []
for (const ent of fs.readdirSync(root, { withFileTypes: true })) {
  if (ent.isFile() && ent.name.endsWith('.slp')) files.push(`${root}/${ent.name}`)
  else if (ent.isDirectory()) {
    let names
    try { names = fs.readdirSync(`${root}/${ent.name}`) } catch { continue }
    for (const n of names) if (n.endsWith('.slp')) files.push(`${root}/${ent.name}/${n}`)
  }
}
files.sort()      // Slippi names games Game_YYYYMMDDTHHMMSS, so path order is date order
let opened = 0
const out = []
for (const p of files) {
  let r = old.get(p)
  if (!r) { r = header(p); opened++ }
  if (r) out.push(r)
}
fs.mkdirSync(path.dirname(path.resolve(A.out)), { recursive: true })
fs.writeFileSync(A.out, JSON.stringify(out))
console.log(`${out.length} replays indexed (${opened} newly read) from ${root}`)
