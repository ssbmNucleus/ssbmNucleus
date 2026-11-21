/**
 * Convert a DOM element rect to a PHYSICAL-pixel screen rect for Win32
 * SetWindowPos (HSDRawViewer / Dolphin embedding).
 *
 * Page-zoom gotcha: the app runs under a resolution-adaptive zoom factor
 * (electron/shell/window.js applyDisplayZoom). Zoom multiplies
 * window.devicePixelRatio (dpr = system display scale x page zoom) and
 * shrinks CSS pixels, but window.screenLeft/screenTop/outerHeight stay in
 * device-independent pixels. So element offsets convert with dpr, while
 * window-origin values convert with the SYSTEM scale (dpr / zoom), and the
 * chrome height must compare like units (outerHeight DIP vs innerHeight
 * CSS px). At zoom 1 this reduces to the old (screenLeft + rect.left) * dpr.
 *
 * @param {DOMRect} rect - element.getBoundingClientRect()
 * @returns {{x: number, y: number, width: number, height: number}}
 */
export function elementScreenRect(rect) {
  const dpr = window.devicePixelRatio || 1
  const zoom = window.electron?.getZoomFactor?.() || 1
  const systemScale = dpr / zoom

  // On Windows, screenX/Y may go negative for window chrome; screenLeft/Top
  // are the reliable pair.
  const screenLeft = window.screenLeft !== undefined ? window.screenLeft : window.screenX
  const screenTop = window.screenTop !== undefined ? window.screenTop : window.screenY

  // Electron window chrome (title bar) height, in DIPs.
  const chromeDip = window.outerHeight - window.innerHeight * zoom

  return {
    x: Math.round(screenLeft * systemScale + rect.left * dpr),
    y: Math.round((screenTop + chromeDip) * systemScale + rect.top * dpr),
    width: Math.round(rect.width * dpr),
    height: Math.round(rect.height * dpr)
  }
}
