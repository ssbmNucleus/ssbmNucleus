import { createViewerFrameDecoder, ownsViewerEvent } from './viewerStream.js'
import { explainAppControl } from '../lib/appControl.js'

export function viewerErrorMessage(error, isStage = false) {
  const message = error?.message || String(error)
  // A viewer older than the one pinned in utility/hsdlib.manifest.json: before
  // hsdlib v2026.11.09.1 the Linux/macOS (headless) viewer loaded fighters only.
  if (isStage && message.includes('No JOBJ found in DAT file')) {
    return 'This viewer could not load the stage model. Update Nucleus and its bundled 3D viewer to a build with Stage Creator support. Your stage file has not been changed.'
  }
  return explainAppControl(message)
}

// A closed editor or a newer load owns the UI; late completions must stay inert.
export async function resolvePaintSource(loadSource, loadPose, isCurrent) {
  const data = await loadSource()
  if (!isCurrent()) return null
  const pose = await loadPose()
  return isCurrent() ? { data, pose } : null
}

export async function launchPaintViewerSession({ electron, paths, onMessage, onSubscribe, isCurrent,
  getCanvas, onFrameError = () => {} }) {
  let disposed = false, unsubscribeMessage, unsubscribeFrame
  const current = () => !disposed && isCurrent()
  const decoder = getCanvas ? createViewerFrameDecoder({ viewerSessionId: paths.viewerSessionId,
    getCanvas, isCurrent: current, onError: onFrameError,
    consume: metadata => electron.viewerFrameConsumed?.(metadata) }) : null
  const cleanup = () => {
    if (disposed) return
    disposed = true
    decoder?.dispose()
    unsubscribeFrame?.()
    unsubscribeMessage?.()
  }
  try {
    unsubscribeMessage = electron.onViewerMessage(message => {
      if (current() && ownsViewerEvent(paths.viewerSessionId, message)) onMessage(message)
    })
    // Subscribe before invoking start: ready and the first frame may precede
    // its IPC response, including when React has not mounted the canvas yet.
    if (decoder && electron.onViewerFrame) unsubscribeFrame = electron.onViewerFrame(decoder.receive)
    onSubscribe(cleanup)
    const result = await electron.viewerStart(paths)
    if (!current()) {
      cleanup()
      await electron.viewerStop?.(paths.viewerSessionId)
      return null
    }
    if (result?.streaming && getCanvas && (!electron.onViewerFrame || !electron.viewerFrameConsumed)) {
      throw new Error('Canvas streaming requires frame metadata and viewerFrameConsumed support from Electron. Update the viewer host.')
    }
    if (result?.error || result?.success === false || result?.connected === false) {
      throw new Error(result.error || 'The viewer could not connect.')
    }
    return result || {}
  } catch (error) {
    cleanup()
    try { await electron.viewerStop?.(paths.viewerSessionId) } catch { /* Preserve the startup error. */ }
    if (!isCurrent()) return null
    throw error
  }
}
