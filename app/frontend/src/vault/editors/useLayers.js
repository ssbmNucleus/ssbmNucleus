/**
 * useLayers — a paint.net-style layer stack for the paint canvas.
 *
 * A Melee texture is a flat image (CI8 / RGB5A3): the game, the DAT and the
 * live viewer only ever see flattened pixels, and nothing in a costume file can
 * carry a stack. So layers are an EDITOR-SIDE construct that lives for the
 * session and is flattened on every commit:
 *
 *   layer canvases (offscreen)  --composite-->  paintCanvasRef  --> viewer/DAT
 *
 * That split is what keeps the rest of the editor untouched. `paintCanvasRef`
 * stays the flattened truth every existing consumer already reads (the viewer
 * push, editedTextures, export, the highlight probe, the eyedropper), while
 * tools and undo are pointed at the ACTIVE layer's canvas instead.
 *
 * Stacks are held per texture for the session, so switching textures and coming
 * back keeps your layers. Closing the editor does not, and neither does a
 * palette recolor — see `adoptCanvas`'s `reset` for why that one reflattens.
 */
import { useCallback, useRef, useState } from 'react'

// Canvas2D names, so composite() can hand the mode straight to the context.
export const BLEND_MODES = [
  { id: 'source-over', name: 'Normal' },
  { id: 'multiply', name: 'Multiply' },
  { id: 'screen', name: 'Screen' },
  { id: 'overlay', name: 'Overlay' },
  { id: 'darken', name: 'Darken' },
  { id: 'lighten', name: 'Lighten' },
  { id: 'color-dodge', name: 'Color Dodge' },
  { id: 'color-burn', name: 'Color Burn' },
  { id: 'hard-light', name: 'Hard Light' },
  { id: 'soft-light', name: 'Soft Light' },
  { id: 'difference', name: 'Difference' },
  { id: 'exclusion', name: 'Exclusion' },
  { id: 'hue', name: 'Hue' },
  { id: 'saturation', name: 'Saturation' },
  { id: 'color', name: 'Color' },
  { id: 'luminosity', name: 'Luminosity' },
  { id: 'lighter', name: 'Additive' }
]

const blankCanvas = (width, height) => {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  canvas.getContext('2d').imageSmoothingEnabled = false
  return canvas
}

const copyOf = (source) => {
  const canvas = blankCanvas(source.width, source.height)
  canvas.getContext('2d').drawImage(source, 0, 0)
  return canvas
}

/**
 * Flatten a stack (bottom-up) onto one canvas. Kept free of React so the
 * blending can be exercised against a real Canvas2D context.
 */
export function compositeLayers(target, layers) {
  if (!target || !layers) return
  const ctx = target.getContext('2d')
  ctx.save()
  ctx.globalAlpha = 1
  ctx.globalCompositeOperation = 'source-over'
  ctx.clearRect(0, 0, target.width, target.height)
  for (const layer of layers) {
    if (!layer.visible || layer.opacity <= 0) continue
    ctx.globalAlpha = layer.opacity
    // A blend mode only has a backdrop to work against once something is under
    // it; on the bottom layer Canvas2D falls back to a plain draw.
    ctx.globalCompositeOperation = layer.blend
    ctx.drawImage(layer.canvas, 0, 0)
  }
  ctx.restore()
}

// Metadata only — the UI never touches a layer's canvas.
const describe = (layer) => ({
  id: layer.id, name: layer.name, visible: layer.visible,
  opacity: layer.opacity, blend: layer.blend
})

export function useLayers({ paintCanvasRef, onComposite }) {
  const stacks = useRef(new Map())        // textureId -> { layers: [bottom..top], activeId }
  const textureRef = useRef(null)         // the texture the canvas is currently showing
  const activeLayerRef = useRef(null)     // the canvas tools and undo write into
  const seq = useRef(0)
  const [view, setView] = useState({ layers: [], activeId: null })

  // onComposite (sendTextureUpdate) is rebuilt every render; go through a ref so
  // the callbacks below can stay stable.
  const sink = useRef(onComposite)
  sink.current = onComposite

  const stack = () => stacks.current.get(textureRef.current) || null
  const activeOf = (entry) => entry?.layers.find(layer => layer.id === entry.activeId) || null

  const publish = useCallback((entry) => {
    activeLayerRef.current = activeOf(entry)?.canvas || null
    setView(entry ? { layers: entry.layers.map(describe), activeId: entry.activeId } : { layers: [], activeId: null })
  }, [])

  /** Flatten the stack onto the visible canvas. */
  const composite = useCallback(() => {
    compositeLayers(paintCanvasRef.current, stack()?.layers)
  }, [paintCanvasRef])

  /** Flatten, then publish the result the way a stroke would. */
  const commit = useCallback(() => {
    composite()
    sink.current?.()
  }, [composite])

  /**
   * Point the stack at `textureId`, whose pixels are already on the canvas.
   *
   * `reset` reflattens: the palette recolor rewrites a texture's flattened
   * pixels without ever going through the canvas, so the recolored image IS the
   * new base and any stack built on the old one no longer describes it.
   */
  const adoptCanvas = useCallback((textureId, canvas, { reset = false } = {}) => {
    if (!textureId || !canvas?.width || !canvas?.height) return
    textureRef.current = textureId
    const existing = reset ? null : stacks.current.get(textureId)
    const sized = existing?.layers.every(layer =>
      layer.canvas.width === canvas.width && layer.canvas.height === canvas.height)
    if (existing && sized) {
      publish(existing)
      composite()            // repaint the stack over the flattened image
      return
    }
    const background = { id: `layer-${++seq.current}`, name: 'Background', visible: true,
      opacity: 1, blend: 'source-over', canvas: copyOf(canvas) }
    const entry = { layers: [background], activeId: background.id }
    stacks.current.set(textureId, entry)
    publish(entry)
  }, [composite, publish])

  const forget = useCallback((textureId) => {
    if (textureId) stacks.current.delete(textureId)
    else stacks.current.clear()
    if (!textureId || textureId === textureRef.current) {
      textureRef.current = textureId ? textureRef.current : null
      activeLayerRef.current = null
      setView({ layers: [], activeId: null })
    }
  }, [])

  // ---- history -----------------------------------------------------------
  // Pixel edits snapshot only the layer they touched; structural edits (add,
  // delete, reorder, opacity, blend, merge) snapshot the whole stack, which is
  // cheap because they are rare. Both go on the SAME stack, so Ctrl+Z walks
  // back through everything in the order it happened, like any editor.

  // `layerId` targets a specific layer -- undo/redo needs the pixels of the
  // layer the entry it is replacing belongs to, which is not always the active
  // one (you can select another layer and then hit Ctrl+Z).
  const pixelSnapshot = useCallback((layerId) => {
    const entry = stack()
    const layer = layerId
      ? entry?.layers.find(row => row.id === layerId) || null
      : activeOf(entry)
    if (!layer) return null
    const ctx = layer.canvas.getContext('2d')
    return { kind: 'pixels', layerId: layer.id,
      imageData: ctx.getImageData(0, 0, layer.canvas.width, layer.canvas.height) }
  }, [])

  const structureSnapshot = useCallback(() => {
    const entry = stack()
    if (!entry) return null
    return { kind: 'structure', activeId: entry.activeId,
      layers: entry.layers.map(layer => ({ ...layer, canvas: copyOf(layer.canvas) })) }
  }, [])

  const restoreSnapshot = useCallback((snapshot) => {
    const entry = stack()
    if (!entry || !snapshot) return
    if (snapshot.kind === 'structure') {
      entry.layers = snapshot.layers.map(layer => ({ ...layer, canvas: copyOf(layer.canvas) }))
      entry.activeId = entry.layers.some(layer => layer.id === snapshot.activeId)
        ? snapshot.activeId : entry.layers[entry.layers.length - 1]?.id
      publish(entry)
    } else {
      const layer = entry.layers.find(row => row.id === snapshot.layerId)
      if (!layer) return          // the layer was deleted; the structure entry owns that undo
      layer.canvas.getContext('2d').putImageData(snapshot.imageData, 0, 0)
    }
    composite()
  }, [composite, publish])

  // ---- structural operations ---------------------------------------------
  // Each mutates in place and republishes; callers wrap them with a history
  // push (see layerAction in SkinCreator) so every one of them is undoable.

  const mutate = (fn) => {
    const entry = stack()
    if (!entry) return
    fn(entry)
    publish(entry)
    commit()
  }

  const addLayer = useCallback(() => mutate(entry => {
    const base = paintCanvasRef.current
    const layer = { id: `layer-${++seq.current}`, name: `Layer ${entry.layers.length + 1}`,
      visible: true, opacity: 1, blend: 'source-over', canvas: blankCanvas(base.width, base.height) }
    const above = entry.layers.findIndex(row => row.id === entry.activeId) + 1
    entry.layers.splice(above || entry.layers.length, 0, layer)
    entry.activeId = layer.id
  }), [paintCanvasRef])

  const duplicateLayer = useCallback((id) => mutate(entry => {
    const index = entry.layers.findIndex(row => row.id === id)
    const source = entry.layers[index]
    if (!source) return
    const copy = { ...source, id: `layer-${++seq.current}`, name: `${source.name} copy`,
      canvas: copyOf(source.canvas) }
    entry.layers.splice(index + 1, 0, copy)
    entry.activeId = copy.id
  }), [])

  const deleteLayer = useCallback((id) => mutate(entry => {
    if (entry.layers.length <= 1) return     // a texture always has pixels
    const index = entry.layers.findIndex(row => row.id === id)
    if (index < 0) return
    entry.layers.splice(index, 1)
    if (entry.activeId === id) entry.activeId = entry.layers[Math.min(index, entry.layers.length - 1)].id
  }), [])

  /** offset +1 moves the layer up the stack (towards the viewer). */
  const moveLayer = useCallback((id, offset) => mutate(entry => {
    const index = entry.layers.findIndex(row => row.id === id)
    const target = index + offset
    if (index < 0 || target < 0 || target >= entry.layers.length) return
    const [layer] = entry.layers.splice(index, 1)
    entry.layers.splice(target, 0, layer)
  }), [])

  /** Draw a layer into the one below it, exactly as the composite would. */
  const mergeDown = useCallback((id) => mutate(entry => {
    const index = entry.layers.findIndex(row => row.id === id)
    if (index <= 0) return
    const upper = entry.layers[index], lower = entry.layers[index - 1]
    const ctx = lower.canvas.getContext('2d')
    ctx.save()
    ctx.globalAlpha = upper.visible ? upper.opacity : 0
    ctx.globalCompositeOperation = upper.blend
    ctx.drawImage(upper.canvas, 0, 0)
    ctx.restore()
    entry.layers.splice(index, 1)
    entry.activeId = lower.id
  }), [])

  /**
   * `live` is for controls that stream while you hold them (the opacity
   * slider): the flattened canvas follows every tick, but the 3D viewer is only
   * pushed once you let go, instead of re-encoding the texture per pixel of
   * slider travel.
   */
  const setLayerProp = useCallback((id, patch, { live = false } = {}) => {
    const entry = stack()
    const layer = entry?.layers.find(row => row.id === id)
    if (!layer) return
    Object.assign(layer, patch)
    publish(entry)
    if (live) composite()
    else commit()
  }, [commit, composite, publish])

  // Selecting a layer changes nothing about the image, so it neither commits
  // nor goes on the undo stack.
  const setActiveLayer = useCallback((id) => {
    const entry = stack()
    if (!entry || !entry.layers.some(layer => layer.id === id)) return
    entry.activeId = id
    publish(entry)
  }, [publish])

  return {
    layers: view.layers, activeId: view.activeId,
    activeLayerRef,
    hasStack: view.layers.length > 0,
    adoptCanvas, forget, composite, commit,
    pixelSnapshot, structureSnapshot, restoreSnapshot,
    addLayer, duplicateLayer, deleteLayer, moveLayer, mergeDown, setLayerProp, setActiveLayer
  }
}
