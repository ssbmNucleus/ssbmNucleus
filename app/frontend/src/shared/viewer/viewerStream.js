import { viewerCanvasState } from './viewerSurface.js'

export function ownsViewerEvent(viewerSessionId, metadata) {
  return !!viewerSessionId && metadata?.viewerSessionId === viewerSessionId
}

export function newViewerSessionId() {
  return `viewer-${globalThis.crypto.randomUUID()}`
}

// A bounded decoder: one active decode and one latest pending frame. Session
// ownership is independent of the native paint-pair sessionId protocol.
export function createViewerFrameDecoder({ viewerSessionId, getCanvas, isCurrent = () => true,
  consume, onError = () => {}, decode = buffer => createImageBitmap(new Blob([buffer], { type: 'image/jpeg' })) }) {
  let disposed = false, active = null, pending = null, latestId = -1
  const report = error => { if (!disposed && isCurrent()) onError(error) }
  const settle = frame => {
    if (!frame || frame.settled) return
    frame.settled = true
    try { Promise.resolve(consume(frame.metadata)).catch(report) } catch (error) { report(error) }
  }
  const discard = frame => { try { /* No decode needed for a discarded frame. */ } finally { settle(frame) } }
  const draw = async frame => {
    active = frame
    let bitmap
    const canvas = getCanvas()
    const surfaceState = viewerCanvasState(canvas)
    const width = canvas?.width, height = canvas?.height
    try {
      if (!canvas || surfaceState?.visible === false) return
      bitmap = await decode(frame.buffer)
      if (!disposed && isCurrent() && frame.metadata.frameId === latestId &&
          canvas && canvas === getCanvas() && viewerCanvasState(canvas) === surfaceState &&
          canvas.width === width && canvas.height === height &&
          width > 0 && height > 0) {
        const context = canvas.getContext('2d')
        if (!context) throw new Error('The viewer canvas could not create a 2D drawing context.')
        context.drawImage(bitmap, 0, 0, width, height)
      }
    } catch (error) { report(new Error(`Viewer frame could not be decoded or drawn: ${error.message}`)) }
    finally {
      try { bitmap?.close() } catch (error) { report(error) } finally {
        settle(frame)
        active = null
        const next = pending
        pending = null
        if (next) {
          if (disposed || !isCurrent()) discard(next)
          else void draw(next)
        }
      }
    }
  }
  return {
    receive(buffer, metadata) {
      if (!ownsViewerEvent(viewerSessionId, metadata)) return
      const frame = { buffer, metadata }
      if (disposed || !isCurrent() || !Number.isSafeInteger(metadata.frameId) || metadata.frameId <= latestId) {
        discard(frame)
        return
      }
      latestId = metadata.frameId
      if (active) { discard(pending); pending = frame }
      else void draw(frame)
    },
    dispose() {
      disposed = true
      // Release main's in-flight slot even if the browser decoder never settles.
      // The outstanding decode is fenced above and closes its bitmap on completion.
      discard(active)
      discard(pending)
      pending = null
    }
  }
}

/**
 * Whether a viewer takes `type`: it announced protocol 2 or later in its `capabilities` message and lists
 * the type in `messages` (docs/dev/VIEWER_STREAMING.md). An older viewer announces neither, and gets only
 * what it always got.
 */
export function viewerSupports(capabilities, type) {
  return Boolean(capabilities && Number.isInteger(capabilities.protocolVersion) && capabilities.protocolVersion >= 2
    && Array.isArray(capabilities.messages) && capabilities.messages.includes(type))
}

export function viewerCapabilityWarning(message, { cspMode = false } = {}) {
  const capabilities = message.capabilities || message
  const missing = []
  if (cspMode && capabilities.cspMode === false) missing.push('CSP camera mode')
  if (capabilities.animationTicks === false) missing.push('live animation frame updates')
  return missing.length ? `This viewer does not support ${missing.join(' or ')}.` : ''
}
