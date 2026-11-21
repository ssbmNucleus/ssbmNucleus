import { stageDataFor } from '../stageData.js'

// Mute City's MapLines are deterministic. grMuteCity_801F04B8 interprets
// grMc_803E34E0; 801F0D20 intersects the two animated splines with z=0.
// Random traffic (801F106C) and wreck/sound draws (801F1A34) create items,
// not MapLines. Neither those draws nor fn_801F2B58 alter these vertices.
//
// This is a bounded animation sampler, NOT a private RNG simulation. The
// 3600-frame DAT animation pauses twice at each of seven stops (340 + 60,
// plus command dispatch frames), so 3600 is NOT the real-frame loop length.
// C16's 25,200-frame capture verifies a 6012-frame repeating suffix after
// startup. Preserve the prefix; only loop the independently measured suffix.

function keyAt(keys, frame) {
  let lo = 0, hi = keys.length
  while (lo + 1 < hi) {
    const mid = (lo + hi) >>> 1
    if (keys[mid][0] <= frame) lo = mid
    else hi = mid
  }
  return lo
}

// Exported for synthetic interpolation/visibility tests and offline auditing.
export function sampleCollision(data, frame) {
  const loopStart = data.loopStart ?? data.range[0]
  if (data.loop && (loopStart === data.range[0] || frame >= loopStart)) {
    frame = ((frame-loopStart)%data.loop+data.loop)%data.loop+loopStart
  }
  if (!Number.isFinite(frame) || frame < data.range[0] || frame > data.range[1]) return null
  const lines = (data.static || []).map(line => [...line])
  for (const group of data.groups) {
    const flags = group.flags[keyAt(group.flags, frame)]
    if (!flags.slice(1).some(flag => flag & 15)) continue
    const keys = data.tracks[group.track]
    const i = keyAt(keys, frame), a = keys[i], b = keys[Math.min(i + 1, keys.length - 1)]
    const t = a[0] === b[0] ? 0 : (frame - a[0]) / (b[0] - a[0])
    const v = a.slice(1).map((value, j) => value + (b[j + 1] - value) * t)
    const vertex = i => {
      if (group.affine) {
        const [x, y] = group.base[i]
        return [x * v[0] + y * v[2] + v[4], x * v[1] + y * v[3] + v[5]]
      }
      if (group.base) return [group.base[i][0] + v[0], group.base[i][1] + v[1]]
      return [v[i * 2], v[i * 2 + 1]]
    }
    for (let j = 0; j < group.lines.length; j++) {
      if (!(flags[j + 1] & 15)) continue
      const [id, a, b] = group.lines[j]
      lines.push([id, flags[j + 1], ...vertex(a), ...vertex(b)])
    }
  }
  lines.sort((a, b) => a[0] - b[0])
  return { lines, replace: true, complete: true }
}

const cache = new WeakMap()
export default function simulate(bundle, idx) {
  if (!bundle || Number(bundle.meta?.stage) !== 10 || !Number.isInteger(idx) || idx < 0 ||
      !Number.isInteger(bundle.meta.start_frame)) return null
  const pack = stageDataFor(10)
  if (!pack?.sim) return null
  const track = pack.sim.collision ? { ...pack.collision, ...pack.sim } : pack.sim
  const frame = bundle.meta.start_frame + idx
  const previous = cache.get(bundle)
  if (previous?.track === pack && previous.frame === frame) return previous.result
  const result = sampleCollision(track, frame)
  if (result) {
    // V5 raw replay bundles use retail collision flags. Legacy visual bundles
    // use authored platform annotations in the shared payload. MapLines 0..53
    // have no drop-through bit in either independent retail capture.
    for (const line of result.lines) {
      if (bundle.meta.v >= 5) line[1] &= 15
      Object.freeze(line)
    }
    Object.freeze(result.lines)
    Object.freeze(result)
  }
  // Direct binary searches are O(log key count), including reverse seeks.
  // No state integration/checkpoint walk is needed for a scripted capture.
  cache.set(bundle, { frame, result, track: pack })
  return result
}
