import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { CloseIcon, SaveIcon } from '../../shared/ui/Icons'
import { playSound } from '../../shared/audio/sounds'
import { ColorRow } from '../extras/EditorControls'
import { API_URL, backendMediaUrl } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'

/**
 * GawColorCreatorModal - "Create New Mod" flow for Mr. Game & Watch.
 *
 * G&W's costume colors are engine-side (the m-ex GawColors table), not in his
 * DAT, so the texture-painting SkinCreator can't recolor him. This modal picks
 * a fill (+ outline) color and POSTs /gaw/create, which builds a vault skin
 * wrapping the vanilla DAT plus a gaw.json sidecar; installing the skin sets
 * the slot's colors via MexCLI.
 *
 * The live preview recolors the vanilla black CSP on a canvas with the same
 * body/outline split the backend recolor uses (body = dark pixels ramped to
 * the fill; near-white outline tinted by the outline color).
 */

// Vanilla GAMEWATCH_COLOR fills + a few known-good extras.
const GAW_PRESETS = [
  { name: 'Black (vanilla)', fill: '#000000' },
  { name: 'Red (vanilla)', fill: '#6E0000' },
  { name: 'Blue (vanilla)', fill: '#00006E' },
  { name: 'Green (vanilla)', fill: '#006E00' },
  { name: 'Purple', fill: '#4B0064' },
  { name: 'Orange', fill: '#B44600' },
  { name: 'Teal', fill: '#00646E' },
  { name: 'White', fill: '#DCDCDC' },
]

const DEFAULT_FILL = '#000000'
const DEFAULT_OUTLINE = '#FFFFFF'
// The engine's vanilla outline alpha (0x80). The UI picks outline RGB only;
// alpha stays vanilla so the in-game edge keeps its translucency.
const OUTLINE_ALPHA_HEX = '80'

function hexToRgb(hex) {
  const h = (hex || '#000000').replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16) || 0,
    parseInt(h.slice(2, 4), 16) || 0,
    parseInt(h.slice(4, 6), 16) || 0,
  ]
}

/** Recolor the vanilla black G&W portrait: dark body pixels ramp toward the
 * fill, near-white outline pixels tint by the outline color, mid grays (drop
 * shadow) stay. Mirrors the backend recolor's body/outline split. */
function recolorGawCsp(ctx, srcImageData, fillHex, outlineHex) {
  const [fr, fg, fb] = hexToRgb(fillHex)
  const [or_, og, ob] = hexToRgb(outlineHex)
  const src = srcImageData.data
  const out = ctx.createImageData(srcImageData.width, srcImageData.height)
  const dst = out.data
  const BODY_LUM = 72 // body ramps 0->72, same knee as the stock recolor
  for (let i = 0; i < src.length; i += 4) {
    const r = src[i], g = src[i + 1], b = src[i + 2], a = src[i + 3]
    const lum = (r + g + b) / 3
    if (a === 0) {
      dst[i + 3] = 0
      continue
    }
    if (lum < BODY_LUM) {
      const t = (BODY_LUM - lum) / BODY_LUM // 1 = pure body, 0 = edge of body
      dst[i] = Math.round(t * fr + (1 - t) * lum)
      dst[i + 1] = Math.round(t * fg + (1 - t) * lum)
      dst[i + 2] = Math.round(t * fb + (1 - t) * lum)
    } else if (lum > 180) {
      // outline / highlight: tint the near-white pixels
      dst[i] = Math.round((r * or_) / 255)
      dst[i + 1] = Math.round((g * og) / 255)
      dst[i + 2] = Math.round((b * ob) / 255)
    } else {
      // mid grays (drop shadow) unchanged
      dst[i] = r; dst[i + 1] = g; dst[i + 2] = b
    }
    dst[i + 3] = a
  }
  ctx.putImageData(out, 0, 0)
}

export default function GawColorCreatorModal({ show, onClose, onCreated }) {
  const [name, setName] = useState('')
  const [fill, setFill] = useState(DEFAULT_FILL)
  const [outline, setOutline] = useState(DEFAULT_OUTLINE)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const canvasRef = useRef(null)
  const sourceRef = useRef(null) // decoded vanilla CSP ImageData

  // Reset on open
  useEffect(() => {
    if (show) {
      setName('')
      setFill(DEFAULT_FILL)
      setOutline(DEFAULT_OUTLINE)
      setError(null)
    }
  }, [show])

  // Load the vanilla black CSP once per open
  useEffect(() => {
    if (!show) return
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      const canvas = canvasRef.current
      if (!canvas) return
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      const ctx = canvas.getContext('2d', { willReadFrequently: true })
      ctx.drawImage(img, 0, 0)
      sourceRef.current = ctx.getImageData(0, 0, canvas.width, canvas.height)
      recolorGawCsp(ctx, sourceRef.current, fill, outline)
    }
    img.onerror = () => setError('Could not load the vanilla G&W portrait for preview')
    img.src = backendMediaUrl(`${API_URL}/gaw/preview-source`)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show, API_URL])

  // Repaint on color change
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !sourceRef.current) return
    recolorGawCsp(canvas.getContext('2d', { willReadFrequently: true }), sourceRef.current, fill, outline)
  }, [fill, outline])

  if (!show) return null

  const handleClose = () => {
    playSound('back')
    onClose()
  }

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Please enter a name for this color')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const data = await api.post('/gaw/create', {
        name: name.trim(),
        fill: `#FF${fill.replace('#', '').toUpperCase()}`,
        outline: `#${OUTLINE_ALPHA_HEX}${outline.replace('#', '').toUpperCase()}`,
      })
      playSound('newSkin')
      onCreated?.(data)
      onClose()
    } catch (err) {
      console.error('[GawColorCreatorModal] Save error:', err)
      setError(err.message || 'Failed to create color mod')
    } finally {
      setSaving(false)
    }
  }

  const modal = (
    <div className="laser-editor-overlay" onClick={(e) => e.target === e.currentTarget && handleClose()}>
      <div className="laser-editor-modal gaw-color-modal">
        <div className="laser-editor-header">
          <div className="laser-editor-title">
            <span className="laser-editor-title-text">Create G&amp;W Color</span>
            <span className="laser-editor-title-char">Mr. Game &amp; Watch</span>
          </div>
          <button className="laser-editor-close" onClick={handleClose}>
            <CloseIcon />
          </button>
        </div>

        <div className="laser-editor-body">
          <div className="shared-note">
            Game &amp; Watch is flat-shaded by the engine — a mod is just a fill +
            outline color, applied to his whole body in-game.
          </div>

          <div className="extra-editor-top">
            <div className="laser-editor-name-group">
              <label className="laser-editor-name-label">Color Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Purple, Lava, Ice..."
                className="laser-editor-name-input"
              />
            </div>

            <div className="gaw-preview" style={{ textAlign: 'center' }}>
              <canvas
                ref={canvasRef}
                className="gaw-preview-canvas"
                style={{ maxWidth: '136px', width: '100%', imageRendering: 'auto' }}
              />
            </div>
          </div>

          <div className="extra-editor-controls">
            <div className="extra-preset-row">
              <span className="extra-preset-row-label">Presets</span>
              <div className="extra-preset-row-swatches">
                {GAW_PRESETS.map((preset) => (
                  <button
                    key={preset.name}
                    type="button"
                    className="laser-preset"
                    style={{ background: preset.fill }}
                    onClick={() => setFill(preset.fill)}
                    title={preset.name}
                  />
                ))}
              </div>
            </div>
          </div>

          <ColorRow
            size="lg"
            label="Fill Color"
            description="G&W's body — the whole silhouette"
            hex={fill}
            onChange={setFill}
          />
          <ColorRow
            size="lg"
            label="Outline Color"
            description="The thin edge around him (vanilla is white)"
            hex={outline}
            onChange={setOutline}
          />

          {error && <div className="laser-editor-error">{error}</div>}
        </div>

        <div className="laser-editor-footer">
          <div className="laser-editor-footer-right">
            <button className="laser-editor-cancel" onClick={handleClose}>
              Cancel
            </button>
            <button
              className="laser-editor-save"
              onClick={handleSave}
              disabled={saving}
            >
              <SaveIcon />
              <span>{saving ? 'Creating… (rendering portrait)' : 'Create Mod'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
