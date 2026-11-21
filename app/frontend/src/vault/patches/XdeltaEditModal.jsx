/**
 * XdeltaEditModal - Modal for editing XDelta patch details
 */
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config.js'
import './PatchEditModal.css'

export default function XdeltaEditModal({
  show,
  patch,
  onPatchChange,
  onSave,
  onCancel,
  onDelete,
  onUpdateImage,
  onDownload,
  BACKEND_URL
}) {
  if (!show || !patch) return null

  const handleOverlayClick = () => {
    playSound('back')
    onCancel()
  }

  const handleContentClick = (e) => {
    e.stopPropagation()
  }

  return (
    <div className="edit-modal-overlay" onClick={handleOverlayClick}>
      <div className="edit-modal-content" onClick={handleContentClick}>
        <h2>Edit Patch</h2>

        <div className="edit-preview">
          {patch.imageUrl ? (
            <img
              src={backendMediaUrl(`${patch.imageUrl}?t=${Date.now()}`)}
              alt={patch.name}
            />
          ) : (
            <div className="edit-placeholder">
              <span>{patch.name[0]}</span>
            </div>
          )}
          <input
            type="file"
            accept="image/*"
            onChange={onUpdateImage}
            style={{ display: 'none' }}
            id="xdelta-image-input"
          />
          <button
            className="btn-edit-screenshot"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); document.getElementById('xdelta-image-input').click(); }}
            title="Replace image"
          >
            ✎
          </button>
        </div>

        <div className="edit-field">
          <label>Name:</label>
          <input
            type="text"
            value={patch.name}
            onChange={(e) => onPatchChange({ ...patch, name: e.target.value })}
          />
        </div>

        <div className="edit-field">
          <label>Description:</label>
          <textarea
            value={patch.description || ''}
            onChange={(e) => onPatchChange({ ...patch, description: e.target.value })}
            rows={3}
          />
        </div>

        <div className="edit-buttons">
          <button className="btn-save" onMouseEnter={playHoverSound} onClick={() => { playSound('boop'); onSave(); }}>
            Save
          </button>
          <button
            className="btn-export"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('start'); onDownload(patch.id); }}
          >
            Export
          </button>
          <button
            className="btn-cancel"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('back'); onCancel(); }}
          >
            Cancel
          </button>
          <button
            className="btn-delete-modal"
            onMouseEnter={playHoverSound}
            onClick={() => {
              playSound('boop')
              onDelete(patch.id)
              onCancel()
            }}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}
