import { useState, useEffect } from 'react'

// Undo/redo stack for the paint canvas, including keyboard shortcuts and
// independent histories keyed by the session and owning texture.
export function useUndoRedo({ paintCanvasRef, sendTextureUpdate, selectedTextureIndex, resetKey, isOpen, skinCreatorStep, canEdit = () => true,
  layerHistory }) {
  const [histories, setHistories] = useState({})
  const historyKey = `${resetKey}:${selectedTextureIndex}`
  const undoStack = histories[historyKey]?.undo || []
  const redoStack = histories[historyKey]?.redo || []
  const updateStack = (kind, update) => setHistories(previous => {
    const entry = previous[historyKey] || { undo: [], redo: [] }
    return { ...previous, [historyKey]: { ...entry,
      [kind]: typeof update === 'function' ? update(entry[kind]) : update } }
  })
  const setUndoStack = update => updateStack('undo', update)
  const setRedoStack = update => updateStack('redo', update)
  const maxUndoSteps = 50

  // With a layer stack an entry is a snapshot object (which layer, or the whole
  // structure); without one it stays exactly what it always was -- the flat
  // canvas's ImageData. Both walk the same single history per texture.
  const capture = () => {
    if (layerHistory) return layerHistory.pixel()
    const canvas = paintCanvasRef.current
    if (!canvas) return null
    return canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height)
  }
  const apply = (state) => {
    if (layerHistory) { layerHistory.restore(state); return }
    const canvas = paintCanvasRef.current
    if (!canvas) return
    canvas.getContext('2d').putImageData(state, 0, 0)
  }

  // The counterpart of an entry, for the other stack: undoing a structural edit
  // has to stash the CURRENT structure, undoing a stroke the current pixels of
  // the layer that stroke touched.
  const mirrorOf = (entry) => {
    if (!layerHistory) return capture()
    return entry?.kind === 'structure' ? layerHistory.structure() : layerHistory.pixel(entry?.layerId)
  }

  // `state` is passed by structural layer edits, which have to snapshot the
  // stack BEFORE they change it; pixel edits let it capture the active layer.
  const saveToUndoStack = (state) => {
    if (!isOpen || !canEdit()) return
    const entry = state === undefined ? capture() : state
    if (!entry) return
    setUndoStack(prev => {
      const newStack = [...prev, entry]
      if (newStack.length > maxUndoSteps) newStack.shift()
      return newStack
    })
    setRedoStack([]) // Clear redo stack on new action
  }

  const undo = () => {
    if (!isOpen || !canEdit()) return
    if (undoStack.length === 0) return

    // Save current state to redo stack. It must be captured in the SHAPE of the
    // entry being undone, or a structural undo would come back as pixels.
    const previousState = undoStack[undoStack.length - 1]
    const currentState = mirrorOf(previousState)
    if (!currentState) return
    setRedoStack(prev => [...prev, currentState])

    setUndoStack(prev => prev.slice(0, -1))
    apply(previousState)
    sendTextureUpdate()
  }

  const redo = () => {
    if (!isOpen || !canEdit()) return
    if (redoStack.length === 0) return

    const nextState = redoStack[redoStack.length - 1]
    const currentState = mirrorOf(nextState)
    if (!currentState) return
    setUndoStack(prev => [...prev, currentState])

    setRedoStack(prev => prev.slice(0, -1))
    apply(nextState)
    sendTextureUpdate()
  }

  // Discard histories when the viewer session changes, never when selecting its partner.
  useEffect(() => { setHistories({}) }, [resetKey])

  // Keyboard shortcuts for undo/redo
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (!isOpen || skinCreatorStep !== 'edit') return
      if (e.ctrlKey || e.metaKey) {
        if (e.key === 'z' && !e.shiftKey) {
          e.preventDefault()
          undo()
        } else if ((e.key === 'z' && e.shiftKey) || e.key === 'y') {
          e.preventDefault()
          redo()
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, skinCreatorStep, undoStack, redoStack, historyKey])

  return { undoStack, redoStack, saveToUndoStack, undo, redo }
}
