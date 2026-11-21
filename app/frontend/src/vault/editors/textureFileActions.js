import { isCurrentPaintTarget } from './paintProtocol'

// PNG export/import of the texture on the paint canvas. An import replaces the
// active layer (one undo step); the assistant's texture requests use it too.
export function createTextureFileActions({
  selectedTextureIndex, modelTextures, paintCanvasRef, canvasOwnerRef, selectedTextureId,
  viewerGenerationRef, selectionRevisionRef, selectionRef, layers, saveToUndoStack,
}) {
  // Export texture as PNG
  const exportTexture = () => {
    if (selectedTextureIndex === null || !modelTextures[selectedTextureIndex]) return
    const canvas = paintCanvasRef.current
    if (!canvas || canvasOwnerRef.current !== selectedTextureId) return

    const tex = modelTextures[selectedTextureIndex]
    const dataUrl = canvas.toDataURL('image/png')
    const a = document.createElement('a')
    a.href = dataUrl
    a.download = `${tex.memberId ? `${tex.memberId}_` : ''}${tex.name || `texture_${tex.index}`}.png`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  // Import texture from PNG
  const importTexture = (e) => {
    const file = e.target.files?.[0]
    if (!file || selectedTextureIndex === null || canvasOwnerRef.current !== selectedTextureId) return

    const generation = viewerGenerationRef.current
    const target = { generation, textureId: selectedTextureId, selection: selectionRevisionRef.current }
    const isCurrent = () => isCurrentPaintTarget(target, { generation: viewerGenerationRef.current,
      textureId: selectionRef.current, selection: selectionRevisionRef.current })
    const reader = new FileReader()
    reader.onload = (event) => {
      if (!isCurrent()) return
      const img = new Image()
      img.onload = () => {
        if (!isCurrent()) return
        // An imported PNG (from the file picker or the assistant) replaces the
        // ACTIVE LAYER, so it can be dialled back with opacity or erased into
        // instead of flattening whatever else is stacked up.
        const canvas = layers.activeLayerRef.current
        if (!canvas) return

        // Save to undo stack before importing
        saveToUndoStack()

        const ctx = canvas.getContext('2d')
        ctx.clearRect(0, 0, canvas.width, canvas.height)
        ctx.imageSmoothingEnabled = false
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
        layers.commit()
      }
      img.src = event.target.result
    }
    reader.readAsDataURL(file)

    // Reset the input so the same file can be selected again
    e.target.value = ''
  }

  return { exportTexture, importTexture }
}
