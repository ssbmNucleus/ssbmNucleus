import { useEffect } from 'react'
import { textureKey, textureAddress, shouldReloadPaintCanvas } from './paintProtocol'

export function useTextureCanvasLoad({
  selectedTextureIndex, modelTextures, paintCanvasRef, editedTextures, canvasWritesRef,
  canvasOwnerRef, viewerGenerationRef, setCanvasOwner, paintCommand,
  fullTextureRequestRef, failViewer, selectionRef, layers, updateCanvasScale,
}) {
  // Load texture onto paint canvas when selected
  useEffect(() => {
    if (selectedTextureIndex === null || !modelTextures[selectedTextureIndex]) return

    const tex = modelTextures[selectedTextureIndex]
    const canvas = paintCanvasRef.current
    if (!canvas) return

    const key = textureKey(tex)
    const editedData = editedTextures[key]
    // Our own stroke coming back around: the canvas already shows these pixels,
    // and repainting would drop ownership mid-edit and eat the next stroke or
    // undo click.
    const publishedData = canvasWritesRef.current.get(key)
    if (!shouldReloadPaintCanvas({ textureId: key, canvasOwner: canvasOwnerRef.current,
      editedData, publishedData })) return
    // Pixels that arrived from outside the canvas (a palette recolor) ARE the
    // new flattened base, so the stack they were built on no longer describes
    // the texture and is reflattened to one layer.
    const externalWrite = Boolean(editedData) && editedData !== publishedData

    const generation = viewerGenerationRef.current
    let disposed = false
    canvasOwnerRef.current = null
    setCanvasOwner(null)
    const isCurrent = () => !disposed && generation === viewerGenerationRef.current && selectionRef.current === key
    if (!editedData) {
      // List thumbnails are downsampled previews. Never give tools/export a
      // canvas built from them, even while the full-resolution read is pending.
      // Single-file viewers use index-only replies; paired viewers additionally
      // correlate the session/request/member supplied by paintCommand.
      const command = paintCommand({ type: 'getFullTexture', ...textureAddress(key) })
      const fullRequest = { sessionId: command.sessionId, requestId: command.requestId,
        textureId: key, generation, width: tex.width, height: tex.height }
      fullTextureRequestRef.current = fullRequest
      fullRequest.fail = (error) => {
        if (!isCurrent() || fullTextureRequestRef.current !== fullRequest) return
        clearTimeout(fullRequest.timeout)
        fullTextureRequestRef.current = null
        failViewer(error)
      }
      fullRequest.timeout = setTimeout(() => fullRequest.fail(new Error('Reading the full-resolution texture timed out. Reconnect to retry.')), 15000)
      Promise.resolve().then(() => {
        if (isCurrent() && fullTextureRequestRef.current === fullRequest) return window.electron.viewerSend(command)
      }).then(sent => {
        if (sent === false) throw new Error('Viewer disconnected before reading texture')
      }).catch(fullRequest.fail)
      return () => {
        disposed = true
        clearTimeout(fullRequest.timeout)
        if (fullTextureRequestRef.current === fullRequest) fullTextureRequestRef.current = null
      }
    }
    const img = new Image()
    img.onload = () => {
      if (!isCurrent()) return
      canvas.width = tex.width
      canvas.height = tex.height
      const ctx = canvas.getContext('2d')
      ctx.imageSmoothingEnabled = false
      ctx.drawImage(img, 0, 0, tex.width, tex.height)
      layers.adoptCanvas(key, canvas, { reset: externalWrite })
      canvasOwnerRef.current = key
      setCanvasOwner(key)
      updateCanvasScale(canvas, tex.width, tex.height)
    }
    img.onerror = () => { if (isCurrent()) failViewer(new Error('Could not decode the edited texture. Your edits are retained.')) }
    img.src = editedData
    return () => { disposed = true }
  }, [selectedTextureIndex, modelTextures, editedTextures, updateCanvasScale])
}
