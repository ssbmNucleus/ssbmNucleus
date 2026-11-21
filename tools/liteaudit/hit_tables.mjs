// Derive the small tables the hit sparks read (hitSparks.js) from the ISO bakes
// in data/fighters (stage_bake.py --fighters) and data/items. Re-run after
// re-baking fighters or items.
//   node tools/liteaudit/hit_tables.mjs
// Writes, under app/frontend/src/tracker/replays/data/:
//   hits/<cid>.json  {cid, states: {state: runs | state}}: a fighter's hitboxes
//                    by action state; runs [[first frame, last frame,
//                    [[dx, dy, radius, element], ...]], ...] where consecutive
//                    action frames have the same hitboxes; dx along the facing,
//                    dy up, around the fighter's position, in whole units (a
//                    spark needs no finer), the radius to 0.1; a number is a
//                    state with exactly the same runs. Lazy, per fighter
//                    (stageData.ensureReplayHitData), ~7 KB each. The `trail`
//                    and `beam` keys (sword and Beam Sword trails,
//                    tools/liteaudit/sword_trails/build.py) and `hold` (the
//                    item-hold hand, tools/liteaudit/held_items/build.py) are
//                    carried over.
//   hitElements.json {kind: element}: item kinds whose hitboxes are not element
//                    0 (normal), the most common element over their frames.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const DATA = path.join(ROOT, 'app/frontend/src/tracker/replays/data')
const r0 = v => Math.round(v), r1 = v => Math.round(v * 10) / 10
const numbered = dir => fs.readdirSync(dir).filter(f => /^\d+\.json$/.test(f)).sort((a, b) => parseInt(a) - parseInt(b))

fs.mkdirSync(path.join(DATA, 'hits'), { recursive: true })
let bytes = 0
for (const file of numbered(path.join(DATA, 'fighters'))) {
  const d = JSON.parse(fs.readFileSync(path.join(DATA, 'fighters', file), 'utf8'))
  const table = d.hitboxes, states = {}, seen = new Map()
  for (const state of Object.keys(table).sort((a, b) => a - b)) {
    const move = typeof table[state] === 'number' ? table[table[state]] : table[state]
    const runs = []
    for (const f of Object.keys(move.frames || {}).map(Number).sort((a, b) => a - b)) {
      const rows = move.frames[f]
      if (!rows.length) continue
      // [id, z, dy, dx, radius, ...]; the element is the hitbox's own (elements[frame])
      const boxes = rows.map(([id, , dy, dx, radius]) =>
        [r0(dx), r0(dy), r1(radius), move.elements?.[f]?.find(h => h[0] === id)?.[1] ?? 0])
      const last = runs.at(-1)
      if (last && last[1] === f - 1 && JSON.stringify(last[2]) === JSON.stringify(boxes)) last[1] = f
      else runs.push([f, f, boxes])
    }
    if (!runs.length) continue
    const sig = JSON.stringify(runs)
    states[state] = seen.has(sig) ? seen.get(sig) : (seen.set(sig, Number(state)), runs)
  }
  const out = path.join(DATA, 'hits', `${d.cid}.json`)
  const { trail, beam, hold } = fs.existsSync(out) ? JSON.parse(fs.readFileSync(out, 'utf8')) : {}
  const text = JSON.stringify({ cid: d.cid, states, trail, beam, hold })
  fs.writeFileSync(out, text + '\n')
  bytes += text.length + 1
}

const items = {}
for (const file of numbered(path.join(DATA, 'items'))) {
  const d = JSON.parse(fs.readFileSync(path.join(DATA, 'items', file), 'utf8'))
  const count = new Map()
  for (const anim of Object.values(d.animations || {})) {
    for (const rows of Object.values(anim.frames || {})) {
      // [id, x, y, z, radius, damage, ?, angle, growth, set, base, element, joint, ?]
      for (const h of rows) count.set(h[11], (count.get(h[11]) || 0) + 1)
    }
  }
  const top = [...count].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0]
  if (top && top[0] !== 0) items[d.kind] = top[0]
}
fs.writeFileSync(path.join(DATA, 'hitElements.json'), JSON.stringify(items) + '\n')
console.log(`hits/: ${numbered(path.join(DATA, 'fighters')).length} fighters, ${bytes} bytes; hitElements.json: ${Object.keys(items).length} item kinds`)
