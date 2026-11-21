import VisualEffectEditor from './VisualEffectEditor'
import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { hexToRgby, rgbyToHex, formatRgby } from '../lib/rgbyColor'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { CloseIcon, SaveIcon } from '../../shared/ui/Icons'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { useBespokeSimpleMode } from './useBespokeSimpleMode'
import { readEditorColors } from './editorRecipe.js'
import { ColorRow, PresetRow } from './EditorControls'
import { api } from '../../shared/transport/api'

/**
 * LaserEditorModal - Color picker UI for creating/editing laser mods
 * Allows setting colors for each laser layer (wide, thin, outline)
 *
 * Editor-polish pattern (fan-out 2026-07-02): a Simple/Advanced toggle +
 * per-layer `picto` crops, ported from EffectEditorPage. Simple = one
 * picker fanned to every layer in its native format (RGBY matrix layers +
 * RGB core line), same as the existing "apply to all" but from a live picker.
 */

// Per-layer color control supporting RGBY and RGB storage formats -- format
// conversion stays here (save shape byte-identical); rendering is the shared
// ColorRow (obvious clickable swatch, no per-picker preset strip).
function ColorPicker({ label, description, value, onChange, isRgb = false, picto, size = 'lg' }) {
  // Handle undefined or invalid values
  const safeValue = value || (isRgb ? 'FFFFFF' : 'FC00')
  const hexValue = isRgb ? `#${safeValue}` : rgbyToHex(safeValue)

  return (
    <ColorRow
      size={size}
      label={label}
      description={description}
      hex={hexValue}
      onChange={(hex) => onChange(isRgb ? hex.replace('#', '').toUpperCase() : hexToRgby(hex))}
      readout={isRgb ? null : `RGBY ${formatRgby(safeValue)}`}
      picto={picto}
    />
  )
}

export default function LaserEditorModal({
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
    wide: 'FC00',
    thin: 'FC00',
    outline: 'FC00',
    tip: 'FFFFFF',     // RGB (6-hex) layers: the beam's white core line
    center: 'FFFFFF'
  })
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState(null)

  // Simple mode: one picker fanned to every layer in its native format --
  // RGBY for the matrix layers (wide/thin/outline), 6-hex RGB for the core
  // line (center/tip). Same shape the "apply to all" presets already write.
  const fanOutSimple = (hex) => {
    const rgby = hexToRgby(hex)
    const rgb = hex.replace('#', '').toUpperCase()
    setColors({ wide: rgby, thin: rgby, outline: rgby, tip: rgb, center: rgb })
  }
  const { simpleColor, applySimpleColor } =
    useBespokeSimpleMode(rgbyToHex(colors.wide), fanOutSimple)

  // Initialize from editing mod if provided
  useEffect(() => {
    if (editingMod) {
      setName(editingMod.name || '')
      setColors(readEditorColors(editingMod, {
        wide: 'FC00', thin: 'FC00', outline: 'FC00', tip: 'FFFFFF', center: 'FFFFFF'
      }))
    } else {
      // Reset for new mod
      setName('')
      setColors({ wide: 'FC00', thin: 'FC00', outline: 'FC00', tip: 'FFFFFF', center: 'FFFFFF' })
    }
    setError(null)
  }, [editingMod, show])

  if (!show) return null

  const handleColorChange = (layer, rgby) => {
    setColors(prev => ({ ...prev, [layer]: rgby }))
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
          wide: { color: colors.wide },
          thin: { color: colors.thin },
          outline: { color: colors.outline },
          tip: { color: colors.tip },
          center: { color: colors.center }
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
      console.error('[LaserEditorModal] Save error:', err)
      setError(err.message || 'Failed to save mod')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editingMod) return
    if (!await appConfirm(`Delete "${editingMod.name}"?`, {
      title: 'Delete Laser Mod',
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
      console.error('[LaserEditorModal] Delete error:', err)
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
              {editingMod ? 'Edit Laser Mod' : 'Create Laser Mod'}
            </span>
            <span className="laser-editor-title-char">{character}</span>
          </div>
          <button className="laser-editor-close" onClick={handleClose}>
            <CloseIcon />
          </button>
        </div>

        <div className="laser-editor-body">
          <VisualEffectEditor key={`${character}/${editingMod?.id || 'new'}`}
            effectId="laser" character={character}
            previewColors={Object.fromEntries(Object.entries(colors).map(([key, value]) => [key, ['wide', 'thin', 'outline'].includes(key) ? rgbyToHex(value) : value]))}
            parts={extraType.properties.map(prop => ({ ...prop, label: prop.name }))}
            wholeEffect={<>
              <ColorPicker label="Beam Color" value={simpleColor.replace('#', '')}
                onChange={applySimpleColor} isRgb />
              <PresetRow onPick={applySimpleColor} activeHex={simpleColor} />
            </>}
            renderControls={prop => <ColorPicker label="Color"
              value={colors[prop.id]} onChange={value => handleColorChange(prop.id, value)}
              isRgb={prop.format === 'RGB'} />}
          />

          {/* Recipe name */}
          <div className="extra-editor-top">
          <div className="laser-editor-name-group">
            <label className="laser-editor-name-label">Mod Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Red Laser, Blue Fire..."
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
