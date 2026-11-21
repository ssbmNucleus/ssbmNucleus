import { useState, useRef } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { api } from '../../shared/transport/api'

/**
 * GunEditorModal - Modal for importing custom gun models
 * Accepts .dae (COLLADA) or .dat (modified PlFc.dat with gun already imported)
 */
export default function GunEditorModal({
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
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)

  if (!show) return null

  const handleFileSelect = (e) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      const ext = selectedFile.name.split('.').pop().toLowerCase()
      if (ext === 'dae' || ext === 'dat') {
        setFile(selectedFile)
        setError(null)
        // Auto-fill name from filename if empty
        if (!name) {
          const baseName = selectedFile.name.replace(/\.(dae|dat)$/i, '')
          setName(baseName)
        }
      } else {
        setError('Please select a .dae or .dat file')
        setFile(null)
      }
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)

    const droppedFile = e.dataTransfer.files?.[0]
    if (droppedFile) {
      const ext = droppedFile.name.split('.').pop().toLowerCase()
      if (ext === 'dae' || ext === 'dat') {
        setFile(droppedFile)
        setError(null)
        if (!name) {
          const baseName = droppedFile.name.replace(/\.(dae|dat)$/i, '')
          setName(baseName)
        }
      } else {
        setError('Please select a .dae or .dat file')
      }
    }
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    setDragOver(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setDragOver(false)
  }

  const handleSave = async () => {
    if (!file) {
      setError('Please select a model file')
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

      await api.post('/storage/models/create', formData)
      onSave?.()
      onClose()
    } catch (err) {
      console.error('[GunEditorModal] Save error:', err)
      setError(err.message || 'Failed to import model')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editingMod) return
    if (!await appConfirm(`Delete "${editingMod.name}"?`, {
      title: 'Delete Model',
      confirmText: 'Delete',
    })) return

    setDeleting(true)
    try {
      await api.post('/storage/models/delete', {
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

  const modal = (
    <div
      className="gun-editor-overlay"
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
      <div className="gun-editor-modal" onClick={e => e.stopPropagation()}>
        <div className="gun-editor-header">
          <h3>{editingMod ? 'Edit Gun Model' : 'Import Gun Model'}</h3>
          <button className="gun-editor-close" onClick={handleClose}>&times;</button>
        </div>

        <div className="modal-body">
          {/* Name input */}
          <div className="form-group">
            <label>Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Enter model name"
              className="form-input"
            />
          </div>

          {/* File drop zone */}
          <div className="form-group">
            <label>Model File</label>
            <div
              className={`file-drop-zone ${dragOver ? 'drag-over' : ''} ${file ? 'has-file' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
            >
              {file ? (
                <div className="file-info">
                  <div className="file-icon">
                    {file.name.endsWith('.dae') ? (
                      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                        <path d="M12 18v-6"/>
                        <path d="M9 15l3 3 3-3"/>
                      </svg>
                    ) : (
                      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                        <rect x="8" y="12" width="8" height="6" rx="1"/>
                      </svg>
                    )}
                  </div>
                  <div className="file-name">{file.name}</div>
                  <div className="file-size">{(file.size / 1024).toFixed(1)} KB</div>
                </div>
              ) : (
                <div className="drop-zone-content">
                  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="17 8 12 3 7 8"/>
                    <line x1="12" y1="3" x2="12" y2="15"/>
                  </svg>
                  <p>Drop .dae or .dat file here</p>
                  <p className="drop-zone-hint">or click to browse</p>
                </div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept=".dae,.dat"
                onChange={handleFileSelect}
                style={{ display: 'none' }}
              />
            </div>
          </div>

          {/* File type info */}
          <div className="file-type-info">
            <div className="file-type">
              <strong>.dae</strong> - COLLADA model file (exported from Blender, etc.)
            </div>
            <div className="file-type">
              <strong>.dat</strong> - Modified PlFc.dat with custom gun already imported
            </div>
          </div>

          {/* Error message */}
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
              Cancel
            </button>
            <button className="btn-primary" onClick={handleSave} disabled={saving || deleting || !file}>
              {saving ? 'Importing...' : 'Import Model'}
            </button>
          </div>
        </div>

        <style>{`
          .gun-editor-modal {
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

          .gun-editor-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid #333;
          }

          .gun-editor-header h3 {
            margin: 0;
            color: #fff;
            font-size: 18px;
          }

          .gun-editor-close {
            background: none;
            border: none;
            color: #888;
            font-size: 24px;
            cursor: pointer;
            padding: 0;
            line-height: 1;
          }

          .gun-editor-close:hover {
            color: #fff;
          }

          .gun-editor-modal .modal-body {
            padding: 20px;
            overflow-y: auto;
          }

          .gun-editor-modal .form-group {
            margin-bottom: 16px;
          }

          .gun-editor-modal .form-group label {
            display: block;
            margin-bottom: 6px;
            color: #ccc;
            font-size: 13px;
          }

          .gun-editor-modal .form-input {
            width: 100%;
            padding: 10px 12px;
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 6px;
            color: #fff;
            font-size: 14px;
          }

          .gun-editor-modal .form-input:focus {
            outline: none;
            border-color: #4a9eff;
          }

          .file-drop-zone {
            border: 2px dashed #444;
            border-radius: 8px;
            padding: 30px 20px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s ease;
            background: #1a1a2e;
          }

          .file-drop-zone:hover {
            border-color: #666;
            background: #1e1e32;
          }

          .file-drop-zone.drag-over {
            border-color: #4a9eff;
            background: #1e2a3e;
          }

          .file-drop-zone.has-file {
            border-style: solid;
            border-color: #4a9eff;
          }

          .drop-zone-content svg {
            color: #666;
            margin-bottom: 12px;
          }

          .drop-zone-content p {
            margin: 0;
            color: #888;
            font-size: 14px;
          }

          .drop-zone-content .drop-zone-hint {
            font-size: 12px;
            color: #666;
            margin-top: 4px;
          }

          .file-info {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
          }

          .file-icon {
            color: #4a9eff;
          }

          .file-name {
            font-size: 14px;
            color: #fff;
            word-break: break-all;
          }

          .file-size {
            font-size: 12px;
            color: #888;
          }

          .file-type-info {
            background: #12121a;
            border-radius: 6px;
            padding: 12px;
            font-size: 12px;
            color: #888;
          }

          .file-type-info .file-type {
            margin-bottom: 6px;
          }

          .file-type-info .file-type:last-child {
            margin-bottom: 0;
          }

          .file-type-info strong {
            color: #aaa;
          }

          .error-message {
            background: #3d1f1f;
            border: 1px solid #5c2b2b;
            color: #ff8888;
            padding: 10px 12px;
            border-radius: 6px;
            font-size: 13px;
            margin-top: 12px;
          }

          .modal-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-top: 1px solid #333;
          }

          .modal-footer-right {
            display: flex;
            gap: 10px;
            margin-left: auto;
          }

          .btn-delete {
            padding: 10px 20px;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s ease;
            background: #5c2b2b;
            border: 1px solid #7a3a3a;
            color: #ff8888;
          }

          .btn-delete:hover:not(:disabled) {
            background: #6e3535;
          }

          .btn-delete:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }

          .btn-secondary, .btn-primary {
            padding: 10px 20px;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s ease;
          }

          .btn-secondary {
            background: #2a2a3e;
            border: 1px solid #444;
            color: #ccc;
          }

          .btn-secondary:hover:not(:disabled) {
            background: #333348;
          }

          .btn-primary {
            background: #4a9eff;
            border: none;
            color: #fff;
          }

          .btn-primary:hover:not(:disabled) {
            background: #5aafff;
          }

          .btn-primary:disabled, .btn-secondary:disabled {
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
