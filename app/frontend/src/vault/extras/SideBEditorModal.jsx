import VisualEffectEditor from './VisualEffectEditor'
import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { CloseIcon, SaveIcon } from '../../shared/ui/Icons'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { ColorRow, PresetRow } from './EditorControls'
import { readEditorColors, rgbWithAlpha } from './editorRecipe.js'
import { api } from '../../shared/transport/api'

/**
 * SideBEditorModal - Color picker UI for creating/editing side-B mods
 * Allows setting colors for each afterimage layer (primary, secondary, tertiary)
 * Uses RGBA format (8 hex chars) instead of RGBY
 */

// Convert RGBA hex string to display hex (#RRGGBB)
function rgbaToHex(rgba) {
  if (!rgba || rgba.length < 6) return '#0099FF'
  return `#${rgba.substring(0, 6)}`
}

// RGBA color control -- format conversion stays here (save shape
// byte-identical); rendering is the shared ColorRow.
function RgbaColorPicker({ label, description, value, onChange }) {
  const safeValue = value || '0099FFFF'
  return (
    <ColorRow
      size="lg"
      label={label}
      description={description}
      hex={rgbaToHex(safeValue)}
      onChange={(hex) => onChange(rgbWithAlpha(hex, safeValue))}
      readout={`RGBA ${safeValue}`}
    />
  )
}

export default function SideBEditorModal({
  show,
  character,
  extraType,
  editingMod,
  onClose,
  onSave,
  onDelete,
}) {
  const [name, setName] = useState('')
  const [colors, setColors] = useState({
    primary: '0099FFFF',
    secondary: 'CCE6FFFF',
    tertiary: 'FFFFFFFF'
  })
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState(null)
  const modelRecipe = editingMod?.modifications?.sideb_model

  // Initialize from editing mod if provided
  useEffect(() => {
    if (editingMod) {
      setName(editingMod.name || '')
      setColors(readEditorColors(editingMod, {
        primary: '0099FFFF', secondary: 'CCE6FFFF', tertiary: 'FFFFFFFF'
      }))
    } else {
      // Reset for new mod
      setName('')
      setColors({ primary: '0099FFFF', secondary: 'CCE6FFFF', tertiary: 'FFFFFFFF' })
    }
    setError(null)
  }, [editingMod, show])

  if (!show) return null

  const handleColorChange = (layer, rgba) => {
    setColors(prev => ({ ...prev, [layer]: rgba }))
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
        modifications: modelRecipe ? editingMod.modifications : {
          primary: { color: colors.primary },
          secondary: { color: colors.secondary },
          tertiary: { color: colors.tertiary }
        }
      }

      // If editing, include the mod ID
      if (editingMod) {
        modData.modId = editingMod.id
      }

      const data = await api.post('/storage/extras/create', modData)
      onSave?.(data.mod)
      onClose()
    } catch (err) {
      console.error('[SideBEditorModal] Save error:', err)
      setError(err.message || 'Failed to save mod')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editingMod) return
    if (!await appConfirm(`Delete "${editingMod.name}"?`, {
      title: 'Delete Side-B Mod',
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

  const handleApplyToAll = (hex) => {
    setColors(previous => Object.fromEntries(Object.entries(previous).map(
      ([layer, rgba]) => [layer, rgbWithAlpha(hex, rgba)])))
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
              {editingMod ? 'Edit Side-B Mod' : 'Create Side-B Mod'}
            </span>
            <span className="laser-editor-title-char">{character}</span>
          </div>
          <button className="laser-editor-close" onClick={handleClose}>
            <CloseIcon />
          </button>
        </div>

        <div className="laser-editor-body">
          {modelRecipe ? (
            <p>This mod contains an imported afterimage model. You can rename or delete it here.
              Create a separate Side-B color mod to use the original afterimage with different colors.</p>
          ) : <VisualEffectEditor key={`${character}/${editingMod?.id || 'new'}`}
            effectId="sideb" character={character}
            previewColors={colors}
            parts={[{ id: 'afterimage', label: 'Afterimage',
              description: 'These colors shade the same trailing silhouette.' }]}
            wholeEffect={<PresetRow onPick={handleApplyToAll} />}
            renderControls={() => extraType.properties.map(prop => <RgbaColorPicker key={prop.id}
              label={prop.name} description={prop.description} value={colors[prop.id]}
              onChange={value => handleColorChange(prop.id, value)} />)}
          />}

          {/* Recipe name */}
          <div className="extra-editor-top">
          <div className="laser-editor-name-group">
            <label className="laser-editor-name-label">Mod Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Red Phantasm, Blue Illusion..."
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
