// NTSC HSD_Rand: scheduler s_link ascending, then p_link, then creation order.
// See rngorder/stage{2,3}/REPORT.md. A pre record is INSIDE Fighter_procInput.
import inputTails from '../data/rngInputTails.runtime.json' with { type: 'json' }
export const nextSeed = seed => (Math.imul(seed, 214013) + 2531011) >>> 0
export const previousSeed = seed => Math.imul((seed - 2531011) >>> 0, 3115528533) >>> 0
export const isSeed = seed => Number.isInteger(seed) && seed >= 0 && seed <= 0xffffffff
export function advanceSeed(seed, draws) {
  if (!isSeed(seed) || !Number.isInteger(draws)) return null
  for (; draws > 0; draws--) seed = nextSeed(seed)
  for (; draws < 0; draws++) seed = previousSeed(seed)
  return seed
}
export function random(seed) {
  if (!isSeed(seed)) return null
  return { seed, used: 0, valid: true,
    next() { this.used++; this.seed = nextSeed(this.seed); return this.seed >>> 16 },
    int(n) { return Math.trunc(n * this.next() / 65536) },
    float() { return this.next() / 65536 },
  }
}
export const setupCursor = bundle => random(bundle?.meta?.start_seed)

// Order is the finalized raw pre-event offset, not a physical/dense port ID.
export function lastPre(bundle, idx) {
  const f = bundle?.frames
  if (!f) return null
  let last = null
  const consider = (row, port, follower) => {
    const order = row.seed_order?.[idx], seed = row.seed?.[idx]
    if (order > (last?.order ?? 0) && isSeed(seed)) last = {
      seed, order, port, follower, pre: row.pre_state?.[idx],
      state: row.state?.[idx], age: row.age?.[idx], cid: row.cid?.[idx],
    }
  }
  for (let p = 0; p < (f.seed?.length || 0); p++) consider(Object.fromEntries(
    ['seed', 'seed_order', 'pre_state', 'state', 'age', 'cid'].map(k => [k, f[k]?.[p]])), p, false)
  for (const row of f.fol || []) consider(row, row.of, true)
  // Old bundles without order are safe only for one fighter and no followers.
  if (!last && !f.seed_order && f.seed?.length === 1 && !f.fol?.length && isSeed(f.seed[0]?.[idx])) {
    last = { seed: f.seed[0][idx], port: 0, follower: false,
      pre: f.pre_state?.[0]?.[idx], state: f.state?.[0]?.[idx], age: f.age?.[0]?.[idx], cid: f.cid?.[0]?.[idx] }
  }
  return last
}

// The optional table counts synchronous frame-zero commands on action entry.
// Unknown/conditional tails are not a proof of zero; special cases remain
// documented by the table producer. Never infer a whole-frame RNG distance.
export function inputTailDraws(bundle, idx, table = inputTails) {
  const p = lastPre(bundle, idx)
  if (!p || p.pre == null || p.state === p.pre || !(p.age <= 1)) return 0
  const draws = table?.tails?.[p.cid]?.[p.state]
  return Number.isInteger(draws) && draws >= 0 ? draws : 0
}

// extra is a known draw count BEFORE this object at the requested priority.
// At priority 1 it MUST include priority-0 work after Frame Start (pass 0 only
// when proven). At priority 10 it MUST include the fighter/item physics tail
// and earlier ground work. Omitting it fails closed at those priorities.
export function frameCursor(bundle, idx, { priority = 4, extra } = {}) {
  if (!Number.isInteger(idx) || idx < 0 || idx >= bundle?.meta?.n) return null
  if (extra != null && (!Number.isInteger(extra) || extra < 0)) return null
  let seed, draws
  if (priority === 4 || priority === 10) {
    if (priority === 10 && extra == null) return null
    seed = lastPre(bundle, idx)?.seed
    draws = inputTailDraws(bundle, idx) + (extra ?? 0)
  } else if (priority === 1) {
    if (extra == null) return null
    seed = bundle.frames?.frame_seed?.[0]?.[idx]
    draws = extra
  } else return null
  return random(advanceSeed(seed, draws))
}
