import VisualEffectEditor from './VisualEffectEditor'
import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { CloseIcon, SaveIcon } from '../../shared/ui/Icons'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { ColorRow, PresetRow } from './EditorControls'
import { api } from '../../shared/transport/api'

/**
 * SwordEditorModal - Color picker UI for creating/editing sword trail mods
 * Used for Marth, Roy, Link, Young Link sword swing colors
 *
 * The game renders the trail as a TWO-color ribbon: one color along the inner
 * (hilt-side) edge, one along the outer (tip-side) edge, blended across the
 * band, with alpha fading from the blade to the tail (ft/ftafterimage.c).
 * Layers: inner + outer RGB.
 */

// Default colors (Marth/Link vanilla; Roy's vanilla comes from extraType)
const DEFAULT_COLORS = {
  inner: '00FFFF',
  outer: 'FFFFFF'
}

// Convert hex to display format
function toDisplayHex(rgb) {
  if (!rgb || rgb.length < 6) return '#FF0000'
  return `#${rgb.slice(0, 6)}`
}

// Convert display hex to RGB storage format
function toStorageRgb(hex) {
  return hex.replace('#', '').toUpperCase()
}

// RGB color control -> shared ColorRow (obvious clickable swatch, no
// per-picker preset strip)
function ColorPicker({ label, description, value, onChange, picto }) {
  return (
    <ColorRow
      size="lg"
      label={label}
      picto={picto}
      description={description}
      hex={toDisplayHex(value)}
      onChange={(hex) => onChange(toStorageRgb(hex))}
    />
  )
}

export default function SwordEditorModal({
  show,
  character,
  extraType,
  editingMod,
  onClose,
  onSave,
  onDelete,
}) {
  const [name, setName] = useState('')
  const [colors, setColors] = useState({ ...DEFAULT_COLORS })
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState(null)

  // Initialize from editing mod or vanilla
  useEffect(() => {
    if (editingMod) {
      setName(editingMod.name || '')
      const m = editingMod.modifications || {}
      const vanilla = extraType?.vanilla || DEFAULT_COLORS
      setColors({
        // Legacy saves used three slices of the same two-color ribbon.
        inner: m.inner?.color
          || (m.main?.color && m.secondary?.color
              ? (m.main.color.slice(4, 6) + m.secondary.color.slice(0, 4))
              : vanilla.inner || DEFAULT_COLORS.inner),
        outer: m.outer?.color || m.tertiary?.color || vanilla.outer || DEFAULT_COLORS.outer
      })
    } else {
      // Reset for new mod - use vanilla colors from extraType if available
      setName('')
      const vanilla = extraType?.vanilla || DEFAULT_COLORS
      setColors({
        inner: vanilla.inner || DEFAULT_COLORS.inner,
        outer: vanilla.outer || DEFAULT_COLORS.outer
      })
    }
    setError(null)
  }, [editingMod, show, extraType])

  if (!show) return null

  const handleColorChange = (layer, value) => {
    setColors(prev => ({ ...prev, [layer]: value }))
  }

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
          inner: { color: colors.inner },
          outer: { color: colors.outer }
        }
      }

      if (editingMod) {
        modData.modId = editingMod.id
      }

      const data = await api.post('/storage/extras/create', modData)
      onSave?.(data.mod)
      onClose()
    } catch (err) {
      console.error('[SwordEditorModal] Save error:', err)
      setError(err.message || 'Failed to save mod')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editingMod) return
    if (!await appConfirm(`Delete "${editingMod.name}"?`, {
      title: 'Delete Sword Mod',
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
              {editingMod ? 'Edit Sword Trail' : 'Create Sword Trail'}
            </span>
            <span className="laser-editor-title-char">{character}</span>
          </div>
          <button className="laser-editor-close" onClick={handleClose}>
            <CloseIcon />
          </button>
        </div>

        <div className="laser-editor-body">
          <VisualEffectEditor key={`${character}/${editingMod?.id || 'new'}`}
            effectId="sword" character={character}
            previewColors={colors}
            parts={[
              { id: 'inner', label: 'Inner Edge', description: 'The hilt-side edge of the trail.' },
              { id: 'outer', label: 'Outer Edge', description: 'The tip-side edge of the trail.' },
            ]}
            wholeEffect={<PresetRow
              onPick={hex => setColors({ inner: toStorageRgb(hex), outer: 'FFFFFF' })}
              activeHex={colors.outer === 'FFFFFF' ? toDisplayHex(colors.inner) : null} />}
            renderControls={part => <ColorPicker label="Color" value={colors[part.id]}
              onChange={value => handleColorChange(part.id, value)} />}
          />

          {/* Recipe name */}
          <div className="extra-editor-top">
          <div className="laser-editor-name-group">
            <label className="laser-editor-name-label">Mod Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Blue Sword, Ice Trail..."
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
