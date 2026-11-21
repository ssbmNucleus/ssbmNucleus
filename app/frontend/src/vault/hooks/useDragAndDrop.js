/**
 * useDragAndDrop Hook
 *
 * Manages drag-and-drop functionality for reordering skins and stage variants.
 * Handles drag state, visual preview, and API mutations for reordering.
 */

import { useState, useRef } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'

export function useDragAndDrop({
  mode,
  // 'characters' or 'stages'
  selectedCharacter,
  selectedStage,
  onRefresh,
  fetchStageVariants,
}) {
  // State
  const [draggedItem, setDraggedItem] = useState(null) // { index, id }
  const [dragStartIndex, setDragStartIndex] = useState(null) // Original position when drag started
  const [dragOverIndex, setDragOverIndex] = useState(null) // For UI reactivity
  const [reordering, setReordering] = useState(false)
  const [previewOrder, setPreviewOrder] = useState(null) // Live preview of reordered items during drag
  const [dragTargetFolder, setDragTargetFolder] = useState(null) // Folder being hovered over during drag
  const [justDroppedId, setJustDroppedId] = useState(null) // ID of item that just dropped (for settle animation)
  const justDraggedRef = useRef(false) // Prevent click from firing right after drag
  const dropInProgressRef = useRef(false) // Track if drop is being processed
  const dragOverIndexRef = useRef(null) // Ref version for reliable access in handlers

  // Derived state
  const isDraggingActive = draggedItem !== null

  // Handlers
  const handleDragStart = (e, index, items) => {
    setDraggedItem({ index, id: items[index].id })
    setDragStartIndex(index) // Track original position for returning to same spot
    e.dataTransfer.effectAllowed = 'move'
    // Suppress the global "Drop to import" overlay for this in-app reorder drag.
    // Electron reports 'Files' in dataTransfer.types even for element drags, so
    // ImportFab keys off this flag to tell internal drags from OS file drops.
    document.documentElement.dataset.nucInternalDrag = '1'
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDragEnter = (e, index, items) => {
    e.preventDefault()
    if (!draggedItem) return

    // Hovering a folder while dragging a skin means "drop INTO this folder",
    // not "reorder around it" — highlight the folder instead of previewing.
    const target = items[index]
    const draggedIsFolder = items.find(i => i.id === draggedItem.id)?.type === 'folder'
    if (target?.type === 'folder' && !draggedIsFolder) {
      if (dragTargetFolder !== target.id) {
        dragOverIndexRef.current = null
        setDragOverIndex(null)
        setDragTargetFolder(target.id)
      }
      return
    }
    if (dragTargetFolder) setDragTargetFolder(null)

    // Only update if we've moved to a different position
    if (dragOverIndexRef.current !== index) {
      dragOverIndexRef.current = index // Update ref immediately
      setDragOverIndex(index) // Update state for UI

      // Find where the dragged item currently is in the items array
      const currentPos = items.findIndex(item => item.id === draggedItem.id)
      if (currentPos === -1 || currentPos === index) return

      // Move item from current position to target position
      const newOrder = [...items]
      const [removed] = newOrder.splice(currentPos, 1)
      newOrder.splice(index, 0, removed)

      setPreviewOrder(newOrder)
    }
  }

  const handleDragLeave = (e) => {
    // Only clear if leaving the container entirely
    if (e.currentTarget === e.target) {
      setDragOverIndex(null)
    }
  }

  const clearDragState = () => {
    dropInProgressRef.current = false
    dragOverIndexRef.current = null
    setReordering(false)
    setDraggedItem(null)
    setDragStartIndex(null)
    setDragOverIndex(null)
    setPreviewOrder(null)
    setDragTargetFolder(null)
  }

  // Drop a skin onto a folder card — assign it to that folder
  const handleDropIntoFolder = async (folderId) => {
    if (!draggedItem || !selectedCharacter) {
      clearDragState()
      return
    }
    dropInProgressRef.current = true
    setReordering(true)
    try {
      await api.post('/storage/skins/set-folder', {
        character: selectedCharacter,
        skinId: draggedItem.id,
        folderId
      })
      playSound('boop')
      const droppedId = draggedItem.id
      setJustDroppedId(droppedId)
      setTimeout(() => setJustDroppedId(null), 400)
      await onRefresh()
      requestAnimationFrame(clearDragState)
      return
    } catch (err) {
      console.error('Move to folder error:', err)
      alert(`Move to folder error: ${err.message}`)
    }
    clearDragState()
  }

  const handleSkinDrop = async (e) => {
    e.preventDefault()
    if (!draggedItem) return

    // Dropping on a highlighted folder = move into that folder
    if (dragTargetFolder) {
      await handleDropIntoFolder(dragTargetFolder)
      return
    }

    if (dragOverIndexRef.current === null) return

    dropInProgressRef.current = true

    const fromIndex = dragStartIndex
    const toIndex = dragOverIndexRef.current

    if (fromIndex === toIndex || fromIndex === null || !selectedCharacter) {
      dropInProgressRef.current = false
      dragOverIndexRef.current = null
      setDraggedItem(null)
      setDragStartIndex(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
      return
    }

    setReordering(true)

    try {
      await api.post('/storage/costumes/reorder', {
        character: selectedCharacter,
        fromIndex,
        toIndex
      })

      playSound('boop') // Play click sound on reorder complete

      // Trigger settle animation on dropped item
      const droppedId = draggedItem.id
      setJustDroppedId(droppedId)
      setTimeout(() => setJustDroppedId(null), 400) // Clear after animation

      // Refresh metadata to get updated order
      await onRefresh()

      // Clear drag state after refresh completes - slight delay to let React render new data first
      requestAnimationFrame(() => {
        dropInProgressRef.current = false
        dragOverIndexRef.current = null
        setReordering(false)
        setDraggedItem(null)
        setDragStartIndex(null)
        setDragOverIndex(null)
        setPreviewOrder(null)
      })
      return
    } catch (err) {
      console.error('Reorder error:', err)
      alert(`Reorder error: ${err.message}`)
    }
    // Only clear on error/cancel - success case handles cleanup above
    dropInProgressRef.current = false
    dragOverIndexRef.current = null
    setReordering(false)
    setDraggedItem(null)
    setDragStartIndex(null)
    setDragOverIndex(null)
    setPreviewOrder(null)
  }

  // Drop a stage variant onto a folder card — assign it to that folder
  const handleVariantDropIntoFolder = async (folderId) => {
    if (!draggedItem || !selectedStage) {
      clearDragState()
      return
    }
    dropInProgressRef.current = true
    setReordering(true)
    try {
      await api.post('/storage/stage-variants/set-folder', {
        stageFolder: selectedStage.folder,
        variantId: draggedItem.id,
        folderId
      })
      playSound('boop')
      const droppedId = draggedItem.id
      setJustDroppedId(droppedId)
      setTimeout(() => setJustDroppedId(null), 400)
      await fetchStageVariants()
      await onRefresh()
      requestAnimationFrame(clearDragState)
      return
    } catch (err) {
      console.error('Move variant to folder error:', err)
      alert(`Move to folder error: ${err.message}`)
    }
    clearDragState()
  }

  const handleVariantDrop = async (e) => {
    e.preventDefault()
    if (!draggedItem) return

    // Dropping on a highlighted folder = move into that folder
    if (dragTargetFolder) {
      await handleVariantDropIntoFolder(dragTargetFolder)
      return
    }

    if (dragOverIndexRef.current === null) return

    dropInProgressRef.current = true // Mark drop as in progress before dragEnd fires

    const fromIndex = dragStartIndex
    const toIndex = dragOverIndexRef.current // Use ref for reliable value

    if (fromIndex === toIndex || fromIndex === null || !selectedStage) {
      dropInProgressRef.current = false
      dragOverIndexRef.current = null
      setDraggedItem(null)
      setDragStartIndex(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
      return
    }

    setReordering(true)

    try {
      await api.post('/storage/stages/reorder', {
        stageFolder: selectedStage.folder,
        fromIndex,
        toIndex
      })

      playSound('boop') // Play click sound on reorder complete

      // Trigger settle animation on dropped item
      const droppedId = draggedItem.id
      setJustDroppedId(droppedId)
      setTimeout(() => setJustDroppedId(null), 400) // Clear after animation

      // Refresh stage variants and metadata
      await fetchStageVariants()
      await onRefresh()

      // Clear drag state after refresh completes - slight delay to let React render new data first
      requestAnimationFrame(() => {
        dropInProgressRef.current = false
        dragOverIndexRef.current = null
        setReordering(false)
        setDraggedItem(null)
        setDragStartIndex(null)
        setDragOverIndex(null)
        setPreviewOrder(null)
      })
      return
    } catch (err) {
      console.error('Reorder error:', err)
      alert(`Reorder error: ${err.message}`)
    }
    // Only clear on error/cancel - success case handles cleanup above
    dropInProgressRef.current = false
    dragOverIndexRef.current = null
    setReordering(false)
    setDraggedItem(null)
    setDragStartIndex(null)
    setDragOverIndex(null)
    setPreviewOrder(null)
  }

  const handleDragEnd = () => {
    // Re-enable the import overlay now that the in-app drag is over.
    delete document.documentElement.dataset.nucInternalDrag
    // If drop is in progress, let the drop handler clean up
    // This prevents the flash when previewOrder is cleared before refresh completes
    if (!dropInProgressRef.current) {
      dragOverIndexRef.current = null
      setDraggedItem(null)
      setDragStartIndex(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
    }
    setDragTargetFolder(null)
    // Prevent click from firing right after drag
    justDraggedRef.current = true
    setTimeout(() => { justDraggedRef.current = false }, 100)
  }

  return {
    // State
    draggedItem,
    dragStartIndex,
    dragOverIndex,
    previewOrder,
    reordering,
    setReordering,
    dragTargetFolder,
    justDraggedRef,
    isDraggingActive,
    justDroppedId,
    setJustDroppedId, // Expose setter for custom drop handlers
    setDragTargetFolder, // Expose setter for folder drag logic

    // Handlers
    handleDragStart,
    handleDragOver,
    handleDragEnter,
    handleDragLeave,
    handleSkinDrop,
    handleVariantDrop,
    handleDragEnd
  }
}
