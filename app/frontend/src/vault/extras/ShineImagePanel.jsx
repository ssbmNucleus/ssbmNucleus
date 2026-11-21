import { useEffect, useRef, useState } from 'react'
import { API_URL } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']

/**
 * ShineImagePanel - the "Image" half of the Fox/Falco shine editor.
 *
 * An image shine is not a color mod: it puts a picture where the vanilla
 * two-color hexagon is (backend vault/routes/extras/effect_model.py). So this
 * panel has no color pickers -- a mod is made from a PNG (or any image), or
 * from a downloaded/modded EfFxData.dat whose picture is decoded out of it.
 *
 * Editing an existing image mod shows its decoded image; dropping a new file
 * creates a new mod, matching the shield texture editor's behavior (there is
 * no in-place image edit, so promising one would be a lie).
 */
export default function ShineImagePanel({
  character,
  extraType,
  editingMod,
  onSaved,
  onError,
}) {
  const [name, setName] = useState('')
  const [file, setFile] = useState(null)
  const [localPreview, setLocalPreview] = useState(null)
  const [saving, setSaving] = useState(false)
  const fileInputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)

  useEffect(() => {
    setName(editingMod?.name || '')
    setFile(null)
    setLocalPreview(null)
  }, [editingMod])

  // Blob URLs from a dropped file leak until revoked.
  useEffect(() => () => { if (localPreview) URL.revokeObjectURL(localPreview) },
    [localPreview])

  const staticBase = API_URL.replace('/api/mex', '')
  const owner = extraType.owner || character
  const modShot = editingMod?.screenshot
    ? `${staticBase}/storage/${owner}/${editingMod.screenshot}`
    : (editingMod?.id
        ? `${API_URL}/storage/extras/effect-image/${character}/${extraType.id}?mod=${editingMod.id}`
        : null)
  const previewSrc = localPreview || modShot
  const size = extraType.imageModel
    ? `${extraType.imageModel.width}x${extraType.imageModel.height}`
    : '256x256'

  const acceptFile = (selected) => {
    if (!selected) return
    const ext = (selected.name.split('.').pop() || '').toLowerCase()
    if (ext !== 'dat' && !IMAGE_EXTS.includes(ext)) {
      onError?.('Please select a .dat file or an image')
      return
    }
    onError?.(null)
    setFile(selected)
    if (!name) setName(selected.name.replace(/\.[^.]+$/, ''))
    if (localPreview) URL.revokeObjectURL(localPreview)
    setLocalPreview(IMAGE_EXTS.includes(ext) ? URL.createObjectURL(selected) : null)
  }

  const handleImport = async () => {
    if (!file) { onError?.('Please choose an image or a modded EfFxData.dat'); return }
    if (!name.trim()) { onError?.('Please enter a name for this mod'); return }
    setSaving(true)
    onError?.(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('character', character)
      formData.append('extraType', extraType.id)
      formData.append('name', name.trim())
      const data = await api.post('/storage/extras/import', formData)
      onSaved?.(data.mod)
    } catch (err) {
      onError?.(err.message || 'Failed to import the image')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="shine-image-panel">
      <div className="shine-image-top">
        <div className="shine-image-box">
          {previewSrc ? (
            <img
              src={previewSrc}
              alt={editingMod?.name || 'shine image'}
              onError={(e) => { e.target.style.display = 'none' }}
            />
          ) : (
            <span className="shine-image-empty">no image yet</span>
          )}
        </div>
        <div className="shine-image-note">
          An image shine replaces the hexagon with a picture, so it has no
          edge/fill colors. The image is stretched to {size} with transparency
          kept; the sparkles and startup flash stay whatever they are.
        </div>
      </div>

      <div className="laser-editor-name-group">
        <label className="laser-editor-name-label">Mod Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g., NERV Shine, Honeycomb..."
          className="laser-editor-name-input"
        />
      </div>

      <div className="shine-image-drop-group">
        <label className="laser-editor-name-label">
          {editingMod ? 'Replace With (creates a new mod)' : 'Image Source'}
        </label>
        <div
          className={`shine-image-drop ${dragOver ? 'drag-over' : ''} ${file ? 'has-file' : ''}`}
          onClick={() => fileInputRef.current?.click()}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); acceptFile(e.dataTransfer.files?.[0]) }}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={(e) => { e.preventDefault(); setDragOver(false) }}
        >
          {file ? (
            <div className="shine-image-file">
              <div className="shine-image-file-name">{file.name}</div>
              <div className="shine-image-file-size">{(file.size / 1024).toFixed(1)} KB</div>
            </div>
          ) : (
            <div className="shine-image-drop-content">
              <p>Drop a PNG, or a modded EfFxData.dat</p>
              <p className="shine-image-hint">or click to browse</p>
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

      <div className="shine-image-types">
        <div><strong>image</strong> — any image; resized to {size}, transparency kept</div>
        <div><strong>.dat</strong> — a downloaded image shine (EfFxData.dat); its picture is read out of the file</div>
      </div>

      <button
        className="laser-editor-save shine-image-import"
        onClick={handleImport}
        disabled={saving || !file}
      >
        {saving ? 'Importing...' : 'Import Image Shine'}
      </button>

      <style>{`
        .shine-image-panel { display: flex; flex-direction: column; gap: 14px; }
        .shine-image-top { display: flex; gap: 14px; align-items: center; }
        .shine-image-box {
          flex: 0 0 104px; width: 104px; height: 104px; border-radius: 8px;
          background: repeating-conic-gradient(#23233a 0% 25%, #1a1a2e 0% 50%) 0 0 / 16px 16px;
          border: 1px solid #333; display: flex; align-items: center;
          justify-content: center; overflow: hidden;
        }
        .shine-image-box img { width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; }
        .shine-image-empty { font-size: 11px; color: #666; }
        .shine-image-note { font-size: 12px; color: #888; line-height: 1.5; }
        .shine-image-drop {
          border: 2px dashed #444; border-radius: 8px; padding: 20px 16px;
          text-align: center; cursor: pointer; transition: all 0.2s ease;
        }
        .shine-image-drop:hover { border-color: #666; }
        .shine-image-drop.drag-over { border-color: #4a9eff; background: #1e2a3e; }
        .shine-image-drop.has-file { border-style: solid; border-color: #4a9eff; }
        .shine-image-drop-content p { margin: 0; color: #888; font-size: 14px; }
        .shine-image-hint { font-size: 12px; color: #666; margin-top: 4px !important; }
        .shine-image-file-name { font-size: 14px; color: #fff; word-break: break-all; }
        .shine-image-file-size { font-size: 12px; color: #888; }
        .shine-image-types {
          background: #12121a; border-radius: 6px; padding: 12px;
          font-size: 12px; color: #888; display: flex; flex-direction: column; gap: 6px;
        }
        .shine-image-types strong { color: #aaa; }
        .shine-image-import { align-self: flex-start; }
      `}</style>
    </div>
  )
}
