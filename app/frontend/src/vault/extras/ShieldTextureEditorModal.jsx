import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { API_URL } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'

/**
 * ShieldTextureEditorModal - Modal for texture_region extras (common_shield).
 *
 * These extras replace ONE raw texture inside the shared effects file (the
 * shield bubble: 128x128 grayscale+alpha at EfCoData 0x104320), so there are
 * no color pickers -- a mod is created by importing either a full modded
 * EfCoData.dat (community shield mods) or an image, which the backend
 * encodes to the grayscale texture. Existing mods show their decoded
 * texture and can be renamed-by-recreate or deleted.
 */
export default function ShieldTextureEditorModal({
  show,
  character,
  extraType,
  editingMod,
  onClose,
  onSave,
  onDelete,
}) {
  const [name, setName] = useState(editingMod?.name || '')
  const [file, setFile] = useState(null)
  const [localPreview, setLocalPreview] = useState(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)

  // The modal component stays mounted across open/close (show toggles), so
  // useState initials go stale -- re-sync per open/target mod.
  useEffect(() => {
    setName(editingMod?.name || '')
    setFile(null)
    setLocalPreview(null)
    setError(null)
  }, [editingMod, show])

  if (!show) return null

  const staticBase = API_URL.replace('/api/mex', '')
  const owner = extraType.owner || character
  const modShot = editingMod?.screenshot
    ? `${staticBase}/storage/${owner}/${editingMod.screenshot}`
    : (editingMod?.id
        ? `${API_URL}/storage/extras/texture-region/${character}/${extraType.id}?mod=${editingMod.id}`
        : null)
  const vanillaShot = `${API_URL}/storage/extras/texture-region/${character}/${extraType.id}?source=vanilla`

  const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']

  const acceptFile = (selected) => {
    if (!selected) return
    const ext = selected.name.split('.').pop().toLowerCase()
    if (ext === 'dat' || IMAGE_EXTS.includes(ext)) {
      setFile(selected)
      setError(null)
      if (!name) setName(selected.name.replace(/\.[^.]+$/, ''))
      if (IMAGE_EXTS.includes(ext)) {
        const url = URL.createObjectURL(selected)
        setLocalPreview(url)
      } else {
        setLocalPreview(null)
      }
    } else {
      setError('Please select a .dat file or an image')
      setFile(null)
      setLocalPreview(null)
    }
  }

  const handleSave = async () => {
    if (!file) {
      setError('Please select a file')
      return
    }
    if (!name.trim()) {
      setError('Please enter a name')
      return
    }

    setSaving(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('character', character)
      formData.append('extraType', extraType.id)
      formData.append('name', name.trim())

      await api.post('/storage/extras/import', formData)
      onSave?.()
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to import texture')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editingMod) return
    if (!await appConfirm(`Delete "${editingMod.name}"?`, {
      title: 'Delete Shield Texture',
      confirmText: 'Delete',
    })) return

    setDeleting(true)
    try {
      await api.post('/storage/extras/delete', {
        character,
        extraType: extraType.id,
        modId: editingMod.id
      })
      onDelete?.(editingMod.id)
      onClose()
    } catch (err) {
      setError(`Delete failed: ${err.message}`)
    } finally {
      setDeleting(false)
    }
  }

  const handleClose = () => {
    playSound('back')
    onClose()
  }

  const previewSrc = localPreview || (editingMod ? modShot : vanillaShot)

  const modal = (
    <div
      className="shield-editor-overlay"
      onClick={(e) => e.target === e.currentTarget && handleClose()}
      style={{
        position: 'absolute',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.8)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: 'var(--page-block-padding) var(--modal-inline-padding)',
        overflow: 'auto',
        overscrollBehavior: 'contain'
      }}
    >
      <div className="shield-editor-modal" onClick={e => e.stopPropagation()}>
        <div className="shield-editor-header">
          <h3>{editingMod ? 'Shield Texture' : 'Import Shield Texture'}</h3>
          <button className="shield-editor-close" onClick={handleClose}>&times;</button>
        </div>

        <div className="modal-body">
          {/* Texture preview */}
          <div className="shield-preview-row">
            <div className="shield-preview-box">
              {previewSrc && (
                <img
                  src={previewSrc}
                  alt="shield texture"
                  onError={(e) => { e.target.style.display = 'none' }}
                />
              )}
            </div>
            <div className="shield-preview-note">
              The shield bubble texture is grayscale + transparency. The
              red/blue/yellow/green tint comes from the player port and is
              applied by the game -- it can't be changed here. Yoshi's egg
              shield is unaffected.
            </div>
          </div>

          {/* Name input */}
          <div className="form-group">
            <label>Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Enter texture name"
              className="form-input"
            />
          </div>

          {/* File drop zone (also shown when editing: re-import = new mod) */}
          <div className="form-group">
            <label>{editingMod ? 'Replace With (creates a new mod)' : 'Texture Source'}</label>
            <div
              className={`file-drop-zone ${dragOver ? 'drag-over' : ''} ${file ? 'has-file' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); acceptFile(e.dataTransfer.files?.[0]) }}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={(e) => { e.preventDefault(); setDragOver(false) }}
            >
              {file ? (
                <div className="file-info">
                  <div className="file-name">{file.name}</div>
                  <div className="file-size">{(file.size / 1024).toFixed(1)} KB</div>
                </div>
              ) : (
                <div className="drop-zone-content">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="17 8 12 3 7 8"/>
                    <line x1="12" y1="3" x2="12" y2="15"/>
                  </svg>
                  <p>Drop a modded EfCoData.dat or an image here</p>
                  <p className="drop-zone-hint">or click to browse</p>
                </div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept=".dat,.png,.jpg,.jpeg,.gif,.bmp,.webp"
                onChange={(e) => acceptFile(e.target.files?.[0])}
                style={{ display: 'none' }}
              />
            </div>
          </div>

          <div className="file-type-info">
            <div className="file-type">
              <strong>.dat</strong> - a modded EfCoData.dat (community shield mods); the shield texture is extracted from it
            </div>
            <div className="file-type">
              <strong>image</strong> - any image; resized to 128x128 and converted to grayscale + transparency
            </div>
          </div>

          {error && (
            <div className="error-message">{error}</div>
          )}
        </div>

        <div className="modal-footer">
          {editingMod && (
            <button className="btn-delete" onClick={handleDelete} disabled={deleting || saving}>
              {deleting ? 'Deleting...' : 'Delete'}
            </button>
          )}
          <div className="modal-footer-right">
            <button className="btn-secondary" onClick={handleClose} disabled={saving || deleting}>
              {editingMod && !file ? 'Close' : 'Cancel'}
            </button>
            {(!editingMod || file) && (
              <button className="btn-primary" onClick={handleSave} disabled={saving || deleting || !file}>
                {saving ? 'Importing...' : 'Import Texture'}
              </button>
            )}
          </div>
        </div>

        <style>{`
          .shield-editor-modal {
            max-width: 500px;
            width: min(100%, 500px);
            max-height: min(100%, var(--modal-max-height));
            background: #1a1a2e;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
            display: flex;
            flex-direction: column;
            margin: auto;
          }

          .shield-editor-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid #333;
          }

          .shield-editor-header h3 {
            margin: 0;
            color: #fff;
            font-size: 18px;
          }

          .shield-editor-close {
            background: none;
            border: none;
            color: #888;
            font-size: 24px;
            cursor: pointer;
            padding: 0;
            line-height: 1;
          }

          .shield-editor-close:hover {
            color: #fff;
          }

          .shield-editor-modal .modal-body {
            padding: 20px;
            overflow-y: auto;
          }

          .shield-preview-row {
            display: flex;
            gap: 14px;
            align-items: center;
            margin-bottom: 16px;
          }

          .shield-preview-box {
            flex: 0 0 96px;
            width: 96px;
            height: 96px;
            border-radius: 8px;
            background:
              repeating-conic-gradient(#23233a 0% 25%, #1a1a2e 0% 50%) 0 0 / 16px 16px;
            border: 1px solid #333;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
          }

          .shield-preview-box img {
            width: 100%;
            height: 100%;
            image-rendering: pixelated;
          }

          .shield-preview-note {
            font-size: 12px;
            color: #888;
            line-height: 1.5;
          }

          .shield-editor-modal .form-group {
            margin-bottom: 16px;
          }

          .shield-editor-modal .form-group label {
            display: block;
            margin-bottom: 6px;
            color: #ccc;
            font-size: 13px;
          }

          .shield-editor-modal .form-input {
            width: 100%;
            padding: 10px 12px;
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 6px;
            color: #fff;
            font-size: 14px;
          }

          .shield-editor-modal .form-input:focus {
            outline: none;
            border-color: #4a9eff;
          }

          .shield-editor-modal .file-drop-zone {
            border: 2px dashed #444;
            border-radius: 8px;
            padding: 24px 16px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s ease;
            background: #1a1a2e;
          }

          .shield-editor-modal .file-drop-zone:hover {
            border-color: #666;
            background: #1e1e32;
          }

          .shield-editor-modal .file-drop-zone.drag-over {
            border-color: #4a9eff;
            background: #1e2a3e;
          }

          .shield-editor-modal .file-drop-zone.has-file {
            border-style: solid;
            border-color: #4a9eff;
          }

          .shield-editor-modal .drop-zone-content svg {
            color: #666;
            margin-bottom: 10px;
          }

          .shield-editor-modal .drop-zone-content p {
            margin: 0;
            color: #888;
            font-size: 14px;
          }

          .shield-editor-modal .drop-zone-content .drop-zone-hint {
            font-size: 12px;
            color: #666;
            margin-top: 4px;
          }

          .shield-editor-modal .file-info {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 6px;
          }

          .shield-editor-modal .file-name {
            font-size: 14px;
            color: #fff;
            word-break: break-all;
          }

          .shield-editor-modal .file-size {
            font-size: 12px;
            color: #888;
          }

          .shield-editor-modal .file-type-info {
            background: #12121a;
            border-radius: 6px;
            padding: 12px;
            font-size: 12px;
            color: #888;
          }

          .shield-editor-modal .file-type-info .file-type {
            margin-bottom: 6px;
          }

          .shield-editor-modal .file-type-info .file-type:last-child {
            margin-bottom: 0;
          }

          .shield-editor-modal .file-type-info strong {
            color: #aaa;
          }

          .shield-editor-modal .error-message {
            background: #3d1f1f;
            border: 1px solid #5c2b2b;
            color: #ff8888;
            padding: 10px 12px;
            border-radius: 6px;
            font-size: 13px;
            margin-top: 12px;
          }

          .shield-editor-modal .modal-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-top: 1px solid #333;
          }

          .shield-editor-modal .modal-footer-right {
            display: flex;
            gap: 10px;
            margin-left: auto;
          }

          .shield-editor-modal .btn-delete {
            padding: 10px 20px;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s ease;
            background: #5c2b2b;
            border: 1px solid #7a3a3a;
            color: #ff8888;
          }

          .shield-editor-modal .btn-delete:hover:not(:disabled) {
            background: #6e3535;
          }

          .shield-editor-modal .btn-delete:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }

          .shield-editor-modal .btn-secondary,
          .shield-editor-modal .btn-primary {
            padding: 10px 20px;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s ease;
          }

          .shield-editor-modal .btn-secondary {
            background: #2a2a3e;
            border: 1px solid #444;
            color: #ccc;
          }

          .shield-editor-modal .btn-secondary:hover:not(:disabled) {
            background: #333348;
          }

          .shield-editor-modal .btn-primary {
            background: #4a9eff;
            border: none;
            color: #fff;
          }

          .shield-editor-modal .btn-primary:hover:not(:disabled) {
            background: #5aafff;
          }

          .shield-editor-modal .btn-primary:disabled,
          .shield-editor-modal .btn-secondary:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }
        `}</style>
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
