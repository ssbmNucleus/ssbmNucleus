import VisualEffectEditor from './VisualEffectEditor'
import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { hexToRgby, rgbyToHex, formatRgby } from '../lib/rgbyColor'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { CloseIcon, SaveIcon } from '../../shared/ui/Icons'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { useBespokeSimpleMode } from './useBespokeSimpleMode'
import { readEditorColors, serializeEditorColors } from './editorRecipe.js'
import { ColorRow } from './EditorControls'
import ShineImagePanel from './ShineImagePanel'
import { isImageShineMod, supportsImageMod } from './imageShineMod'
import { api } from '../../shared/transport/api'
import './ShineEditor.css'

/**
 * ShineEditorModal - editor for Fox/Falco shine, in two kinds.
 *
 * COLORS: the two-color gradient pattern
 * - Primary (621F vanilla) - bright edge/outline vertices
 * - Secondary (AB9F vanilla) - fill/interior vertices
 * Working mods replace these in pairs (e.g., Green: 621F→0FF0, AB9F→0A45)
 *
 * IMAGE: the community "image shines" (NERV, Honeycomb, ...) put a picture
 * where the hexagon is instead of recoloring it, so they have no color
 * pickers at all -- ShineImagePanel handles them, and the backend
 * (vault/routes/extras/effect_model.py) rebuilds the effect model around the
 * image. The two kinds share one mod list because they patch the same model:
 * installing one takes the other back out.
 */

/**
 * Interactive SVG Hexagon showing the two-color gradient
 * Primary = edge/outline, Secondary = fill
 */
// Preset shine color combinations (matching known working mods)
const SHINE_PRESETS = [
  { name: 'Vanilla Blue', primary: '621F', secondary: 'AB9F' },
  { name: 'Green', primary: '0FF0', secondary: '0A45' },
  { name: 'Purple', primary: 'FCCC', secondary: 'A50F' },
  { name: 'Red', primary: 'FC00', secondary: '8800' },
  { name: 'White', primary: 'FFFF', secondary: 'AAAA' },
  { name: 'Gray', primary: 'FFFF', secondary: '5D88' }
]

// Default colors matching vanilla shine
const DEFAULT_COLORS = {
  primary: '621F',    // Vanilla bright blue edge
  secondary: 'AB9F',  // Vanilla grayish fill
  flash1: '63FF',     // Vanilla startup flash color
  flash2: 'FFFF',     // Vanilla startup flash highlight
  sparkles: 'FFFFFF'  // Vanilla sparkle particle color (RGB, not RGBY)
}

// Layer metadata for UI
const LAYER_INFO = {
  primary: { label: 'Edge', desc: 'Bright edge/outline color' },
  secondary: { label: 'Band', desc: 'Wide hexagon band inside the edge; the center stays transparent' },
  flash1: { label: 'Flash Color', desc: 'Startup flash color' },
  flash2: { label: 'Flash Highlight', desc: 'Startup flash highlight' },
  sparkles: { label: 'Sparkles', desc: 'Sparkle particles around the shield' }
}

// RGBY color control -- format conversion stays here (save shape
// byte-identical); rendering is the shared ColorRow (obvious clickable
// swatch, no per-picker preset strip).
function ColorPicker({ label, description, value, onChange, picto }) {
  const safeValue = value || '621F'
  return (
    <ColorRow
      size="lg"
      label={label}
      description={description}
      hex={rgbyToHex(safeValue)}
      onChange={(hex) => onChange(hexToRgby(hex))}
      readout={`RGBY ${formatRgby(safeValue)}`}
      picto={picto}
    />
  )
}

// Plain RGB color control (sparkles is 6-char RGB, not RGBY like the others)
function RgbColorPicker({ label, description, value, onChange, picto }) {
  const safeValue = value || 'FFFFFF'
  return (
    <ColorRow
      size="lg"
      label={label}
      description={description}
      hex={`#${safeValue}`}
      onChange={(hex) => onChange(hex.replace('#', '').toUpperCase())}
      picto={picto}
    />
  )
}

export default function ShineEditorModal({
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
  // 'colors' | 'image'. Only offered when the extra declares image support,
  // and forced to 'image' when the mod being edited IS an image mod.
  const imageSupported = supportsImageMod(extraType)
  const [kind, setKind] = useState('colors')

  // Simple mode: one picker fanned to every shine layer in its native format
  // -- RGBY for edge/fill/flash, RGB 6-hex for sparkles. Advanced mode keeps
  // the interactive region-selector UX unchanged.
  const fanOutSimple = (hex) => {
    const rgby = hexToRgby(hex)
    const rgb = hex.replace('#', '').toUpperCase()
    setColors({ primary: rgby, secondary: rgby, flash1: rgby, flash2: rgby, sparkles: rgb })
  }
  const { simpleColor, applySimpleColor } =
    useBespokeSimpleMode(rgbyToHex(colors.primary), fanOutSimple)

  // Initialize from editing mod if provided
  useEffect(() => {
    if (editingMod) {
      setName(editingMod.name || '')
      setColors(readEditorColors(editingMod, DEFAULT_COLORS))
    } else {
      // Reset for new mod
      setName('')
      setColors({ ...DEFAULT_COLORS })
    }
    // An image mod has no colors to show, so open on its own panel; a color
    // mod (or a fresh create) opens on the pickers.
    setKind(imageSupported && isImageShineMod(editingMod) ? 'image' : 'colors')
    setError(null)
  }, [editingMod, show, imageSupported])

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
      // Vanilla is also an explicit choice: omitting it leaves a previously
      // installed flash/sparkle override in the project.
      const modifications = serializeEditorColors(colors)

      const modData = {
        character,
        extraType: extraType.id,
        name: name.trim(),
        modifications
      }

      // Colors authored from an image mod are a separate recipe; changing
      // tabs must not overwrite the image's source and format metadata.
      if (editingMod && !isImageShineMod(editingMod)) {
        modData.modId = editingMod.id
      }

      const data = await api.post('/storage/extras/create', modData)
      onSave?.(data.mod)
      onClose()
    } catch (err) {
      console.error('[ShineEditorModal] Save error:', err)
      setError(err.message || 'Failed to save mod')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editingMod) return
    if (!await appConfirm(`Delete "${editingMod.name}"?`, {
      title: 'Delete Shine Mod',
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

  // Apply a preset combination. NOTE: merge into prev state -- replacing the
  // whole object dropped flash1/flash2/sparkles (undefined), which the save
  // path then wrote as {color: undefined} (pre-2026-07 bug).
  const handleApplyPreset = (preset) => {
    setColors(prev => ({
      ...prev,
      primary: preset.primary,
      secondary: preset.secondary
    }))
  }

  // Get display colors for SVG preview
  const handleClose = () => {
    playSound('back')
    onClose()
  }

  const modal = (
    <div className="laser-editor-overlay" onClick={(e) => e.target === e.currentTarget && handleClose()}>
      <div className="laser-editor-modal shine-editor-modal">
        <div className="laser-editor-header">
          <div className="laser-editor-title">
            <span className="laser-editor-title-text">
              {editingMod ? 'Edit Shine Mod' : 'Create Shine Mod'}
            </span>
            <span className="laser-editor-title-char">{character}</span>
          </div>
          <button className="laser-editor-close" onClick={handleClose}>
            <CloseIcon />
          </button>
        </div>

        <div className="laser-editor-body">
          {/* Shared effect note */}
          <div className="shared-note">
            Shared between Fox and Falco
          </div>

          {/* Colors vs image: two genuinely different mods of the same
              effect, so they get a kind switch rather than a hidden mode. */}
          {imageSupported && (
            <div className="extra-mode-toggle shine-kind-toggle" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={kind === 'colors'}
                className={kind === 'colors' ? 'active' : ''}
                onClick={() => { setError(null); setKind('colors') }}
              >Colors</button>
              <button
                type="button"
                role="tab"
                aria-selected={kind === 'image'}
                className={kind === 'image' ? 'active' : ''}
                onClick={() => { setError(null); setKind('image') }}
              >Image</button>
            </div>
          )}

          {kind === 'image' ? (
            <ShineImagePanel
              character={character}
              extraType={extraType}
              editingMod={isImageShineMod(editingMod) ? editingMod : null}
              onError={setError}
              onSaved={(mod) => { onSave?.(mod); onClose() }}
            />
          ) : (
          <>

          <VisualEffectEditor key={`${character}/${editingMod?.id || 'new'}`}
            effectId="shine" character={character}
            previewColors={Object.fromEntries(Object.entries(colors).map(([key, value]) => [key, key === 'sparkles' ? value : rgbyToHex(value)]))}
            parts={[
              { id: 'shield', label: 'Hexagon', controls: ['primary', 'secondary'],
                description: 'A thin edge around a wide band. The center stays transparent.' },
              { id: 'flash', label: 'Startup Flash', controls: ['flash1', 'flash2'] },
              { id: 'sparkles', label: 'Sparkles', controls: ['sparkles'] },
            ]}
            wholeEffect={<>
              <RgbColorPicker label="Shine Color" value={simpleColor.replace('#', '')} onChange={applySimpleColor} />
              <div className="extra-preset-row">
                <span className="extra-preset-row-label">Edge & Band</span>
                <div className="extra-preset-row-swatches">
                  {SHINE_PRESETS.map(preset => <button type="button" key={preset.name}
                    className="laser-preset shine-preset-combo"
                    aria-label={`Apply ${preset.name} to edge and band`}
                    style={{ background: `linear-gradient(135deg, ${rgbyToHex(preset.primary)} 50%, ${rgbyToHex(preset.secondary)} 50%)` }}
                    onClick={() => handleApplyPreset(preset)} title={preset.name} />)}
                </div>
              </div>
            </>}
            renderControls={part => part.controls.map(key => key === 'sparkles' ? (
              <RgbColorPicker key={key} label="Color" value={colors[key]}
                onChange={value => handleColorChange(key, value)} />
            ) : (
              <ColorPicker key={key} label={LAYER_INFO[key].label} description={LAYER_INFO[key].desc}
                value={colors[key]} onChange={value => handleColorChange(key, value)} />
            ))}
          />

          {/* Recipe name */}
          <div className="extra-editor-top">
            <div className="laser-editor-name-group">
              <label className="laser-editor-name-label">Mod Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Green Shine, Purple Reflector..."
                className="laser-editor-name-input"
              />
            </div>

          </div>
          </>
          )}

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
              {kind === 'image' ? 'Close' : 'Cancel'}
            </button>
            {/* Image mods are created by the panel's own import button (there
                is no in-place image edit), so no Save here in that mode. */}
            {kind === 'colors' && (
              <button
                className="laser-editor-save"
                onClick={handleSave}
                disabled={saving || deleting}
              >
                <SaveIcon />
                <span>{saving ? 'Saving...' : 'Save Mod'}</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
