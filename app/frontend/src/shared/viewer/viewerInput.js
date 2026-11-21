/**
 * How far the renderer's camera moves (its X/Y, in scene units) for one pixel of mouse movement, so the model stays
 * under the cursor while it is dragged: the span the view sees at the model's distance, over the view's span in
 * pixels. The field of view is the view's longer side's (HSDRawViewer's Camera narrows the vertical one by the aspect
 * when the view is wider than tall). It draws the model at the camera's Z (the scene file's: Fox's sits 22 units away
 * at a 70 degree field of view, Bowser's 1747 at 2), and zoom scales the model, not that distance, so this holds at
 * any zoom. `camera`: the renderer's (exportScene: z, fovRadians); `width`, `height`: the view's, in pixels.
 * -> scene units per pixel, or null when it is not known.
 */
export function cameraPanStep(camera, width, height) {
  const z = Math.abs(Number(camera?.z)), fov = Number(camera?.fovRadians)
  const pixels = Math.max(Number(width) || 0, Number(height) || 0)
  if (!(z > 0) || !(fov > 0 && fov < Math.PI) || !(pixels > 0)) return null
  return 2 * z * Math.tan(fov / 2) / pixels
}

/**
 * Drag to rotate, right-drag to pan, scroll to zoom. With `panStep` (a function: scene units per pixel, read at each
 * move) a pan follows the cursor on both axes: the renderer adds the camera's X as it is and draws its Y downwards, so
 * a drag right and down moves the model right and down. Without it, the older `panScale` (one sign for both axes, so
 * one axis ran against the cursor) is kept for the viewers that still use it.
 */
export function bindViewerInput({ element, windowTarget = window, documentTarget = document,
  sendCamera, onError = () => {}, panScale = 0.01, panStep = null, zoomScale = 0.05 }) {
  let drag = null
  const send = (...args) => {
    try { Promise.resolve(sendCamera(...args)).catch(onError) } catch (error) { onError(error) }
  }
  // Controls, and anything under [data-viewer-ignore] (overlay panels), keep
  // their own pointer/wheel behaviour instead of orbiting the camera.
  const interactive = event => event.target.closest?.('button, input, select, textarea, a, [data-viewer-ignore]')
  const release = () => {
    const previous = drag
    drag = null
    if (previous && element.hasPointerCapture?.(previous.id)) element.releasePointerCapture(previous.id)
  }
  const down = event => {
    if (interactive(event) || (event.button !== 0 && event.button !== 2) || drag) return
    event.preventDefault()
    element.focus({ preventScroll: true })
    drag = { id: event.pointerId, button: event.button, x: event.clientX, y: event.clientY }
    element.setPointerCapture(event.pointerId)
  }
  const move = event => {
    if (!drag || drag.id !== event.pointerId) return
    if (!event.buttons) { release(); return }
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y
    drag.x = event.clientX
    drag.y = event.clientY
    if (drag.button === 2 && panStep) {
      const step = Number(panStep())
      if (step > 0 && Number.isFinite(step)) send(0, 0, 0, dx * step, dy * step)
    } else if (drag.button === 2) send(0, 0, 0, dx * panScale, -dy * panScale)
    else send(dy * 0.5, dx * 0.5, 0, 0, 0)
  }
  const up = event => { if (drag?.id === event.pointerId) release() }
  const wheel = event => {
    if (interactive(event) || !event.deltaY) return
    event.preventDefault()
    send(0, 0, event.deltaY > 0 ? -zoomScale : zoomScale, 0, 0)
  }
  const context = event => { if (!interactive(event)) event.preventDefault() }
  const listeners = { pointerdown: down, pointermove: move, pointerup: up,
    pointercancel: up, lostpointercapture: up, wheel, contextmenu: context, blur: release }
  for (const [type, callback] of Object.entries(listeners)) element.addEventListener(type, callback, { passive: false })
  windowTarget.addEventListener('blur', release)
  documentTarget.addEventListener('visibilitychange', release)
  return () => {
    release()
    for (const [type, callback] of Object.entries(listeners)) element.removeEventListener(type, callback)
    windowTarget.removeEventListener('blur', release)
    documentTarget.removeEventListener('visibilitychange', release)
  }
}
