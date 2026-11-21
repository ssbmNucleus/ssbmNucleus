/**
 * Convert raw RGBA bytes (base64, as returned by /api/mex/project/build) into a
 * PNG data URL suitable for an <img> preview. Returns null on bad/empty input.
 */
export function rgbaToDataUrl(base64, w, h) {
  if (!base64 || !w || !h) return null
  try {
    const bin = atob(base64)
    if (bin.length !== w * h * 4) return null
    const bytes = new Uint8ClampedArray(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    canvas.getContext('2d').putImageData(new ImageData(bytes, w, h), 0, 0)
    return canvas.toDataURL('image/png')
  } catch {
    return null
  }
}
