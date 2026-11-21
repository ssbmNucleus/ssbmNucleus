// Compact, always-loaded item looks for Watch Lite paint, derived from the
// stage-gated item tables (data/items/<kind>.json, baked from the vanilla ISO
// by `stage_bake.py --items`). Re-run after re-baking items:
//   node tools/liteaudit/item_sizes.mjs
// Writes app/frontend/src/tracker/replays/data/itemSizes.json:
//   { "<kind>": [family, hitRadius, bodyRadius, held, byState?] }
// - family: the bake's item family ("fireball", "laser", ... or "authored").
// - hitRadius: world units = the item's most common hitbox radius x its model
//   scale (lbColl scales an item hitbox by the item's scale); 0 = no hitbox.
// - bodyRadius: half its widest ECB extent x scale (the item's own size).
//   Both rounded to 0.01.
// - byState: hit radius per recorded item state, when it varies (the charge
//   levels of Samus's and Mewtwo's shots); 0 = no hitbox in that state.
// - held: a prop held or attached to its fighter, whose silhouette already
//   shows it (blasters, bows, capes, bats, Game & Watch props...). The name
//   rule follows stageSim/stage16.js's held props, except the two that are
//   seen on their own: the common Hammer item (only Kirby's hammer is part of
//   his pose) and Yoshi's egg, which hides the swallowed fighter in game.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const DATA = path.join(ROOT, 'app/frontend/src/tracker/replays/data');
const HELD = /(Blaster|Bow|Kirby_Hammer|Mario_Cape|DrMario_Sheet|Ness_Bat|Ness_Yoyo|Peach_Parasol|Peach_Toad|PeachToad|NeedleHeld|IceClimber_GumStrings|GameWatchChefPan|HShot|GBeam|Seak_Chain)$/;
const out = {};
for (const file of fs.readdirSync(path.join(DATA, 'items')).filter(f => /^\d+\.json$/.test(f)).sort((a, b) => parseInt(a) - parseInt(b))) {
  const d = JSON.parse(fs.readFileSync(path.join(DATA, 'items', file), 'utf8'));
  if (!Number.isInteger(d.kind)) continue;
  const radii = new Map();
  for (const anim of Object.values(d.animations || {})) for (const hits of Object.values(anim.frames || {}))
    for (const h of hits) if (h[4] > 0) radii.set(h[4], (radii.get(h[4]) || 0) + 1);
  const scale = Number.isFinite(d.scale) ? d.scale : 1;
  const hit = [...radii].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0]?.[0] || 0;
  const body = Math.max(0, ...(d.ecb || []).map(Math.abs)) / 2;
  const held = d.family === 'attached' || HELD.test(d.name || '');
  const r = v => Math.round(v * scale * 100) / 100;
  const byState = (d.states || []).map(a => {
    let m = 0;
    for (const hits of Object.values(d.animations?.[a]?.frames || {})) for (const h of hits) m = Math.max(m, h[4]);
    return r(m);
  });
  out[d.kind] = [d.family || 'authored', r(hit), r(body), held ? 1 : 0];
  if (new Set(byState).size > 1) out[d.kind].push(byState);
}
fs.writeFileSync(path.join(DATA, 'itemSizes.json'), JSON.stringify(out) + '\n');
console.log(`itemSizes.json: ${Object.keys(out).length} kinds`);
