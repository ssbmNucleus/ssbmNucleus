import { surfaceYAt, STAGES, collisionGeometry, moverSegments, stadiumGeometry, randallPlatform } from './meleeStages'
import { simFor, applyStageSimulation } from './stageSim/index.js'
import './stageSim/all.js'

// One geometry decision for painting and grounded-fit validation. Simulators
// get first refusal before any ground trail. Keep recorded FoD/Stadium events
// and the existing Corneria/Great Bay fallback until their ports are ready.
export function stageGeometryAt(bundle, idx) {
  const id = bundle.meta.stage, frame = bundle.meta.start_frame + idx
  const baked = collisionGeometry(id, frame)
  let geometry = baked
  if (!geometry || geometry.legacy) {
    const st = STAGES[id]
    const ps = id === 3 ? stadiumGeometry(bundle.stage_state?.stadium, idx) : null
    const dy = st?.anchored ? stageAnchorDy(bundle, st, idx) : 0
    const fod = fodPlatformY(bundle, stageStateAt(bundle, idx), idx)
    const main = (ps?.main || st?.main || []).map(([x, y]) => [x, y + dy])
    const lines = []
    let lineId = -1
    for (let k = 0; k < main.length; k++) {
      const a = main[k], b = main[(k + 1) % main.length], dx = b[0] - a[0]
      // Legacy authored silhouettes run left->right across the top. Never
      // count the reversed underside as a floor merely because it is flat.
      const floor = dx > 0 && Math.abs((b[1] - a[1]) / dx) <= 1.5
      lines.push([lineId--, floor ? 1 : 2, ...a, ...b])
    }
    // The authored platform list lost its line kinds and directions. Where an
    // entry lies on a solid floor of a body the dump's static collision knows
    // (Great Bay's left platform), draw that body from the dump instead.
    const bodies = !ps && !dy ? staticBodies(baked) : []
    const used = new Set()
    for (const pf of (ps ? ps.platforms || [] : st?.platforms || [])) {
      const body = bodies.find(b => b.floors.some(f => onFloor(f, pf)))
      if (body) { used.add(body); continue }
      const left = pf[0][0] < 0 && pf[1][0] < 0
      const right = pf[0][0] > 0 && pf[1][0] > 0
      const y = left ? fod?.left : right ? fod?.right : null
      lines.push([lineId--, 257, pf[0][0], (y ?? pf[0][1]) + dy, pf[1][0], (y ?? pf[1][1]) + dy])
    }
    for (const body of used) lines.push(...body.lines)
    for (const s of ps?.extra || []) lines.push([lineId--, 1, ...s])
    geometry = { main, lines, floors: lines.filter(l => l[1] & 1).map(l => l.slice(2)),
      partial: !st || !!ps?.unknown, source: 'legacy', covered: !!st, ...(ps?.fills && !dy ? { fillPolys: ps.fills } : {}) }
  }
  // The old full DAT path remains available beyond the short live dump of
  // Poke Floats. This is explicitly a legacy fallback, not verified coverage.
  if (id === 23 && !geometry.covered) {
    const floors = moverSegments(id, frame) || []
    geometry = { ...geometry, lines: floors.map((s, i) => [-i - 1, 1, ...s]), floors,
      partial: !floors.length, source: 'legacy-movers' }
  }
  const simulate = simFor(id)
  if (simulate) {
    const result = simulate(bundle, idx)
    // Authored fallbacks have synthetic IDs. Once a real port is available,
    // merge into the dump's independently known base so its original line IDs
    // can replace/remove surfaces without leaving duplicate fallback floors.
    if (result) geometry = applyStageSimulation(baked?.legacy ? baked : geometry, result)
  }
  // Randall's cloud and line are still drawn by drawRandall in each host. Include
  // it in floor truth without drawing the line twice here.
  if (id === 8 && geometry.source !== 'simulator') {
    const cloud = randallPlatform(frame)
    const lines = geometry.lines.filter(l => l[0] !== 0)
    if (cloud) geometry = { ...geometry, lines,
      floors: [...lines.filter(l => l[1] & 1).map(l => l.slice(2)), [...cloud.left, ...cloud.right]] }
  }
  // The body fill comes from the SAME active lines that are stroked, whatever
  // produced them (bake, simulator or authored fallback). The bake's `main`
  // is only a fallback: it is static, so simulators had to drop it (FoD and
  // Stadium lost their fill), and its flat underside drew every stage as a
  // slab reaching its lowest point.
  // A simulator may split them into pieces it knows are separate bodies
  // (Stadium's base and each terrain layer), each traced on its own; every
  // polygon is wound the same way, so the nonzero fill is their union.
  // An authored fallback may give its bodies as outlines outright.
  const fills = geometry.fillPolys && geometry.source === 'legacy' ? geometry.fillPolys.map(wound)
    : (geometry.fillSets || [geometry.lines]).flatMap(set => cachedFills(set))
  if (!fills.length && geometry.main?.length >= 4) fills.push(geometry.main)
  return { ...geometry, fills }
}

// Groups of the dump's static lines (joined at shared vertices) that hold a
// wall or ceiling: solid bodies whose position the dump knows for certain.
function staticBodies(baked) {
  const solid = (baked?.lines || []).filter(l => (l[1] & SOLID_KINDS) && !(l[1] & DROP_THROUGH))
  const key = (x, y) => `${Math.round(x * 100)},${Math.round(y * 100)}`
  const parent = solid.map((_, i) => i), at = new Map()
  const find = i => parent[i] === i ? i : (parent[i] = find(parent[i]))
  solid.forEach((l, i) => { for (const k of [key(l[2], l[3]), key(l[4], l[5])]) {
    if (at.has(k)) parent[find(i)] = find(at.get(k)); else at.set(k, i)
  } })
  const groups = new Map()
  solid.forEach((l, i) => { const r = find(i); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(l) })
  return [...groups.values()].filter(g => g.some(l => l[1] & BODY_KINDS))
    .map(lines => ({ lines, floors: lines.filter(l => (l[1] & SOLID_KINDS) === FLOOR) }))
}
// An authored segment [[x0,y0],[x1,y1]] lying on a floor line (within .05).
function onFloor(f, [[x0, y0], [x1, y1]]) {
  const lo = Math.min(f[2], f[4]), hi = Math.max(f[2], f[4])
  if (Math.min(x0, x1) > hi - 0.5 || Math.max(x0, x1) < lo + 0.5 || f[2] === f[4]) return false
  const yAt = x => f[3] + (f[5] - f[3]) * (Math.max(lo, Math.min(hi, x)) - f[2]) / (f[4] - f[2])
  return Math.abs(yAt(x0) - y0) < 0.05 && Math.abs(yAt(x1) - y1) < 0.05
}

// Solid (not drop-through) collision lines traced end to end into polygons.
// Melee stores each line with its solid side on the right: floors run left to
// right, the ceilings of an underside right to left, so a landmass is a
// clockwise loop. Closed bodies are found first: from each line, follow that
// direction, sharpest right turn first (it keeps to the edge of one body),
// backing out of dead ends until the start comes round again. A dead end at a
// fork is a stub hanging off the outline (Stadium's pit edges where a
// transformation's terrain continues the floor; Venom's wing tips beside its
// hull). What is left is traced greedily the same way (a line stored against
// the flow is taken reversed only when nothing else continues; a trace that
// comes back to a vertex it passed cuts that loop off whole). It is open:
// - at the bottom of a pedestal or body (FoD, Yoshi's Story), the acid line
//   (Brinstar) or street level (Onett): closed by dropping both ends to a base
//   BASE units under its lowest point or, failing that, straight between its
//   ends, whichever first agrees with its own lines (body under every floor,
//   none under an underside). If neither does it is only stroked: a missing
//   fill is better than a wrong one.
// - floors alone, starting and ending on one closed body: its new top (Stadium's
//   terrain while it grows over the old floor), closed like the above.
// - floors alone, hanging off a body or spanning two: a wing, bridge or deck
//   with nothing under it (Venom's wing tips, Brinstar's middle bridge, whose
//   gap walls face into the gap, Rainbow Cruise's decks): only stroked.
// - floors alone, touching nothing: a ground (Kongo Jungle 64, Flat Zone,
//   Mute City's track, 94 units and wider) gets a band BASE units thick under
//   it; anything narrower is a platform whose drop-through bit a simulator
//   table omits (Stadium's side platforms, 30 wide) and is only stroked.
// Shared vertices are joined at 0.01 units. Polygons are wound one way, so a
// nonzero fill is their union: no vanilla stage nests one solid loop inside
// another, while Stadium's old and new terrain overlap mid-transformation.
// The work is bounded for any collision set (custom stages can be large): the
// loop search only walks lines that can lie on a loop (strongly connected
// components of the line graph), iteratively, under a step budget, and a
// candidate is only probed when that is cheap. Past the budget the stage is
// stroked with no fill at all: fail closed to the outline.
const SOLID_KINDS = 15, DROP_THROUGH = 256, FLOOR = 1, CEILING = 2, BODY_KINDS = 14
const BASE = 5, PROBE = 0.3, GROUND_WIDTH = 60
const LOOP_STEPS = 200000, PROBE_WORK = 400000
function insidePolygon(p, x, y) {
  let c = false
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const [xi, yi] = p[i], [xj, yj] = p[j]
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c
  }
  return c
}
// Does a closed candidate put solid where these lines say solid is?
function agrees(poly, lines) {
  for (const l of lines) {
    const dx = l[4] - l[2], dy = l[5] - l[3], kind = l[1] & SOLID_KINDS
    if (Math.abs(dy) > Math.abs(dx) || Math.abs(dx) < 1) continue
    for (const t of [0.25, 0.5, 0.75]) {
      const mx = l[2] + dx * t, my = l[3] + dy * t
      if (kind === FLOOR && !insidePolygon(poly, mx, my - PROBE)) return false
      if (kind === CEILING && (insidePolygon(poly, mx, my - PROBE) || !insidePolygon(poly, mx, my + PROBE))) return false
    }
  }
  return true
}
function signedArea(poly) {   // twice the area, positive counter-clockwise
  let area = 0
  for (let k = 0, j = poly.length - 1; k < poly.length; j = k++) area += (poly[j][0] - poly[k][0]) * (poly[j][1] + poly[k][1])
  return area
}
function wound(poly) {
  return signedArea(poly) < 0 ? [...poly].reverse() : poly
}
export function solidFills(lines, { loopSteps = LOOP_STEPS } = {}) {
  const solid = (lines || []).filter(l => (l[1] & SOLID_KINDS) && !(l[1] & DROP_THROUGH))
  if (!solid.length) return []
  const key = (x, y) => `${Math.round(x * 100)},${Math.round(y * 100)}`
  const starts = new Map(), ends = new Map()
  const add = (m, k, i) => { if (!m.has(k)) m.set(k, []); m.get(k).push(i) }
  solid.forEach((l, i) => { add(starts, key(l[2], l[3]), i); add(ends, key(l[4], l[5]), i) })
  const degree = k => (starts.get(k)?.length || 0) + (ends.get(k)?.length || 0)
  const used = new Uint8Array(solid.length), out = []
  const turn = (a, b) => {
    const dx = a[4] - a[2], dy = a[5] - a[3], ex = b[4] - b[2], ey = b[5] - b[3]
    return Math.atan2(dx * ey - dy * ex, dx * ex + dy * ey)
  }
  // Closed bodies first: follow the stored direction from a line, sharpest
  // right turn first, backing out of dead ends, until the start comes round
  // again. A dead end at a fork is a stub, not the outline: Stadium's pit
  // edges hang off the floor where a transformation's terrain continues it.
  const comp = loopComponents(solid, starts, key), budget = { left: loopSteps }
  const cycleFrom = i => {
    const home = key(solid[i][2], solid[i][3]), path = [i], tried = new Set([i])
    // a path home never leaves the line's component
    const options = j => {
      const l = solid[j]
      return (starts.get(key(l[4], l[5])) || []).filter(n => !used[n] && !tried.has(n) && comp[n] === comp[i])
        .sort((a, b) => turn(l, solid[a]) - turn(l, solid[b]))
    }
    if (key(solid[i][4], solid[i][5]) === home) return path
    const stack = [{ opts: options(i), at: 0 }]   // one frame per line on the path
    while (stack.length) {
      if (--budget.left < 0) return null
      const top = stack[stack.length - 1]
      if (top.at >= top.opts.length) { stack.pop(); path.pop(); continue }
      const n = top.opts[top.at++]
      tried.add(n); path.push(n)
      if (key(solid[n][4], solid[n][5]) === home) return path
      stack.push({ opts: options(n), at: 0 })
    }
    return null
  }
  const loops = []   // vertex keys of every closed body
  const closed = poly => {
    if (poly.length < 3 || Math.abs(signedArea(poly)) <= 1e-6) return
    out.push(wound(poly)); loops.push(new Set(poly.map(p => key(...p))))
  }
  for (let i = 0; i < solid.length; i++) {
    if (used[i] || comp[i] < 0) continue
    const cycle = cycleFrom(i)
    if (budget.left < 0) return []
    if (!cycle) continue
    for (const j of cycle) used[j] = 1
    closed(cycle.map(j => [solid[j][2], solid[j][3]]))
  }
  // What is left is open, traced greedily the same way
  const trace = i => {
    let chain = [solid[i]]
    let [x0, y0, x1, y1] = solid[i].slice(2)
    let pts = [[x0, y0], [x1, y1]]
    const seen = new Map([[key(x0, y0), 0], [key(x1, y1), 1]])
    used[i] = 1
    for (;;) {
      const k = key(x1, y1), dx = x1 - x0, dy = y1 - y0
      let best = null, bestTurn = Infinity
      const options = [...(starts.get(k) || []).map(j => [j, false]), ...(ends.get(k) || []).map(j => [j, true])]
      for (const [j, rev] of options) {
        if (used[j]) continue
        const l = solid[j], ex = rev ? l[2] - l[4] : l[4] - l[2], ey = rev ? l[3] - l[5] : l[5] - l[3]
        const t = Math.atan2(dx * ey - dy * ex, dx * ex + dy * ey) + (rev ? 10 : 0)
        if (t < bestTurn) { bestTurn = t; best = [j, rev] }
      }
      if (!best) break
      const [j, rev] = best, l = solid[j]
      used[j] = 1; chain.push(l)
      x0 = x1; y0 = y1
      ;[x1, y1] = rev ? [l[2], l[3]] : [l[4], l[5]]
      const s = seen.get(key(x1, y1))
      if (s === undefined) { seen.set(key(x1, y1), pts.length); pts.push([x1, y1]); continue }
      // back at pts[s]: chain[s..] closes a body; the path continues from there
      closed(pts.slice(s))
      for (const p of pts.slice(s + 1)) seen.delete(key(...p))
      pts = pts.slice(0, s + 1); chain = chain.slice(0, s)
    }
    if (!chain.length) return
    const first = pts[0], last = pts[pts.length - 1], a = key(...first), b = key(...last)
    if (a === b) { closed(pts); return }
    if (!chain.some(l => l[1] & BODY_KINDS)) {
      if (degree(a) === 1 && degree(b) === 1) {
        // a ground touching nothing: a BASE-thick band under it
        const xs = pts.map(p => p[0])
        if (xs.reduce((m, x) => Math.max(m, x), -Infinity) - xs.reduce((m, x) => Math.min(m, x), Infinity) >= GROUND_WIDTH)
          out.push(wound([...pts, ...[...pts].reverse().map(([x, y]) => [x, y - BASE])]))
        return
      }
      // the new top of a body it starts and ends on (Stadium's terrain while
      // it grows over the old floor); a wing, bridge or deck with a free end,
      // or between two bodies, has nothing under it
      if (!loops.some(v => v.has(a) && v.has(b))) return
    }
    // probing costs lines x vertices; a chain too long to check is only stroked
    if (chain.length * (pts.length + 2) > PROBE_WORK) return
    const base = pts.reduce((m, p) => Math.min(m, p[1]), Infinity) - BASE
    const dropped = [...pts, [last[0], base], [first[0], base]]
    const poly = agrees(dropped, chain) ? dropped : agrees(pts, chain) ? pts : null
    if (poly && poly.length >= 3 && Math.abs(signedArea(poly)) > 1e-6) out.push(wound(poly))
  }
  // chain starts first (nothing ends where they begin), then whatever is left
  solid.forEach((l, i) => { if (!used[i] && !(ends.get(key(l[2], l[3])) || []).some(j => j !== i)) trace(i) })
  solid.forEach((_, i) => { if (!used[i]) trace(i) })
  return out
}

// Lines that can lie on a closed loop: the strongly connected components of the
// line graph (a line leads to the lines starting where it ends), by iterative
// Tarjan. comp[i] is the component id, or -1 for a line on no loop.
function loopComponents(solid, starts, key) {
  const n = solid.length, index = new Int32Array(n).fill(-1), low = new Int32Array(n), comp = new Int32Array(n).fill(-1)
  const onStack = new Uint8Array(n), stack = [], next = j => starts.get(key(solid[j][4], solid[j][5])) || []
  let counter = 0, comps = 0
  for (let r = 0; r < n; r++) {
    if (index[r] >= 0) continue
    const work = [[r, 0]]
    index[r] = low[r] = counter++; stack.push(r); onStack[r] = 1
    while (work.length) {
      const top = work[work.length - 1], [v] = top, succ = next(v)
      if (top[1] < succ.length) {
        const w = succ[top[1]++]
        if (index[w] < 0) { index[w] = low[w] = counter++; stack.push(w); onStack[w] = 1; work.push([w, 0]) }
        else if (onStack[w]) low[v] = Math.min(low[v], index[w])
        continue
      }
      work.pop()
      if (work.length) { const u = work[work.length - 1][0]; low[u] = Math.min(low[u], low[v]) }
      if (low[v] !== index[v]) continue
      const members = []
      let w
      do { w = stack.pop(); onStack[w] = 0; members.push(w) } while (w !== v)
      // a single line is on a loop only if it leads back to itself
      if (members.length > 1 || next(v).includes(v)) { for (const m of members) comp[m] = comps; comps++ }
    }
  }
  return comp
}

// Fills are a function of the active lines alone, and those repeat frame after
// frame: trace each distinct set once. Keyed by two 32-bit hashes of the lines'
// exact values (their float bits) and their count; a few hundred recent sets
// are kept.
const fillCache = new Map(), FILL_CACHE = 256
const bits = new Float64Array(1), words = new Int32Array(bits.buffer)
// Is (x, y) inside the filled landmass? Nonzero winding over every fill
// polygon, the same rule the canvas fill uses.
export function insideBody(fills, x, y) {
  let winding = 0
  for (const p of fills || []) for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const [xi, yi] = p[i], [xj, yj] = p[j]
    if (yj <= y) { if (yi > y && (xi - xj) * (y - yj) - (x - xj) * (yi - yj) > 0) winding++ }
    else if (yi <= y && (xi - xj) * (y - yj) - (x - xj) * (yi - yj) < 0) winding--
  }
  return winding !== 0
}
// A floor the game hides: it has sunk into (or runs inside) the stage body,
// so the space just above its middle is solid (FoD's side platforms
// at the bottom of their travel, Randall passing under Yoshi's Story).
export function buriedPlatform(fills, x0, y0, x1, y1) {
  if (!fills || !fills.length) return false
  return insideBody(fills, (x0 + x1) / 2, (y0 + y1) / 2 + 0.5)
}
// A wall or ceiling with solid body on both sides is a seam inside the
// landmass, not an edge the game shows (Stadium's base walls once a terrain
// stands over them, two bodies meeting).
export function interiorLine(fills, x0, y0, x1, y1) {
  if (!fills || !fills.length) return false
  const len = Math.hypot(x1 - x0, y1 - y0)
  if (!(len > 0)) return false
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2, nx = -(y1 - y0) / len * 0.5, ny = (x1 - x0) / len * 0.5
  return insideBody(fills, mx + nx, my + ny) && insideBody(fills, mx - nx, my - ny)
}
export function cachedFills(lines) {
  let h1 = 2166136261, h2 = 5381, n = 0
  for (const l of lines || []) for (let k = 1; k < 6; k++) {
    bits[0] = l[k]
    h1 = Math.imul(Math.imul(h1 ^ words[0], 16777619) ^ words[1], 16777619)
    h2 = (Math.imul((Math.imul(h2, 33) + words[0]) | 0, 33) + words[1]) | 0; n++
  }
  const key = `${h1 >>> 0}:${h2 >>> 0}:${n}`
  let fills = fillCache.get(key)
  if (fills) { fillCache.delete(key); fillCache.set(key, fills); return fills }
  fills = solidFills(lines)
  fillCache.set(key, fills)
  if (fillCache.size > FILL_CACHE) fillCache.delete(fillCache.keys().next().value)
  return fills
}

// A fighter pins the surface under it only while it stands there itself:
// grounded, past Dead*/Rebirth* (state >= 14, the respawn halo reads as
// grounded far above any floor), and neither captured nor dead. A grabbed or
// thrown fighter (cat 4) inherits the GRABBER's grounded flag while its y
// follows the throw animation, so it witnesses nothing (those arcs drew a
// floor bar under every throw victim on partial stages).
const CAT_ATTACK = 2, CAT_CAPTURED = 4, CAT_DEAD = 6   // viz_export._category
export function groundWitness(f, i, t) {
  if (!f.air || f.air[i][t] || f.state[i][t] < 14) return false
  return !(f.cat && (f.cat[i][t] === CAT_CAPTURED || f.cat[i][t] === CAT_DEAD))
}

// What the stage is doing at a frame when the replay bundle does not say: the
// anchored stages' drift, Fountain of Dreams' side platforms, Stadium / FoD
// state events, and Dream Land's wind. Pure functions of (bundle, idx), cached
// per bundle; litePaint draws what they return.

// Stage anchor inference. A few stages' WHOLE collision drifts in-game
// (Corneria's Great Fox random-walks ~±20 units; marked `anchored` in
// STAGES) and the replay never records stage position — so the base-pose
// drawing slides out from under the fighters. Grounded fighters pin it:
// whenever a fighter is grounded, their y IS the real surface height under
// their x, so y - surfaceYAt(x) is the stage's current vertical offset.
// We take a recency-weighted median of those candidates over a trailing
// window — the median so outliers (fighters on omitted movers, platform/
// floor mismatches) can't drag the stage, recency-weighted so fresh ground
// touches win. Stateless per (bundle, idx): seeking anywhere renders the
// same picture. Validated on real replays: Corneria's grounded-fighter
// error goes from ~8-13 median (drifting) to <2.5 with this on.
const ANCHOR_WINDOW = 120    // trailing frames of grounded evidence
const ANCHOR_MAX_BACK = 600  // how far past the window we'll hunt for ANY sample
const ANCHOR_CLAMP = 80      // |candidate| beyond this = riding unmodeled geometry
export function stageAnchorDy(bundle, st, idx) {
  const f = bundle.frames
  if (!f.air) return 0   // old cached bundles have no grounded flag — stay static
  const NP = f.x.length
  const samples = []     // [weight, candidate dy]
  const lo = Math.max(0, idx - ANCHOR_WINDOW + 1)
  const candidateAt = (i, t) => {
    // groundWitness excludes Dead* AND Rebirth/RebirthWait (12/13): the
    // respawn platform reads as "grounded" but floats far above any real
    // surface — one respawning fighter in a sparse window could drag the
    // whole ship (Codex review catch). It also drops throw victims, whose
    // grounded flag is the thrower's.
    if (!groundWitness(f, i, t)) return null
    const s = surfaceYAt(st, f.x[i][t])
    if (s === null) return null            // off every authored surface
    const c = f.y[i][t] - s
    return Math.abs(c) > ANCHOR_CLAMP ? null : c
  }
  for (let t = idx; t >= lo; t--) {
    const w = 1 - (idx - t) / ANCHOR_WINDOW
    for (let i = 0; i < NP; i++) {
      const c = candidateAt(i, t)
      if (c !== null) samples.push([w, c])
    }
  }
  if (!samples.length) {
    // nobody touched ground in the window (juggle, double recovery) — walk
    // further back and take the nearest frame that has any grounded sample;
    // stale beats a snap to base pose mid-combo.
    for (let t = lo - 1; t >= Math.max(0, idx - ANCHOR_MAX_BACK); t--) {
      const row = []
      for (let i = 0; i < NP; i++) {
        const c = candidateAt(i, t)
        if (c !== null) row.push(c)
      }
      if (row.length) {
        row.sort((a, b) => a - b)
        const m = row.length >> 1
        return row.length % 2 ? row[m] : (row[m - 1] + row[m]) / 2
      }
    }
    return 0   // a whole seconds-long stretch with zero ground contact: give up
  }
  // weighted median over the window's candidates
  samples.sort((a, b) => a[1] - b[1])
  let total = 0
  for (const [w] of samples) total += w
  let acc = 0
  for (const [w, c] of samples) { acc += w; if (acc >= total / 2) return c }
  return samples[samples.length - 1][1]
}

// ── Fountain of Dreams side platforms ─────────────────────────────────────
// FoD's two side platforms ride up and down all match long. Slippi only
// records their positions from slp 3.18 (2024+) — `stage_state.fod`, a list of
// [idx, platform, height] events — and most of any real library predates that
// (measured on this one: FoD games from 2025/2026 carry ~1k-2k events each,
// games from 2023 and earlier carry exactly zero). Without them both
// platforms drew at their authored resting height and a fighter standing on
// one appeared sunk into it to the waist. Two separate things are needed:
//
// 1. UNITS. The recorded height is in the stage's own units, not world units:
//    world_y = 0.75 * recorded + 1.125. Measured by regressing recorded height
//    against the y of fighters grounded on the platform — 2,383 samples from
//    three 2026 replays give slope 0.7494, intercept 1.138, and forcing the
//    exact 0.75/1.125 leaves a median residual of 0.025 with p95 0.05, i.e.
//    dead on at the bundle's 0.1-unit y quantisation. The pair is pinned
//    independently by meleeStages' authored resting heights, which invert to
//    exactly recorded 20 (left, 16.125) and 28 (right, 22.125): 6/8 = 0.75 is
//    FoD's grGroundParam stage scale, 1.125 its collision-root y. Drawing the
//    raw value put the platform ~5 units too high — the same sunk-in-platform
//    artifact, on the modern replays that DO have events.
//
// 2. INFERENCE for the clips with no events, same idea as stageAnchorDy above:
//    a grounded fighter's y IS the surface it stands on. A fighter witnesses a
//    platform when it is grounded (frames.air), not respawning (state >= 14),
//    not being juggled or carried (cat 4 = hitstun/grabbed/thrown — a grabbed
//    fighter inherits the grabber's grounded flag while its y follows the throw
//    animation; those 20-frame arcs were the whole error tail) and its x sits
//    inside that platform's span. Unlike the anchor there is NO window median:
//    the platforms move ~0.1 units/frame, so averaging a 120-frame window would
//    smear them across a third of their travel, while one fresh witness is
//    already exact. We take the nearest witness in TIME on either side of idx
//    and hold it — bidirectional because a bundle is an offline recording, not
//    a live feed, and looking both ways beat looking back only (mean error 3.8
//    vs 4.8 units over every frame; lerping between the two neighbours instead
//    of holding the nearer measured identically and was dropped). Stateless per
//    (bundle, idx), like the anchor: seeking anywhere renders the same picture.
//
// Travel clamp: over 274 modern FoD games (307,725 recorded events) the height
// never leaves [-1.0, 35.0] raw, and both ends are hard stops hit by hundreds
// of games — so world y is clamped to [0.375, 27.375]. That range also does
// the "witness is standing on the stage, not the platform" rejection for free:
// FoD's floor under the platforms is exactly y = 0, below the platform's own
// lowest position, so a stage-floor sample can never pass as a platform one.
const FOD_SPANS = { left: [-49.5, -21], right: [21, 49.5] }   // STAGES[2].platforms
const FOD_SCALE = 0.75, FOD_BASE = 1.125   // recorded units -> world y
const FOD_MIN_Y = 0.375, FOD_MAX_Y = 27.375
const FOD_TOL = 0.1        // bundle y is rounded to 0.1 — don't reject the ends

// One per-bundle cache for everything the paint path precomputes (FoD witness
// tables, per-frame stage-state tables). Keyed by the bundle object itself:
// every caller parks it on a state object once and hands that same reference to
// paintFrame for the life of the clip (detail.js / theater.js / clipcard.js /
// WatchLiteClip all do `s.bundle = raw.bundle || raw` at load), so the key is
// stable and nothing here is rebuilt per frame.
const bundleCache = new WeakMap()
function cacheFor(bundle) {
  let c = bundleCache.get(bundle)
  if (!c) { c = {}; bundleCache.set(bundle, c) }
  return c
}

// Per-side witness tables for a bundle: y[t] = the platform's surface y as
// pinned by whoever stood on it at frame t (NaN = nobody did), plus prev[t] /
// next[t], the nearest witnessed frame at or before / at or after t (-1 = none
// in this clip). Built once per bundle in one O(frames x players) pass so the
// per-frame lookup paintFrame does is O(1) — and so there's no arbitrary hunt
// distance: a witness anywhere in the clip is better than the resting default
// (measured: capping the hunt at 600 frames leaves 28% of frames unfit and
// mean error 3.8 units; unlimited leaves none and 3.25, vs 7.06 for the
// default. Frames where someone is actually standing there score the same
// either way — the witness is that very frame).
function fodWitnesses(bundle) {
  const c = cacheFor(bundle)
  if (c.witnesses) return c.witnesses
  const f = bundle.frames
  const NP = f.x.length
  const n = bundle.meta.n || (NP ? f.x[0].length : 0)
  const w = {}
  for (const side of ['left', 'right']) {
    const [x0, x1] = FOD_SPANS[side]
    const y = new Float64Array(n).fill(NaN)
    if (f.air) {
      for (let t = 0; t < n; t++) {
        let lo = NaN, hi = NaN     // lo/hi witness this frame -> median of them
        for (let i = 0; i < NP; i++) {
          if (!groundWitness(f, i, t)) continue
          const x = f.x[i][t]
          if (x < x0 || x > x1) continue
          const fy = f.y[i][t]
          if (fy < FOD_MIN_Y - FOD_TOL || fy > FOD_MAX_Y + FOD_TOL) continue
          if (!(lo <= fy)) lo = fy
          if (!(hi >= fy)) hi = fy
        }
        if (lo === lo) y[t] = (lo + hi) / 2
      }
    }
    const prev = new Int32Array(n), next = new Int32Array(n)
    let k = -1
    for (let t = 0; t < n; t++) { if (y[t] === y[t]) k = t; prev[t] = k }
    k = -1
    for (let t = n - 1; t >= 0; t--) { if (y[t] === y[t]) k = t; next[t] = k }
    w[side] = { y, prev, next }
  }
  c.witnesses = w
  return w
}

// Nearest witness in time to idx, held (no lerp — see the note above), clamped
// to the platform's measured travel. -1/none anywhere in the clip -> null, and
// the authored resting height stays, which is what this drew before.
function fodInfer(tab, idx) {
  const back = tab.prev[idx], fwd = tab.next[idx]
  let t = -1
  if (back >= 0 && fwd >= 0) t = (idx - back) <= (fwd - idx) ? back : fwd
  else t = back >= 0 ? back : fwd
  if (!(t >= 0)) return null
  return Math.min(FOD_MAX_Y, Math.max(FOD_MIN_Y, tab.y[t]))
}

// World y of the two side platforms at frame idx, or null when the stage/bundle
// gives us nothing. Recorded events ALWAYS win — a side is inferred only when
// this replay recorded nothing for it. Exported so the inference can be scored
// against replays that DO carry events (hide them, infer, diff).
export function fodPlatformY(bundle, ss, idx) {
  if (bundle.meta.stage !== 2) return null
  let left = ss && ss.fodLeft != null ? ss.fodLeft * FOD_SCALE + FOD_BASE : null
  let right = ss && ss.fodRight != null ? ss.fodRight * FOD_SCALE + FOD_BASE : null
  if (left == null || right == null) {
    const w = fodWitnesses(bundle)
    if (left == null) left = fodInfer(w.left, idx)      // nearest witness in
    if (right == null) right = fodInfer(w.right, idx)   // time; a tie is idx
  }
  return { left, right }
}

// ── v2 bundle extras: stage state + items ─────────────────────────────────

// Latest FoD platform heights / Stadium transformation at frame idx.
//
// The event lists are NOT short: a modern (slp 3.18+) FoD replay records the
// two side platforms continuously and carries 1,000-2,000 `fod` events per
// game. Rescanning that list from the start on every frame made this O(events)
// at 60fps and it swamped everything else in the paint — measured on a real
// 1,225-event FoD game, paintFrame cost 13.0 us/frame of which stageStateAt
// alone was 12.1, against 1.1 us/frame for a non-FoD clip of the same length.
// So resolve the whole event stream into per-frame tables ONCE per bundle (in
// the same cache as the FoD witnesses above) and make the per-frame lookup a
// couple of array reads, like the witness lookup.
//
// The exporter emits both lists non-decreasing in idx (pre-window events are
// carried in clamped to 0 and prepended — see viz_export._viz_items), which is
// what makes a single forward sweep equivalent to the old per-frame scan. If a
// bundle ever arrives out of order we don't guess: `sorted` goes false and the
// original scan is used for that bundle.
function stageStateTables(bundle) {
  const c = cacheFor(bundle)
  if (c.stage) return c.stage
  const ss = bundle.stage_state
  const f = bundle.frames
  const n = bundle.meta.n || (f && f.x.length ? f.x[0].length : 0)
  const t = { n, sorted: true, fodLeft: null, fodRight: null, stadium: null }
  const ordered = (ev) => {
    for (let i = 1; i < ev.length; i++) if (ev[i][0] < ev[i - 1][0]) return false
    return true
  }
  if (ss.fod && ss.fod.length && n > 0) {
    const ev = ss.fod
    if (!ordered(ev)) t.sorted = false
    else {
      // carry each side's latest recorded height forward; NaN until its first
      // event, matching the key simply being absent from the old result.
      const L = new Float64Array(n).fill(NaN), R = new Float64Array(n).fill(NaN)
      let lv = NaN, rv = NaN, e = 0
      for (let i = 0; i < n; i++) {
        while (e < ev.length && ev[e][0] <= i) {
          const r = ev[e++]
          if (r[1] === 0) rv = r[2]
          else lv = r[2]
        }
        L[i] = lv; R[i] = rv
      }
      t.fodLeft = L; t.fodRight = R
    }
  }
  if (ss.stadium && ss.stadium.length && n > 0) {
    const ev = ss.stadium
    if (!ordered(ev)) t.sorted = false
    else {
      // one shared {event,id} per recorded transformation (a handful per game),
      // indexed per frame — so no object is allocated in the draw path.
      const forms = ev.map((e) => ({ event: e[1], id: e[2] }))
      const at = new Array(n).fill(null)
      let cur = null, e = 0
      for (let i = 0; i < n; i++) {
        while (e < ev.length && ev[e][0] <= i) cur = forms[e++]
        at[i] = cur
      }
      t.stadium = at
    }
  }
  c.stage = t
  return t
}

export function stageStateAt(bundle, idx) {
  const ss = bundle.stage_state
  if (!ss) return null
  const t = stageStateTables(bundle)
  // out of the tables' range (or an unsorted event list): fall back to the
  // original scan so the answer is the same whatever the bundle looks like.
  if (!t.sorted || idx < 0 || idx >= t.n) return stageStateScan(ss, idx)
  const out = {}
  if (t.fodLeft) {
    const l = t.fodLeft[idx], r = t.fodRight[idx]
    if (l === l) out.fodLeft = l
    if (r === r) out.fodRight = r
  }
  if (t.stadium) {
    const ev = t.stadium[idx]
    if (ev) out.stadium = ev
  }
  return out
}

function stageStateScan(ss, idx) {
  const out = {}
  if (ss.fod) {
    for (const [t, plat, h] of ss.fod) {
      if (t > idx) break
      if (plat === 0) out.fodRight = h
      else out.fodLeft = h
    }
  }
  if (ss.stadium && ss.stadium.length) {
    let ev = null
    for (const e of ss.stadium) {
      if (e[0] > idx) break
      ev = e
    }
    if (ev) out.stadium = { event: ev[1], id: ev[2] }
  }
  return out
}

// ── Whispy Woods' wind, Dream Land N64 ──────────────────────────────────────
//
// Slippi has no wind event, but the engine leaves the wind written into the
// fighters' own positions, exactly. From the decomp (gr/groldpupupu.c ->
// fn_802112F4, consumed by ftColl_GetWindOffsetVec and applied in
// Fighter_procUpdate as `fp->cur_pos.x += windOffset.x`):
//
//   * the wind is a pure per-frame POSITION offset of exactly 0.2 units. It is
//     never added to velocity and it is applied AFTER physics and collision, so
//     on a fighter that would not otherwise move, the frame delta IS the wind.
//     GrOp.dat's `yakumono_param` block holds the 0.2 and the bounds below.
//   * it only reaches one half of the stage at a time — the tree stands at
//     x ~= -17.5 and blows away from itself over the side most fighters are on
//     (ftLib_800864A8). Left blow: x in (-74,-18); right blow: x in (-17,76);
//     both y in (-10,40). Ledge-hangers (|x| ~ 77) and the top platform
//     (y ~ 51.4) sit outside it, which is why nobody gets blown off the ledge.
//   * one blow lasts at most 274 frames (the blow state gates the push to
//     45 < t < 320) and its direction is fixed for the whole blow. Measured on
//     120 replays with no cap applied: longest run 262 frames, and consecutive
//     blows never start less than 797 frames apart.
//
// So a witness is a fighter that is provably self-motionless — grounded (or
// fully airborne, where Melee decays horizontal velocity to exactly 0), in an
// action state that cannot translate it on its own, stick inside the walk
// deadzone, far enough from the other fighter that the overlap-push (its own
// +-0.1/0.3) can't be mistaken for wind — whose x moves by exactly +-0.2 for
// WIND_RUN frames running.
//
// Calibrated against replays that CANNOT contain wind: on 572 games across five
// wind-free stages (4,340,852 frames) this rule produced zero witnesses and drew
// nothing. Every relaxation that was tried does fire there — a 4-frame run
// catches walks trailing off, and dropping the state gate catches sliding
// forward smashes (one, measured, drifted 0.2065/frame for ten frames).
const DL_STAGE = 28
const WIND_V = 0.2          // engine constant, GrOp.dat yakumono_param +0x10
const WIND_TOL = 0.03       // bundle x is rounded to 0.1, a multiple of 0.2
const WIND_RUN = 6          // consecutive frames at the wind rate = a witness
const WIND_MAX = 274        // longest possible blow
const WIND_GROW = 60        // how far past its own evidence a blow may be drawn
const WIND_SEP = 30         // closer than this, the fighter-push contaminates dx
const WIND_STICK = 0.28     // below Melee's 0.2875 walk threshold
const WIND_YLO = -10, WIND_YHI = 40
export const WIND_LX0 = -74, WIND_LX1 = -18   // left-blow box
export const WIND_RX0 = -17, WIND_RX1 = 76    // right-blow box
// Which blow box a point is in: -1 left, +1 right, 0 = the wind cannot reach it.
function windSide(x, y) {
  if (!(y > WIND_YLO && y < WIND_YHI)) return 0
  if (x > WIND_LX0 && x < WIND_LX1) return -1
  if (x > WIND_RX0 && x < WIND_RX1) return 1
  return 0
}

// Per-frame wind direction for a bundle: Int8Array (-1/0/+1), or null on every
// other stage. Built once per bundle into the same WeakMap as the FoD witnesses
// so the paint path stays O(1) per frame — this is an O(frames x players) scan
// and it must never run inside the frame loop. Measured: 0.2-0.6 ms to build a
// whole game, ~30 ns per cached lookup, and nothing at all off Dream Land.
// Exported, like fodPlatformY, so the rule can be re-scored against replays.
export function windTable(bundle) {
  const c = cacheFor(bundle)
  if (c.wind !== undefined) return c.wind
  c.wind = null
  const f = bundle.frames
  if (bundle.meta.stage !== DL_STAGE || !f || !f.air || !f.joyx || !f.cat) return null
  const NP = f.x.length
  const n = bundle.meta.n || (NP ? f.x[0].length : 0)
  if (n < WIND_RUN + 4) return null

  // pos[t] = a witness proves the wind blows this way; negL/negR[t] = a witness
  // inside that box proves it does NOT. Negative evidence is what stops a blow
  // from being drawn past its real end.
  const pos = new Int8Array(n)
  const clash = new Uint8Array(n)   // two witnesses claiming opposite ways
  const negL = new Uint8Array(n), negR = new Uint8Array(n)
  const run = new Int8Array(n)
  for (let i = 0; i < NP; i++) {
    const X = f.x[i], Y = f.y[i], A = f.air[i], J = f.joyx[i], C = f.cat[i]
    run.fill(0)
    for (let t = 3; t < n; t++) {
      if (Math.abs(J[t]) > WIND_STICK || Math.abs(J[t - 1]) > WIND_STICK) continue
      // A fighter in hitstun/grabbed/dead witnesses nothing either way: the
      // engine skips the wind outright for some of those states
      // (ftColl_GetWindOffsetVec bails on fp->x2224_b4), so its stillness would
      // cut a real blow short. Anything that can translate ITSELF — attacks,
      // specials, landing lag — can still say "no wind", but must not be
      // believed when it moves: that is what `quiet` gates.
      let skip = false, quiet = true
      for (let k = 0; k < 4; k++) {
        const cc = C[t - k]
        if (cc === CAT_CAPTURED || cc === CAT_DEAD) { skip = true; break }
        if (cc === CAT_ATTACK) quiet = false
      }
      if (skip) continue
      const grounded = !(A[t] || A[t - 1] || A[t - 2] || A[t - 3])
      const aloft = !!(A[t] && A[t - 1] && A[t - 2] && A[t - 3])
      if (!grounded && !aloft) continue
      let close = false
      for (let q = 0; q < NP; q++) {
        if (q !== i && Math.abs(f.x[q][t] - X[t]) < WIND_SEP) { close = true; break }
      }
      if (close) continue
      const d1 = X[t] - X[t - 1], d2 = X[t - 1] - X[t - 2], d3 = X[t - 2] - X[t - 3]
      let v
      if (Math.abs(d1) < WIND_TOL) v = 0
      else if (Math.abs(d1 - WIND_V) < WIND_TOL) v = 1
      else if (Math.abs(d1 + WIND_V) < WIND_TOL) v = -1
      else continue
      // the two frames before must be still or already blowing the same way —
      // a steady walk sitting near 0.2 cannot also have a neutral stick
      let ok = true
      for (let k = 0; k < 2; k++) {
        const d = k ? d3 : d2
        if (Math.abs(d) < WIND_TOL) continue
        if (v && Math.abs(d - v * WIND_V) < WIND_TOL) continue
        ok = false; break
      }
      if (!ok) continue
      const side = windSide(X[t], Y[t])
      // an airborne witness must have stayed in one box for the whole window,
      // or falling out through y = 40 reads as stillness on both sides of it
      if (!side || (aloft && windSide(X[t - 2], Y[t - 2]) !== side)) continue
      if (v) { if (side === v && quiet) run[t] = v }
      else if (side < 0) negL[t] = 1
      else negR[t] = 1
    }
    for (let t = 3; t < n;) {
      if (!run[t]) { t++; continue }
      let e = t
      while (e + 1 < n && run[e + 1] === run[t]) e++
      if (e - t + 1 >= WIND_RUN) {
        for (let k = t; k <= e; k++) {
          if (pos[k] && pos[k] !== run[t]) clash[k] = 1
          pos[k] = run[t]
        }
      }
      t = e + 1
    }
  }

  // Witnesses -> drawn intervals. Everything between two same-direction
  // witnesses inside one 274-frame window is certainly mid-blow (the blow is
  // contiguous), so that span is drawn outright; past it the blow is carried at
  // most WIND_GROW frames further, and stops dead at the first frame a witness
  // proves that box wind-free. Carrying it is the only step not backed by its
  // own evidence, so it was audited with a port holdout — witnesses from one
  // port only, judged against the other port's, at full precision. Over 200
  // Dream Land games: 7 of 14,388 carried frames (0.05%) contradicted, 97
  // independently confirmed. Carrying the full 274 instead of 60 pushes that to
  // 0.21% and lets two blows land within 552 frames of each other, which the
  // engine cannot do (measured minimum spacing, 120 games: 797).
  const out = new Int8Array(n)
  for (let t = 0; t < n; t++) if (clash[t]) pos[t] = 0
  for (let t = 0; t < n;) {
    const d = pos[t]
    if (!d) { t++; continue }
    let a = t, b = t
    for (let k = t + 1; k < n && k - a < WIND_MAX; k++) {
      if (pos[k] === d) b = k
      else if (pos[k] === -d) break
    }
    const neg = d > 0 ? negR : negL
    let s = a, e = b
    const lo = Math.max(0, a - WIND_GROW), hi = Math.min(n - 1, b + WIND_GROW)
    while (s > lo && !neg[s - 1]) s--
    while (e < hi && !neg[e + 1]) e++
    for (let k = s; k <= e; k++) out[k] = d
    t = b + 1
  }
  c.wind = out
  return out
}
