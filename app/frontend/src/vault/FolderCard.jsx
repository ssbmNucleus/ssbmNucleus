/**
 * FolderCard - Folder card component with inline editing
 *
 * Features:
 * - Expandable/collapsible folder
 * - Inline name editing
 * - Drag and drop support
 * - Rename and delete actions
 * - Skin count display
 */
import { useRef } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'

export default function FolderCard({
  folder,
  isExpanded,
  displayIdx,
  arrayIdx,
  isDragging,
  isDropTarget,
  isJustDropped,
  isEditing,
  editingFolderName,
  folderSkinCount,
  reordering,
  canDrag = true,
  onToggle,
  onDragStart,
  onDragOver,
  onDragEnter,
  onDragLeave,
  onDrop,
  onDragEnd,
  onEditingFolderNameChange,
  onSaveFolderName,
  onCancelEdit,
  onStartEditing,
  onDelete,
  justDraggedRef,
  // Label noun for the count, e.g. "skin" (characters) or "variant" (stages)
  itemNoun = 'skin'
}) {
  // True when the click's mousedown happened while the rename input was open —
  // that mousedown blurs the input (saving the name), and the resulting click
  // on the card must not ALSO toggle the folder.
  const wasEditingOnMouseDownRef = useRef(false)

  const classNames = [
    'folder-card',
    isExpanded && 'expanded',
    isDragging && 'dragging',
    isDropTarget && 'drop-target',
    isJustDropped && 'just-dropped'
  ].filter(Boolean).join(' ')

  return (
    <div
      key={folder.id}
      className={classNames}
      draggable={!reordering && !isEditing && canDrag}
      onMouseEnter={playHoverSound}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      onMouseDown={() => { wasEditingOnMouseDownRef.current = isEditing }}
      onClick={() => {
        if (wasEditingOnMouseDownRef.current) { wasEditingOnMouseDownRef.current = false; return }
        if (!isEditing && !justDraggedRef.current) { playSound('boop'); onToggle(folder.id, isExpanded); }
      }}
    >
      <svg className="folder-icon" viewBox="0 0 24 24" fill="currentColor">
        {isExpanded ? (
          <path d="M20 6h-8l-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 12H4V6h5.17l2 2H20v10z"/>
        ) : (
          <path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>
        )}
      </svg>
      <div className="folder-header">
        {isEditing ? (
          <input
            className="folder-name-input"
            value={editingFolderName}
            onChange={(e) => onEditingFolderNameChange(e.target.value)}
            onBlur={() => onSaveFolderName(folder.id)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSaveFolderName(folder.id)
              if (e.key === 'Escape') onCancelEdit()
            }}
            autoFocus
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span className="folder-name">{folder.name}</span>
        )}
        <span className="folder-count">{folderSkinCount} {itemNoun}{folderSkinCount !== 1 ? 's' : ''}</span>
        <span className="folder-chevron">▼</span>
      </div>
      <div className="folder-actions">
        <button
          onClick={(e) => {
            e.stopPropagation()
            playSound('boop')
            onStartEditing(folder)
          }}
          title="Rename folder"
        >
          ✎
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation()
            playSound('boop')
            onDelete(folder.id)
          }}
          title="Delete folder"
        >
          ×
        </button>
      </div>
    </div>
  )
}
