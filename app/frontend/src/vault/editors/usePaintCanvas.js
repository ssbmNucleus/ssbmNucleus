import { useState, useRef, useEffect } from 'react'
import { getCanvasCoords, drawBrush, eraseBrush, drawLine, floodFill, replaceColor,
         selectionFromDrag, selectionHitZone, selectionCursor, gripRadius,
         moveSelection, resizeSelection, constrainDrag } from './canvasUtils'

/**
 * Drawing tools state and paint canvas mouse handlers.
 *
 * Two canvases, because of layers:
 *  - `viewCanvasRef` is the one ON SCREEN, holding the flattened image. Pointer
 *    coordinates and the texture's size come from it (an offscreen canvas has
 *    no layout box, so getBoundingClientRect would be all zeros), and so does
 *    the eyedropper -- it picks the colour you can see.
 *  - `targetCanvasRef` is where the tools actually draw: the active layer.
 * With no layer stack the two are the same canvas and nothing changes.
 */
export function usePaintCanvas({ viewCanvasRef, targetCanvasRef, saveToUndoStack, sendTextureUpdate,
                                 onLivePaint, zoom = 1, selectionKeysEnabled = false }) {
  const drawTargetRef = targetCanvasRef || viewCanvasRef
  // Strokes land on the offscreen active layer, so the visible canvas has to be
  // reflattened as the pointer moves -- without this you would see nothing at
  // all until you let go. Publishing to the 3D viewer still waits for mouse-up.
  const redraw = () => onLivePaint?.()
  const [isDrawing, setIsDrawing] = useState(false)
  const isDrawingRef = useRef(false) // Ref for interval callback access
  const lastDrawPos = useRef(null)

  // Drawing tools state
  const [activeTool, setActiveTool] = useState('pencil') // pencil, eraser, fill, replace, select, eyedropper
  const [drawColor, setDrawColor] = useState('#ff0000')
  const [brushSize, setBrushSize] = useState(1)
  // How far from the clicked color the replace tool still counts as a match.
  // 0 = only the exact color, which is what you want on flat pixel art.
  const [replaceTolerance, setReplaceTolerance] = useState(0)

  // Area selection: every tool is masked to it while it exists.
  const [selection, setSelection] = useState(null)
  const [pendingSelection, setPendingSelection] = useState(null)  // live drag rect
  const selectStart = useRef(null)
  // An existing selection can be dragged by its middle or resized by an edge or
  // corner, like paint.net -- `selectDrag` says which of those is in flight.
  const selectDrag = useRef(null)   // { kind: 'new'|'move'|'resize', zone, origin, start }
  const [hoverZone, setHoverZone] = useState(null)
  const clearSelection = () => {
    setSelection(null); setPendingSelection(null); setHoverZone(null); selectDrag.current = null
  }
  const selectAll = () => {
    const canvas = viewCanvasRef.current
    if (!canvas?.width || !canvas?.height) return
    setPendingSelection(null)
    setSelection({ x: 0, y: 0, w: canvas.width, h: canvas.height })
  }

  const pickColorAt = (x, y) => {
    const canvas = viewCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const pixel = ctx.getImageData(x, y, 1, 1).data
    const hex = '#' + [pixel[0], pixel[1], pixel[2]]
      .map(c => c.toString(16).padStart(2, '0')).join('')
    setDrawColor(hex)
  }

  const eyedropperPick = (x, y) => {
    pickColorAt(x, y)
    setActiveTool('pencil') // Switch back to pencil after picking
  }

  const handlePaintMouseDown = (e) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()

    const canvas = viewCanvasRef.current          // geometry: the canvas on screen
    const target = drawTargetRef.current           // pixels: the active layer
    const coords = getCanvasCoords(canvas, e)
    if (!coords || !target) return
    if (coords.x < 0 || coords.y < 0 || coords.x >= canvas.width || coords.y >= canvas.height) return

    if (activeTool === 'eyedropper') {
      eyedropperPick(coords.x, coords.y)
      return
    }

    if (activeTool === 'select') {
      // Grab an edge/corner to resize, the middle to move, anywhere else to
      // drag out a new one. A plain click on empty space clears the old one.
      const zone = selectionHitZone(selection, coords.x, coords.y, gripRadius(zoom))
      selectStart.current = coords
      setIsDrawing(true)
      isDrawingRef.current = true
      if (zone) {
        selectDrag.current = { kind: zone === 'inside' ? 'move' : 'resize', zone, origin: selection, start: coords }
        setPendingSelection(selection)
      } else {
        selectDrag.current = { kind: 'new', start: coords }
        setPendingSelection(null)
        setSelection(null)
      }
      return
    }

    // Fill and replace sample the layer they are about to change, the way
    // paint.net's bucket samples the active layer rather than the flattened
    // image -- filling from what you see would paint over a hole you can see
    // through.
    if (activeTool === 'replace') {
      saveToUndoStack()
      const changed = replaceColor(target, coords.x, coords.y, drawColor,
        { tolerance: replaceTolerance, selection })
      if (changed) sendTextureUpdate()
      return
    }

    if (activeTool === 'fill') {
      saveToUndoStack()
      floodFill(target, coords.x, coords.y, drawColor, selection)
      sendTextureUpdate()
      return
    }

    // Pencil or eraser - start drawing
    saveToUndoStack()
    setIsDrawing(true)
    isDrawingRef.current = true

    if (activeTool === 'pencil') {
      drawBrush(target, coords.x, coords.y, drawColor, brushSize, selection)
    } else if (activeTool === 'eraser') {
      eraseBrush(target, coords.x, coords.y, brushSize, selection)
    }
    redraw()
    lastDrawPos.current = coords
  }

  const handlePaintMouseMove = (e) => {
    const canvas = viewCanvasRef.current
    if (!isDrawing) {
      // Hovering with the select tool: the cursor advertises what a drag here
      // would do (move the box, or pull the edge you are over).
      if (activeTool === 'select') {
        const at = getCanvasCoords(canvas, e)
        const zone = at ? selectionHitZone(selection, at.x, at.y, gripRadius(zoom)) : null
        if (zone !== hoverZone) setHoverZone(zone)
      } else if (hoverZone) setHoverZone(null)
      return
    }
    const coords = getCanvasCoords(canvas, e)
    const target = drawTargetRef.current
    if (!coords || !target) return

    if (activeTool === 'select') {
      const drag = selectDrag.current
      if (!drag) return
      if (drag.kind === 'new') {
        const end = e.shiftKey ? constrainDrag(drag.start, coords) : coords
        setPendingSelection(selectionFromDrag(canvas, drag.start, end))
      } else {
        const dx = coords.x - drag.start.x, dy = coords.y - drag.start.y
        setPendingSelection(drag.kind === 'move'
          ? moveSelection(drag.origin, dx, dy, canvas)
          : resizeSelection(drag.origin, drag.zone, dx, dy, canvas))
      }
      return
    }

    const toolFn = activeTool === 'eraser'
      ? (x, y) => eraseBrush(target, x, y, brushSize, selection)
      : (x, y) => drawBrush(target, x, y, drawColor, brushSize, selection)

    if (lastDrawPos.current) {
      drawLine(lastDrawPos.current.x, lastDrawPos.current.y, coords.x, coords.y, toolFn)
    } else {
      toolFn(coords.x, coords.y)
    }
    redraw()
    lastDrawPos.current = coords
  }

  const handlePaintMouseUp = () => {
    if (!isDrawing) return
    setIsDrawing(false)
    isDrawingRef.current = false

    if (activeTool === 'select') {
      // A move or resize that collapsed the box counts as clearing it.
      setSelection(pendingSelection)
      setPendingSelection(null)
      selectStart.current = null
      selectDrag.current = null
      return   // selecting paints nothing, so there is nothing to send
    }

    lastDrawPos.current = null
    sendTextureUpdate()
  }

  // Ctrl+A / Ctrl+D / Escape, the three every editor has. Undo/redo's own
  // listener owns Ctrl+Z and Ctrl+Y (useUndoRedo).
  useEffect(() => {
    if (!selectionKeysEnabled) return
    const onKeyDown = (e) => {
      if (e.target?.closest?.('input, textarea, select, [contenteditable="true"]')) return
      if ((e.ctrlKey || e.metaKey) && e.key === 'a') { e.preventDefault(); selectAll() }
      else if ((e.ctrlKey || e.metaKey) && e.key === 'd') { e.preventDefault(); clearSelection() }
      else if (e.key === 'Escape' && (selection || pendingSelection)) { e.preventDefault(); clearSelection() }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectionKeysEnabled, selection, pendingSelection])

  return {
    activeTool,
    setActiveTool,
    drawColor,
    setDrawColor,
    brushSize,
    setBrushSize,
    replaceTolerance,
    setReplaceTolerance,
    selection,
    pendingSelection,
    clearSelection,
    selectAll,
    // What the pointer would do on a press right now, for the canvas cursor.
    paintCursor: activeTool === 'select' ? selectionCursor(hoverZone) : null,
    isDrawingRef,
    handlePaintMouseDown,
    handlePaintMouseMove,
    handlePaintMouseUp
  }
}
