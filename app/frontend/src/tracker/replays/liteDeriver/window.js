export const MAX_CLIP_FRAMES = 1500

export function frameWindow(parsed, startFrame, endFrame, pad = 45) {
  const { firstFrame, n } = parsed
  if (!n) return { lo: 0, hi: -1 }
  startFrame = startFrame ?? firstFrame
  endFrame = Math.min(endFrame ?? firstFrame + n - 1, startFrame + MAX_CLIP_FRAMES)
  // Cap the requested action before padding, exactly as build_clip_bundle
  // does. These are true frames, so rollback row counts never enter the math.
  const lo = Math.max(0, Math.min(n - 1, Math.trunc(startFrame - pad - firstFrame)))
  const hi = Math.max(lo, Math.min(n - 1, Math.trunc(endFrame + pad - firstFrame)))
  return { lo, hi }
}

// Shared by direct derivation (absolute frame events) and re-windowing
// (relative index events). Carry deltas in even if no event occurs in the clip.
export function sliceStageState(stage, lo, hi) {
  const out = {}
  if (hi < lo) return out
  const baseline = [], fod = []
  for (const [frame, plat, height] of stage?.fod || []) {
    if (frame < lo) baseline[plat] = [0, plat, height]
    else if (frame <= hi) fod.push([frame - lo, plat, height])
  }
  const carried = baseline.filter(Boolean).concat(fod)
  if (carried.length) out.fod = carried
  let carry = null
  const stadium = []
  for (const [frame, event, tid] of stage?.stadium || []) {
    if (frame < lo) carry = [0, event, tid]
    else if (frame <= hi) stadium.push([frame - lo, event, tid])
  }
  if (carry) stadium.unshift(carry)
  if (stadium.length) out.stadium = stadium
  return out
}

const sliceTrack = (v, lo, hi) =>
  v != null && typeof v.slice === 'function' ? v.slice(lo, hi + 1) : v

export function windowBundle(bundle, startFrame, endFrame, pad = 45) {
  const { meta } = bundle
  const { lo, hi } = frameWindow({ firstFrame: meta.start_frame, n: meta.n }, startFrame, endFrame, pad)
  if (meta.n < 2 || (lo === 0 && hi === meta.n - 1)) return bundle
  const frames = {}
  for (const [key, ports] of Object.entries(bundle.frames)) {
    if (key === 'fol') {
      frames.fol = ports.map(f => Object.fromEntries(Object.entries(f).map(([k, v]) =>
        [k, k === 'of' ? v : sliceTrack(v, lo, hi)])))
    } else frames[key] = Array.isArray(ports) ? ports.map(v => sliceTrack(v, lo, hi)) : ports
  }
  const start = meta.start_frame + lo, end = meta.start_frame + hi
  const conversions = Object.fromEntries(Object.entries(bundle.conversions || {}).map(([actor, rows]) =>
    [actor, rows.filter(c => c.end_frame >= start && c.start_frame <= end)]))
  const out = { meta: { ...meta, start_frame: start, n: hi - lo + 1 }, frames, conversions }
  if (bundle.items) {
    out.items = []
    for (const item of bundle.items) {
      const a = Math.max(lo, item.f), b = Math.min(hi, item.f + item.x.length - 1)
      if (b < a) continue
      const clipped = { ...item, f: a - lo }
      const born = (item.born ?? item.f) - lo
      if (born < clipped.f) clipped.born = born; else delete clipped.born
      for (const k of ['x', 'y', 'd', 's', 'vx', 'vy', 'lifetime', 'subtype', 'face', 'launched', 'charge', 'owner', 'port']) {
        if (item[k] != null) clipped[k] = sliceTrack(item[k], a - item.f, b - item.f)
      }
      out.items.push(clipped)
    }
  }
  const stage = sliceStageState(bundle.stage_state, lo, hi)
  if (Object.keys(stage).length) out.stage_state = stage
  return out
}
