import VisualEffectEditor from './VisualEffectEditor'
import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { CloseIcon, SaveIcon } from '../../shared/ui/Icons'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { ColorRow, PresetRow } from './EditorControls'
import { readEditorColors } from './editorRecipe.js'
import { api } from '../../shared/transport/api'

/**
 * LaserRingEditorModal - Color picker UI for creating/editing blaster-flash
 * ("laser_ring") mods: the streak burst around Fox/Falco on every blaster
 * shot (audit 2026-07: EfFxData Models_5 TEV colors; NOT the beam or the red
 * muzzle ring). color1 = KONST (bright streaks), color2 = TEV0 (dim tint).
 * The six "hue" bytes are FObj animation trackTypes; they MUST be zeroed for
 * custom colors to show (the vanilla animation overwrites the colors every
 * frame otherwise) -- see docs/EXTRAS_AUDIT.md.
 */

// Default colors (vanilla laser ring)
const DEFAULT_COLOR1 = 'FF004C'
const DEFAULT_COLOR2 = 'B20000'

// Convert hex to display format
function toDisplayHex(rgb) {
  if (!rgb || rgb.length < 6) return '#FF004C'
  return `#${rgb.slice(0, 6)}`
}

// Convert display hex to RGB storage format
function toStorageRgb(hex) {
  return hex.replace('#', '').toUpperCase()
}

// Darken a color by a percentage
function darkenColor(hex, percent) {
  const num = parseInt(hex.replace('#', ''), 16)
  const r = Math.max(0, Math.floor((num >> 16) * (1 - percent)))
  const g = Math.max(0, Math.floor(((num >> 8) & 0x00FF) * (1 - percent)))
  const b = Math.max(0, Math.floor((num & 0x0000FF) * (1 - percent)))
  return ((r << 16) | (g << 8) | b).toString(16).padStart(6, '0').toUpperCase()
}

// RGB color control -> shared ColorRow (obvious clickable swatch, no
// per-picker preset strip)
function ColorPicker({ label, description, value, onChange, picto }) {
  return (
    <ColorRow
      size="lg"
      label={label}
      description={description}
      hex={toDisplayHex(value)}
      onChange={(hex) => onChange(toStorageRgb(hex))}
      picto={picto}
    />
  )
}

export default function LaserRingEditorModal({
  show,
  character,
  extraType,
  editingMod,
  onClose,
  onSave,
  onDelete,
}) {
  const [name, setName] = useState('')
  const [color1, setColor1] = useState(DEFAULT_COLOR1)
  const [color2, setColor2] = useState(DEFAULT_COLOR2)
  const [linkColors, setLinkColors] = useState(true) // Auto-derive color2 from color1
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState(null)

  // Initialize from editing mod or vanilla
  useEffect(() => {
    const loaded = readEditorColors(editingMod, {
      color1: extraType?.vanilla?.color1 || DEFAULT_COLOR1,
      color2: extraType?.vanilla?.color2 || DEFAULT_COLOR2,
    })
    setColor1(loaded.color1)
    setColor2(loaded.color2)
    if (editingMod) {
      setName(editingMod.name || '')
      setLinkColors(false) // Don't auto-link when editing
    } else {
      // Reset for new mod - use vanilla colors
      setName('')
      setLinkColors(true)
    }
    setError(null)
  }, [editingMod, show, extraType])

  // Link only user edits. An effect that derives color2 after initialization
  // can overwrite the saved/default second channel with the previous mod.
  const changePrimary = (color) => {
    setColor1(color)
    if (linkColors) setColor2(darkenColor(color, 0.3))
  }

  if (!show) return null

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Please enter a name for this mod')
      return
    }

    setSaving(true)
    setError(null)

    try {
      const modData = {
        character,
        extraType: extraType.id,
        name: name.trim(),
        modifications: {
          color1: { color: color1 },
          color2: { color: color2 },
          // Disable the 6 FObj color-animation tracks (trackType = 00 =
          // HSD_A_T_NONE). REQUIRED: with these left vanilla the animation
          // overwrites KONST/TEV0 every frame and custom colors never show
          // (verified in-game 2026-07). The backend also injects these if
          // missing, so legacy mods behave identically.
          hue1: { color: '00' },
          hue2: { color: '00' },
          hue3: { color: '00' },
          hue4: { color: '00' },
          hue5: { color: '00' },
          hue6: { color: '00' }
        }
      }

      if (editingMod) {
        modData.modId = editingMod.id
      }

      const data = await api.post('/storage/extras/create', modData)
      onSave?.(data.mod)
      onClose()
    } catch (err) {
      console.error('[LaserRingEditorModal] Save error:', err)
      setError(err.message || 'Failed to save mod')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editingMod) return
    if (!await appConfirm(`Delete "${editingMod.name}"?`, {
      title: 'Delete Blaster Flash Mod',
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

  const modal = (
    <div className="laser-editor-overlay" onClick={(e) => e.target === e.currentTarget && handleClose()}>
      <div className="laser-editor-modal">
        <div className="laser-editor-header">
          <div className="laser-editor-title">
            <span className="laser-editor-title-text">
              {editingMod ? 'Edit Blaster Flash' : 'Create Blaster Flash'}
            </span>
            <span className="laser-editor-title-char">{character}</span>
          </div>
          <button className="laser-editor-close" onClick={handleClose}>
            <CloseIcon />
          </button>
        </div>

        <div className="laser-editor-body">
          <VisualEffectEditor key={`${character}/${editingMod?.id || 'new'}`}
            effectId="laser_ring" character={character}
            previewColors={{ color1, color2 }}
            parts={[{ id: 'streaks', label: 'Streak Burst' }]}
            renderControls={() => <>
              <ColorPicker label="Streak Color" value={color1} onChange={changePrimary} />
              <label className="visual-effect-link">
                <input type="checkbox" checked={linkColors} onChange={event => {
                  setLinkColors(event.target.checked)
                  if (event.target.checked) setColor2(darkenColor(color1, 0.3))
                }} /> Match the dim tint
              </label>
              {!linkColors && <ColorPicker label="Dim Tint" value={color2} onChange={setColor2} />}
              <PresetRow onPick={hex => changePrimary(toStorageRgb(hex))} activeHex={toDisplayHex(color1)} />
            </>}
          />

          {/* Recipe name */}
          <div className="extra-editor-top">
          <div className="laser-editor-name-group">
            <label className="laser-editor-name-label">Mod Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Green Flash, Blue Streaks..."
              className="laser-editor-name-input"
            />
          </div>

          </div>

          {error && (
            <div className="laser-editor-error">{error}</div>
          )}
        </div>

        <div className="laser-editor-footer">
          {editingMod && (
            <button
              className="laser-editor-delete"
              onClick={handleDelete}
              disabled={deleting || saving}
            >
              {deleting ? 'Deleting...' : 'Delete'}
            </button>
          )}
          <div className="laser-editor-footer-right">
            <button className="laser-editor-cancel" onClick={handleClose}>
              Cancel
            </button>
            <button
              className="laser-editor-save"
              onClick={handleSave}
              disabled={saving || deleting}
            >
              <SaveIcon />
              <span>{saving ? 'Saving...' : 'Save Mod'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
