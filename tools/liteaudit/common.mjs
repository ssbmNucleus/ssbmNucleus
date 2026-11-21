import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync } from 'node:zlib';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const DEFAULT_OUT = path.join(ROOT, 'app/scratch/liteaudit/harness');
export const REPLAYS = path.join(ROOT, 'app/frontend/src/tracker/replays');
export function args(argv = process.argv.slice(2)) {
  const result = {};
  for (let i = 0; i < argv.length; i++) {
    if (!argv[i].startsWith('--')) throw new Error(`Expected --option, got ${argv[i]}`);
    const key = argv[i].slice(2);
    result[key] = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
  }
  return result;
}
export function outDir(value = DEFAULT_OUT) {
  const result = path.resolve(value), rel = path.relative(DEFAULT_OUT, result);
  if (rel.startsWith('..') || path.isAbsolute(rel)) throw new Error(`Output must be under ${DEFAULT_OUT}`);
  fs.mkdirSync(result, { recursive: true });
  return result;
}
export function readJSON(file) {
  const bytes = fs.readFileSync(file);
  return JSON.parse(file.endsWith('.gz') ? gunzipSync(bytes) : bytes);
}
export function writeJSON(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value, (_, v) => ArrayBuffer.isView(v) ? [...v] : v, 2));
  fs.renameSync(tmp, file);
}
export function selection(options, out) {
  const manifest = readJSON(options.manifest || path.join(out, options.full ? 'corpus.json' : 'golden.json'));
  const [i, n] = String(options.shard || '1/1').split('/').map(Number);
  if (!Number.isInteger(i) || !Number.isInteger(n) || i < 1 || i > n) throw new Error('Shard must be i/N (1-based)');
  // Shard BEFORE eligibility filtering, exactly as the Python stages do.
  let games = manifest.games.filter((_, idx) => idx % n === i - 1);
  if (options.limit) games = games.slice(0, Number(options.limit));
  return { manifest, games: games.filter(g => g.eligible) };
}
export class Flags {
  constructor() { this.checks = {}; this.metrics = {}; }
  flag(check, example = {}, count = 1) {
    const row = this.checks[check] ||= { count: 0, examples: [] };
    row.count += count;
    if (row.examples.length < 8) row.examples.push(example);
  }
  metric(key, count = 1) { this.metrics[key] = (this.metrics[key] || 0) + count; }
  result() { return { flags: this.checks, metrics: this.metrics }; }
}
let derive;
export async function produce(game, truth, producer, out) {
  if (producer === 'python') {
    if (truth.python_error || !truth.bundle) throw new Error(truth.python_error || 'Python bundle unavailable');
    return { bundle: readJSON(path.join(out, 'python', `${game.id}.json.gz`)), rowFids: truth.row_fids };
  }
  if (producer !== 'js') throw new Error('--producer must be js or python');
  derive ||= (await import(pathToFileURL(path.join(REPLAYS, 'liteDeriver/index.js')).href)).deriveFromSlp;
  const bundle = await derive(new Uint8Array(fs.readFileSync(game.path)));
  return { bundle, rowFids: null };
}
export const trueFrame = (bundle, rowFids, idx) => rowFids?.[idx] ?? bundle.meta.start_frame + idx;
export const different = (a, b, tol = 0) => typeof a === 'number' && typeof b === 'number'
  ? !Number.isFinite(a) || !Number.isFinite(b) || Math.abs(a - b) > tol + 1e-7 : a !== b;
export const FLOAT_FIELDS = new Set(['x', 'y', 'pct', 'shield', 'age', 'joyx', 'joyy', 'cstickx', 'csticky']);
export function itemFrames(items, startOf = t => t.f) {
  const map = new Map();
  for (const [track, it] of items.entries()) {
    for (let k = 0; k < it.x.length; k++) {
      const idx = startOf(it) + k;
      if (!map.has(idx)) map.set(idx, []);
      map.get(idx).push({ t: it.t, o: it.o, x: it.x[k], y: it.y[k], s: it.s?.[k], d: it.d?.[k],
        vx: it.vx?.[k], vy: it.vy?.[k], spawn: it.spawn, track });
    }
  }
  return map;
}
// Bundle tracks omit spawn ids. Match the multiset by type/owner, nearest
// position, and consume each candidate once so duplicates cannot hide ghosts.
export function matchItems(expected, actual) {
  const compatible = (e, a) => e.t === a.t && e.o === a.o &&
    ['x', 'y', 'd', 's'].every(k => !different(e[k], a[k], k === 'x' || k === 'y' ? .05 : 0));
  // Simultaneous items can have identical positions but different states. A
  // maximum compatible matching avoids inventing deltas from array ordering.
  const assigned = new Map();
  const visit = (ei, seen) => {
    for (let ai = 0; ai < actual.length; ai++) {
      if (seen.has(ai) || !compatible(expected[ei], actual[ai])) continue;
      seen.add(ai);
      if (!assigned.has(ai) || visit(assigned.get(ai), seen)) { assigned.set(ai, ei); return true; }
    }
    return false;
  };
  expected.forEach((_, ei) => visit(ei, new Set()));
  const usedExpected = new Set(assigned.values());
  const unused = new Set(actual.map((_, i) => i).filter(i => !assigned.has(i)));
  const pairs = [...assigned].map(([ai, ei]) => [expected[ei], actual[ai]]), missing = [];
  for (const [ei, e] of expected.entries()) {
    if (usedExpected.has(ei)) continue;
    let best = null, distance = Infinity;
    for (const i of unused) {
      const a = actual[i];
      if (a.t !== e.t || a.o !== e.o) continue;
      const d = Math.abs(a.x - e.x) + Math.abs(a.y - e.y);
      if (d < distance) { distance = d; best = i; }
    }
    if (best === null) missing.push(e);
    else { unused.delete(best); pairs.push([e, actual[best]]); }
  }
  return { pairs, missing, extra: [...unused].map(i => actual[i]) };
}
export function direct(meta) { return process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === meta.url; }
