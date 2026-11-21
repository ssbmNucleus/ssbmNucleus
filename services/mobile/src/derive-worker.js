import { deriveBundle, parseSlp } from '../../../app/frontend/src/tracker/replays/liteDeriver/index.js'

// Also imported by api.js for the main-thread fallback. One parse feeds both
// the bundle and the legacy row map (cloud combos are row-basis).
export function deriveClip(bytes) {
  const parsed = parseSlp(bytes)
  const bundle = deriveBundle(parsed)
  return { bundle, rowFids: parsed.rowFids, firstFrame: parsed.firstFrame }
}

if (typeof WorkerGlobalScope !== 'undefined' && globalThis instanceof WorkerGlobalScope) {
  globalThis.onmessage = ({ data }) => {
    try {
      const result = deriveClip(data)
      globalThis.postMessage(result, [result.rowFids.buffer])
    } catch (error) {
      globalThis.postMessage({ error: error.message || String(error) })
    }
  }
}
