import { useState, useRef } from 'react'
import { useAutoAnimate } from '@formkit/auto-animate/react'
import { buildDisplayList, countSkinsInFolder } from '../lib/storageViewerUtils'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import FolderCard from '../FolderCard'

const SkeletonCard = () => (
  <div className="stage-card skeleton-card">
    <div className="stage-icon-container">
      <div className="skeleton skeleton-image"></div>
    </div>
    <div className="skeleton skeleton-text" style={{ width: '60%', height: '12px' }}></div>
  </div>
)

export default function CustomStagesGrid({
  customStages,
  isLoading,
  onSelectStage,
  onBack,
  onRefresh
}) {
  // Drag state
  const [draggedItem, setDraggedItem] = useState(null) // { id }
  const [dragStartIndex, setDragStartIndex] = useState(null)
  const [previewOrder, setPreviewOrder] = useState(null)
  const [reordering, setReordering] = useState(false)
  const [justDroppedId, setJustDroppedId] = useState(null)
  const [dragTargetFolder, setDragTargetFolder] = useState(null)
  const dragOverIndexRef = useRef(null)
  const dropInProgressRef = useRef(false)
  const justDraggedRef = useRef(false)

  // Folder state
  const [expandedFolders, setExpandedFolders] = useState({})
  const [editingFolderId, setEditingFolderId] = useState(null)
  const [editingFolderName, setEditingFolderName] = useState('')

  const isDraggingActive = draggedItem !== null
  const itemsForDisplay = previewOrder || customStages
  const displayList = buildDisplayList(itemsForDisplay, expandedFolders)

  const [animateRef, enableAnimations] = useAutoAnimate({ duration: 150 })
  enableAnimations(!isDraggingActive)

  // ── Drag handlers ──────────────────────────────────────────
  const handleDragStart = (e, index, items) => {
    setDraggedItem({ id: items[index].id })
    setDragStartIndex(index)
    e.dataTransfer.effectAllowed = 'move'
    // Suppress the global "Drop to import" overlay for this in-app reorder drag
    // (Electron tags element drags with 'Files' otherwise — see ImportFab).
    document.documentElement.dataset.nucInternalDrag = '1'
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDragEnter = (e, index, items) => {
    e.preventDefault()
    if (!draggedItem) return

    // Hovering a folder while dragging a stage = "drop INTO this folder"
    const target = items[index]
    const draggedIsFolder = items.find(i => i.id === draggedItem.id)?.type === 'folder'
    if (target?.type === 'folder' && !draggedIsFolder) {
      if (dragTargetFolder !== target.id) {
        dragOverIndexRef.current = null
        setDragTargetFolder(target.id)
      }
      return
    }
    if (dragTargetFolder) setDragTargetFolder(null)

    if (dragOverIndexRef.current === index) return
    dragOverIndexRef.current = index

    const currentPos = items.findIndex(item => item.id === draggedItem.id)
    if (currentPos === -1 || currentPos === index) return

    const newOrder = [...items]
    const [removed] = newOrder.splice(currentPos, 1)
    newOrder.splice(index, 0, removed)
    setPreviewOrder(newOrder)
  }

  const cleanupDrag = () => {
    dragOverIndexRef.current = null
    dropInProgressRef.current = false
    setReordering(false)
    setDraggedItem(null)
    setDragStartIndex(null)
    setPreviewOrder(null)
    setDragTargetFolder(null)
  }

  const handleDropIntoFolder = async (folderId) => {
    if (!draggedItem) {
      cleanupDrag()
      return
    }
    dropInProgressRef.current = true
    setReordering(true)
    try {
      await api.post('/custom-stages/set-folder', { stageId: draggedItem.id, folderId })
      playSound('boop')
      const droppedId = draggedItem.id
      setJustDroppedId(droppedId)
      setTimeout(() => setJustDroppedId(null), 400)
      await onRefresh()
      requestAnimationFrame(cleanupDrag)
      return
    } catch (err) {
      console.error('Move to folder error:', err)
      alert(`Move to folder failed: ${err.message}`)
    }
    cleanupDrag()
  }

  const handleDrop = async (e) => {
    e.preventDefault()
    if (!draggedItem) return

    if (dragTargetFolder) {
      await handleDropIntoFolder(dragTargetFolder)
      return
    }

    if (dragOverIndexRef.current === null) return
    dropInProgressRef.current = true

    const fromIndex = dragStartIndex
    const toIndex = dragOverIndexRef.current

    if (fromIndex === toIndex || fromIndex === null) {
      cleanupDrag()
      return
    }

    setReordering(true)
    try {
      await api.post('/custom-stages/reorder', { fromIndex, toIndex })
      playSound('boop')
      const droppedId = draggedItem.id
      setJustDroppedId(droppedId)
      setTimeout(() => setJustDroppedId(null), 400)
      await onRefresh()
      requestAnimationFrame(cleanupDrag)
      return
    } catch (err) {
      console.error('Reorder error:', err)
      alert(`Reorder failed: ${err.message}`)
    }
    cleanupDrag()
  }

  const handleDragEnd = () => {
    delete document.documentElement.dataset.nucInternalDrag
    if (!dropInProgressRef.current) cleanupDrag()
    else setDragTargetFolder(null)
    justDraggedRef.current = true
    setTimeout(() => { justDraggedRef.current = false }, 100)
  }

  // ── Folder handlers ────────────────────────────────────────
  const toggleFolder = async (folderId, currentExpanded) => {
    setExpandedFolders(prev => ({
      ...prev,
      [folderId]: currentExpanded !== undefined ? !currentExpanded : !(prev[folderId] ?? true)
    }))
    try {
      await api.post('/custom-stages/folders/toggle', { folderId })
    } catch (err) {
      console.error('Toggle folder error:', err)
    }
  }

  const handleCreateFolder = async () => {
    try {
      const data = await api.post('/custom-stages/folders/create', { name: 'New Folder' })
      await onRefresh()
      setEditingFolderId(data.folder.id)
      setEditingFolderName(data.folder.name)
    } catch (err) {
      alert(`Create folder failed: ${err.message}`)
    }
  }

  const saveFolderName = async (folderId) => {
    if (!editingFolderName.trim()) {
      setEditingFolderId(null)
      return
    }
    try {
      await api.post('/custom-stages/folders/rename', { folderId, newName: editingFolderName.trim() })
      await onRefresh()
    } catch (err) {
      alert(`Rename folder failed: ${err.message}`)
    } finally {
      setEditingFolderId(null)
      setEditingFolderName('')
    }
  }

  const deleteFolder = async (folderId) => {
    if (!await appConfirm('Delete this folder? Stages inside will move out, not be deleted.', {
      title: 'Delete Folder',
      confirmText: 'Delete',
    })) return
    try {
      await api.post('/custom-stages/folders/delete', { folderId })
      await onRefresh()
    } catch (err) {
      alert(`Delete folder failed: ${err.message}`)
    }
  }

  // ── Render ─────────────────────────────────────────────────
  const stageCount = customStages.filter(s => s.type !== 'folder').length

  return (
    <div className="grid-wrapper">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap', width: '100%' }}>
        <button
          className="mode-btn"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('back'); onBack(); }}
        >
          ← Back to Stages
        </button>

        <div className="character-header-actions" style={{ marginBottom: 0, marginLeft: 'auto' }}>
          <button
            className="character-action-button"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); handleCreateFolder(); }}
            aria-label="New folder"
            title="Create a folder to group these custom stages"
          >
            📁
          </button>
        </div>
      </div>

      <div className={`custom-stages-grid${isDraggingActive ? ' is-dragging' : ''}`} ref={animateRef}>
        {isLoading ? (
          Array.from({ length: 8 }).map((_, idx) => (
            <SkeletonCard key={`skeleton-cs-${idx}`} />
          ))
        ) : stageCount === 0 && customStages.length === 0 ? (
          <div className="no-skins-message" style={{ gridColumn: '1 / -1' }}>
            <p>No custom stages yet. Import a stage package or scan an ISO.</p>
          </div>
        ) : displayList.map((entry, idx) => {
          if (entry.type === 'folder') {
            const folderId = entry.folder.id
            return (
              <FolderCard
                key={folderId}
                folder={entry.folder}
                isExpanded={entry.isExpanded}
                displayIdx={idx}
                arrayIdx={entry.arrayIndex}
                isDragging={draggedItem && draggedItem.id === folderId}
                isDropTarget={dragTargetFolder === folderId}
                isJustDropped={justDroppedId === folderId}
                isEditing={editingFolderId === folderId}
                editingFolderName={editingFolderName}
                folderSkinCount={countSkinsInFolder(folderId, customStages)}
                reordering={reordering}
                onToggle={toggleFolder}
                onDragStart={(e) => handleDragStart(e, itemsForDisplay.findIndex(s => s.id === folderId), itemsForDisplay)}
                onDragOver={handleDragOver}
                onDragEnter={(e) => handleDragEnter(e, itemsForDisplay.findIndex(s => s.id === folderId), itemsForDisplay)}
                onDragLeave={() => {}}
                onDrop={handleDrop}
                onDragEnd={handleDragEnd}
                onEditingFolderNameChange={setEditingFolderName}
                onSaveFolderName={saveFolderName}
                onCancelEdit={() => setEditingFolderId(null)}
                onStartEditing={(folder) => {
                  setEditingFolderId(folder.id)
                  setEditingFolderName(folder.name)
                }}
                onDelete={deleteFolder}
                justDraggedRef={justDraggedRef}
              />
            )
          }

          const stage = entry.skin
          const stageId = stage.id
          const isDragging = draggedItem && draggedItem.id === stageId
          const isJustDropped = justDroppedId === stageId
          const classes = [
            'stage-card',
            isDragging && 'dragging',
            isJustDropped && 'just-dropped'
          ].filter(Boolean).join(' ')

          return (
            <div
              key={stageId}
              className={classes}
              draggable={!reordering}
              onMouseEnter={playHoverSound}
              onDragStart={(e) => handleDragStart(e, itemsForDisplay.findIndex(s => s.id === stageId), itemsForDisplay)}
              onDragOver={handleDragOver}
              onDragEnter={(e) => handleDragEnter(e, itemsForDisplay.findIndex(s => s.id === stageId), itemsForDisplay)}
              onDrop={handleDrop}
              onDragEnd={handleDragEnd}
              onClick={() => {
                if (justDraggedRef.current) return
                playSound('boop')
                onSelectStage(stage)
              }}
            >
              <div className="stage-icon-container">
                {stage.has_icon ? (
                  <img
                    src={backendMediaUrl(stage.icon_url)}
                    alt={stage.name}
                    className="stage-icon"
                    style={{ imageRendering: 'pixelated' }}
                    onError={(e) => {
                      e.target.style.display = 'none'
                      e.target.nextSibling.style.display = 'flex'
                    }}
                  />
                ) : null}
                <div className="stage-placeholder" style={{ display: stage.has_icon ? 'none' : 'flex' }}>
                  {stage.name[0]}
                </div>
              </div>
              <div className="stage-info">
                <h3 className="stage-name">{stage.name}</h3>
              </div>
            </div>
          )
        })}
      </div>

    </div>
  )
}
