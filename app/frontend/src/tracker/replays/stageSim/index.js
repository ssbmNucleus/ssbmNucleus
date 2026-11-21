// Collision simulator plug-in boundary. all.js registers validated paths.
//
// Simulator signature: (bundle, idx) => result | null
// - idx indexes the finalized bundle; true Slippi frame = meta.start_frame+idx.
// - Source-audited modules export collisionLag (see collisionTiming.js). It
//   describes callback-write -> collision-refresh delay, NOT a dump-clock
//   correction. Never advance idx or the RNG cursor to fit a geometry capture.
// - bundle.frames contains leader-port x/y/air/state/cid arrays and, when the
//   producer supplies it, seed[port][idx] (uint32). Never assume a missing seed
//   means zero. Current JS derivation forwards FrameArrays.seed; older/cache
//   producers may omit it. Check availability before claiming exactness.
// - Use the whole seed/position history, with a WeakMap cache per bundle and
//   checkpoints for seeking. Results must not depend on previous paint calls.
// - null means unavailable (missing seeds, prefix, unsupported replay, etc.).
// - Recorded FoD/Stadium stage_state events are authoritative inputs. Consume
//   them, or return null to keep their existing renderer.
// - result.lines: [[lineId, flags, x0,y0,x1,y1], ...], in WORLD coordinates.
//   IDs are the original dump MapLine indices; flags low nibble = current kind
//   (1 floor, 2 ceiling, 4/8 wall); bit 8 = drop-through. Only emit active lines.
// - Optional result.floors / result.platforms: [[x0,y0,x1,y1], ...] for synthetic
//   surfaces with no MapLine ID. These draw as solid/drop-through floors.
// - result.toggledLines: [[lineId, enabled], ...]. False removes a base line;
//   true needs either an existing base line or geometry in result.lines.
// - replace:true discards the base; otherwise result.lines replace equal IDs
//   and add to the deterministic base. complete:true suppresses ground trails.
//   For legacy authored stages the base becomes the dump's known static lines
//   when a result is available; the old inferred surfaces are not merged in.
// - Optional main is a CLOSED, non-self-intersecting decorative polygon. It is
//   never used as floor truth. Changed/toggled geometry clears the old main
//   unless the simulator supplies its own; paint traces the body fill from the
//   active lines anyway (liteStageInference.solidFills), main is its fallback.
// RNG: rng.js owns setupCursor(GameStart) and frameCursor(final pre + input
// tail + earlier ground draws). Proc priorities ascend, then p_link/creation.
// Priority-1/10 consumers must supply their known intervening draw counts;
// the helper refuses to infer those from another frame's resettable stream.

const registry = new Map()
const defaults = new Map()
export function simFor(stageId) { return registry.get(Number(stageId)) || defaults.get(Number(stageId)) || null }

// Built-ins remain available underneath a scoped host/test override. Explicit
// overrides still reject duplicates and disposing one restores the built-in.
export function registerDefaultStageSim(stageId, simulator) {
  const id = Number(stageId)
  if (!Number.isInteger(id) || typeof simulator !== 'function') throw new TypeError('Invalid default stage simulator')
  if (defaults.has(id)) throw new Error(`Stage ${id} already has a default simulator`)
  defaults.set(id, simulator)
}

export function registerStageSim(stageId, simulator) {
  if (typeof simulator !== 'function') throw new TypeError('Stage simulator must be a function')
  const id = Number(stageId)
  if (!Number.isInteger(id)) throw new TypeError('Stage ID must be an integer')
  if (registry.has(id)) throw new Error(`Stage ${id} already has a simulator`)
  registry.set(id, simulator)
  return () => { if (registry.get(id) === simulator) registry.delete(id) }
}

export function applyStageSimulation(base, result) {
  if (!result) return base
  const byId = new Map((result.replace ? [] : base?.lines || []).map(l => [l[0], l]))
  for (const line of result.lines || []) byId.set(line[0], line)
  for (const [id, enabled] of result.toggledLines || []) if (!enabled) byId.delete(id)
  const lines = [...byId.values()]
  let syntheticId = -1000000
  for (const s of result.floors || []) lines.push([syntheticId--, 1, ...s])
  for (const s of result.platforms || []) lines.push([syntheticId--, 257, ...s])
  const changed = result.replace || result.lines?.length || result.toggledLines?.length
  return {
    main: result.main || (changed ? [] : base?.main || []), lines,
    floors: lines.filter(l => l[1] & 1).map(l => l.slice(2)),
    partial: !result.complete, source: 'simulator', covered: true,
    ...(result.fillSets ? { fillSets: result.fillSets } : {}),
  }
}
