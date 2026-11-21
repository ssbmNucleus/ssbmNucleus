import { parseSlp } from './slpParse.js'
import { deriveBundle } from './deriveBundle.js'
import { frameWindow } from './window.js'

export { parseSlp, parseHeaderOnly, SlpError } from './slpParse.js'
export { deriveBundle } from './deriveBundle.js'
export { windowBundle, frameWindow, MAX_CLIP_FRAMES } from './window.js'

export function deriveFromSlp(bytes, { start, end, pad = 45 } = {}) {
  const parsed = parseSlp(bytes)
  // Omitted bounds mean a whole game, without the clip length cap.
  return deriveBundle(parsed, start == null && end == null ? {} : frameWindow(parsed, start, end, pad))
}
