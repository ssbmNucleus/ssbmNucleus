/**
 * Weighted-playlist math: play chances are integer percentages that
 * always sum to exactly 100 (mirrors the backend's normalization).
 */

/** Scale `weights` to non-negative integers summing to exactly `target`,
 *  preserving ratios (largest-remainder rounding). All-zero input splits
 *  the target evenly. */
export function scaleToTotal(weights, target) {
  const n = weights.length
  if (!n) return []
  let ws = weights.map(w => Math.max(0, w))
  let total = ws.reduce((a, b) => a + b, 0)
  if (total <= 0) {
    ws = ws.map(() => 1)
    total = n
  }
  const exact = ws.map(w => (w * target) / total)
  const floors = exact.map(Math.floor)
  const leftover = target - floors.reduce((a, b) => a + b, 0)
  const byRemainder = exact
    .map((x, i) => [x - floors[i], i])
    .sort((a, b) => b[0] - a[0])
  for (let k = 0; k < leftover; k++) floors[byRemainder[k % n][1]] += 1
  return floors
}

/** Pin weights[index] to `value` and rescale the rest proportionally so
 *  the list still sums to 100. */
export function rebalanceWeights(weights, index, value) {
  if (weights.length <= 1) return weights.map(() => 100)
  const pinned = Math.max(0, Math.min(100, Math.round(value)))
  const others = weights.filter((_, i) => i !== index)
  const scaled = scaleToTotal(others, 100 - pinned)
  let j = 0
  return weights.map((_, i) => (i === index ? pinned : scaled[j++]))
}
