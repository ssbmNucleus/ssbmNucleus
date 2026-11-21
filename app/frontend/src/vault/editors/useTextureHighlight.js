import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * useTextureHighlight — "where does this texture live on the model?"
 *
 * The viewer has no hit-testing, but it does take live texture pushes, so the
 * answer is the flat-colour PROBE trick done in-place: replace the texture with
 * a solid colour for a moment and whatever lights up on the 3D preview is where
 * that texture is used. Two colours alternate so the flash reads as a flash
 * even on a model that is already magenta.
 *
 * Guarantees, because this writes into the DAT the viewer would export:
 *  - alpha is copied from the real texture, so the silhouette never changes
 *  - the ORIGINAL pixels are captured up front and always pushed back, keyed to
 *    the texture they came from — so a restore is correct even if the canvas
 *    has moved on to another texture by then
 *  - painting is blocked for the ~1s the probe is up, so the captured original
 *    cannot go stale behind us
 *  - nothing here touches editedTextures, the undo stack, or the dirty flag:
 *    a highlight is not an edit
 */

const PROBE_COLORS = [[255, 0, 255], [0, 255, 255], [255, 0, 255]]
const STEP_MS = 240

const canvasToBase64 = (canvas) =>
  canvas.toDataURL('image/png').replace('data:image/png;base64,', '')

// Flat colour where the texture is opaque, untouched alpha everywhere else.
const probeImage = (canvas, [r, g, b]) => {
  const source = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height)
  const probe = document.createElement('canvas')
  probe.width = canvas.width
  probe.height = canvas.height
  const data = source.data
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] === 0) continue
    data[i] = r
    data[i + 1] = g
    data[i + 2] = b
  }
  probe.getContext('2d').putImageData(source, 0, 0)
  return canvasToBase64(probe)
}

export function useTextureHighlight({ paintCanvasRef, pushTexture, enabled = true }) {
  const timers = useRef([])
  const live = useRef(null)          // { textureId, original } while a probe is up
  const [highlighting, setHighlighting] = useState(false)

  // Everything the callbacks need lives in refs so `flash` and `cancelHighlight`
  // keep a STABLE identity. Otherwise showing the probe re-renders the caller,
  // the callbacks are rebuilt, and any effect keyed on them tears the flash
  // down a frame after it started.
  const latest = useRef({ pushTexture, enabled })
  latest.current = { pushTexture, enabled }

  const clearTimers = () => {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }

  const cancelHighlight = useCallback(() => {
    clearTimers()
    const state = live.current
    live.current = null
    setHighlighting(false)
    if (state) latest.current.pushTexture(state.textureId, state.original)
  }, [])

  const flash = useCallback((textureId) => {
    const canvas = paintCanvasRef.current
    if (!latest.current.enabled || !canvas || !textureId || !canvas.width || !canvas.height) return
    cancelHighlight()
    let original, probes
    try {
      original = canvasToBase64(canvas)
      probes = PROBE_COLORS.map(color => probeImage(canvas, color))
    } catch {
      return    // a tainted or zero-sized canvas simply does not get a highlight
    }
    live.current = { textureId, original }
    setHighlighting(true)
    probes.forEach((data, step) => {
      timers.current.push(setTimeout(() => {
        if (live.current?.textureId === textureId) latest.current.pushTexture(textureId, data)
      }, step * STEP_MS))
    })
    timers.current.push(setTimeout(cancelHighlight, probes.length * STEP_MS))
  }, [paintCanvasRef, cancelHighlight])

  // Leaving the editor mid-flash must not strand the probe in the DAT.
  useEffect(() => cancelHighlight, [cancelHighlight])

  return { flash, cancelHighlight, highlighting }
}
