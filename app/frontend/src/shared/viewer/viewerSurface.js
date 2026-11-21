const canvasStates = new WeakMap()
export const viewerCanvasState = canvas => canvas && canvasStates.get(canvas)

// Render pixels are derived from the layout box, never desktop coordinates.
export function viewerRenderSize(rect, dpr = 1) {
  if (!Number.isFinite(rect.width) || !Number.isFinite(rect.height) || rect.width < 2 || rect.height < 2) return null
  const pixelRatio = Number.isFinite(dpr) && dpr > 0 ? dpr : 1
  // Match the stream renderer's maximum edge without stretching wide/tall views.
  const scale = Math.min(pixelRatio, 2048 / Math.max(rect.width, rect.height))
  return { width: Math.max(1, Math.round(rect.width * scale)), height: Math.max(1, Math.round(rect.height * scale)) }
}

export function createViewerSurface({ element, getCanvas, streaming, resize, show, hide,
  screenRect, getDpr = () => window.devicePixelRatio, isVisible = () => !document.hidden,
  onError = () => {} }) {
  let lastSize = '', visible = null
  const send = (fn, ...args) => {
    try { Promise.resolve(fn(...args)).catch(onError) } catch (error) { onError(error) }
  }
  return {
    update(layoutSize) {
      // ResizeObserver supplies layout dimensions unaffected by modal transforms.
      const rect = streaming ? (layoutSize || (Number.isFinite(element.clientWidth)
        ? { width: element.clientWidth, height: element.clientHeight } : element.getBoundingClientRect()))
        : element.getBoundingClientRect()
      const size = viewerRenderSize(rect, getDpr())
      const nextVisible = !!size && isVisible() &&
        (!element.checkVisibility || element.checkVisibility({ visibilityProperty: true }))
      const canvas = getCanvas()
      const state = viewerCanvasState(canvas)
      if (canvas && (!state || state.visible !== nextVisible ||
          state.width !== size?.width || state.height !== size?.height)) {
        canvasStates.set(canvas, { visible: nextVisible, width: size?.width, height: size?.height })
      }
      if (!nextVisible) {
        if (visible !== false) send(hide)
        visible = false
        return
      }
      const target = streaming ? { x: 0, y: 0, ...size } : screenRect(rect)
      const key = JSON.stringify(target)
      if (streaming && canvas) {
        if (canvas.width !== size.width) canvas.width = size.width
        if (canvas.height !== size.height) canvas.height = size.height
      }
      if (key !== lastSize) {
        lastSize = key
        send(resize, target.x, target.y, target.width, target.height)
      }
      if (visible !== true) send(show)
      visible = true
    }
  }
}
