/**
 * PauseTextureEditor - per-slot texture editor for a pause screen mod.
 *
 * Lays the 11 GmPause textures out on a 4:3 canvas approximating where they
 * sit on the real pause screen (corner brackets, P1/Pause text top-right,
 * main graphic + hints bottom-left). Click a slot to upload a replacement;
 * user-replaced slots get a badge and can be reverted. A strip below lists
 * every slot for precise access to the tiny ones.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import './PauseEditor.css'

// Slot geometry on a 720x540 reference canvas (measured from a vanilla
// in-game pause capture). The two 88x72 main-graphic textures (t4 + t10)
// render LAYERED at the same bottom-left position — the editor shows them
// as a single slot and the backend edits them as a pair. The camera swirl
// (t0) draws on top of the main graphic.
const SLOT_LAYOUT = {
  0:  { name: 'Camera Swirl',     x: 63,  y: 423, w: 54,  h: 54 },
  1:  { name: 'Trim (left)',      x: 424, y: 55,  w: 22,  h: 27 },
  2:  { name: 'Trim (right)',     x: 667, y: 55,  w: 22,  h: 27 },
  3:  { name: 'Edge Bar',         x: 686, y: 372, w: 25,  h: 90 },
  4:  { name: 'Main Graphic',     x: 14,  y: 400, w: 136, h: 108 },
  5:  { name: 'Corner Bracket',   x: 30,  y: 42,  w: 67,  h: 67 },
  6:  { name: '"Pause" Text',     x: 515, y: 55,  w: 146, h: 27 },
  7:  { name: '"P1" Text',        x: 452, y: 55,  w: 57,  h: 27 },
  8:  { name: 'L+R+A+Start Hint', x: 513, y: 438, w: 147, h: 43 },
  9:  { name: 'Z Retry Hint',     x: 513, y: 486, w: 104, h: 47 },
}
const REF_W = 720
const REF_H = 540

// Secondary 88x72 main-graphic slots (everything after the first) are hidden:
// the backend replaces/reverts the whole pair through the visible one.
const hiddenMainSlots = (textures) => {
  const mains = textures.filter(t => t.width === 88 && t.height === 72)
  return new Set(mains.slice(1).map(t => t.index))
}

const pct = (v, ref) => `${(v / ref) * 100}%`

export default function PauseTextureEditor({ mod, onBack, isDraft = false, onSaveDraft, onDiscardDraft }) {
  const [textures, setTextures] = useState([])
  const [error, setError] = useState('')
  const [busySlot, setBusySlot] = useState(null)
  const [bust, setBust] = useState({})        // index -> cache-bust stamp
  const [pickerSlot, setPickerSlot] = useState(null)
  const fileInputRef = useRef(null)

  const fetchTextures = useCallback(async () => {
    try {
      const data = await api.get(`/menus/pause/${mod.id}/textures`)
      setTextures(data.textures || [])
      setError('')
    } catch (err) {
      setError(err.message || 'Failed to load textures')
    }
  }, [mod.id])

  useEffect(() => { fetchTextures() }, [fetchTextures])

  // backendMediaUrl carries the backend token (bare <img src> to an /api/
  // route has no auth header and 401s in the packaged app).
  const texUrl = (t) => backendMediaUrl(t.url, bust[t.index])

  const openPicker = (index) => {
    if (busySlot !== null) return
    playSound('boop')
    setPickerSlot(index)
    fileInputRef.current?.click()
  }

  const handleFile = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    const index = pickerSlot
    setPickerSlot(null)
    if (!file || index === null) return

    setBusySlot(index)
    const formData = new FormData()
    formData.append('index', String(index))
    formData.append('file', file)
    try {
      await api.post(`/menus/pause/${mod.id}/replace_texture`, formData)
      playSound('newSkin')
      setBust(prev => ({ ...prev, [index]: Date.now() }))
      await fetchTextures()
    } catch (err) {
      setError(err.message || 'Replace failed')
    } finally {
      setBusySlot(null)
    }
  }

  const handleRevert = async (index) => {
    setBusySlot(index)
    try {
      await api.post(`/menus/pause/${mod.id}/revert_texture`, { index })
      playSound('boop')
      setBust(prev => ({ ...prev, [index]: Date.now() }))
      await fetchTextures()
    } catch (err) {
      setError(err.message || 'Revert failed')
    } finally {
      setBusySlot(null)
    }
  }

  return (
    <div className="pause-editor">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/*"
        onChange={handleFile}
        style={{ display: 'none' }}
      />

      <div className="pause-editor-header">
        <button
          className="mode-btn"
          onMouseEnter={playHoverSound}
          onClick={() => {
            playSound('back')
            if (isDraft) { onDiscardDraft?.() } else { onBack() }
          }}
        >
          {isDraft ? '✕ Discard' : '← Back'}
        </button>
        <h3 className="pause-editor-title">{isDraft ? 'New Pause Mod (draft)' : mod.name}</h3>
        {isDraft ? (
          <button
            className="btn-build-iso"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); onSaveDraft?.() }}
            title="Save this mod to your vault"
          >
            Save to Vault
          </button>
        ) : (
          <span className="pause-editor-hint">Click a texture to replace it</span>
        )}
      </div>

      {error && <div className="import-message error">{error}</div>}

      <div className="pause-editor-canvas">
        {textures.map((t) => {
          const slot = SLOT_LAYOUT[t.index]
          if (!slot || hiddenMainSlots(textures).has(t.index)) return null
          return (
            <button
              key={t.index}
              className={`pause-editor-slot ${t.replaced ? 'replaced' : ''} ${busySlot === t.index ? 'busy' : ''}`}
              style={{
                left: pct(slot.x, REF_W),
                top: pct(slot.y, REF_H),
                width: pct(slot.w, REF_W),
                height: pct(slot.h, REF_H),
                // smaller slots stack above bigger ones so overlapped
                // elements (the swirl on the main graphic) stay clickable
                zIndex: Math.max(1, 200 - Math.round((slot.w * slot.h) / 100)),
              }}
              title={`${slot.name} — ${t.width}x${t.height} ${t.format}${t.replaced ? ' (edited)' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => openPicker(t.index)}
            >
              <img src={texUrl(t)} alt={slot.name} draggable={false} />
            </button>
          )
        })}
      </div>

      <div className="pause-editor-strip">
        {textures.map((t) => {
          if (hiddenMainSlots(textures).has(t.index)) return null
          const slot = SLOT_LAYOUT[t.index] || { name: `Texture ${t.index}` }
          return (
            <div key={t.index} className={`pause-editor-chip ${t.replaced ? 'replaced' : ''}`}>
              <button
                className="pause-editor-chip-preview"
                onMouseEnter={playHoverSound}
                onClick={() => openPicker(t.index)}
                title={`Replace ${slot.name}`}
              >
                <img src={texUrl(t)} alt={slot.name} draggable={false} />
              </button>
              <div className="pause-editor-chip-info">
                <span className="pause-editor-chip-name">{slot.name}</span>
                <span className="pause-editor-chip-meta">{t.width}x{t.height}</span>
              </div>
              {t.replaced && (
                <button
                  className="mod-card-btn"
                  onMouseEnter={playHoverSound}
                  onClick={() => handleRevert(t.index)}
                  disabled={busySlot !== null}
                  title="Restore this slot's original texture"
                >
                  Revert
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
