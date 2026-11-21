/**
 * PercentFontEditor - per-glyph editor for a percent font mod.
 *
 * One tile per glyph: digits 0-9, the % sign, and the HP mark (stamina mode).
 * Click a tile to upload a replacement image — it lands on every damage-HUD
 * slot showing that glyph (the digits repeat across three texture banks).
 * Edited glyphs get a badge and can be reverted; uploads install as RGB5A3
 * so color survives (vanilla glyphs are grayscale).
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import './PauseEditor.css'

const GLYPH_LABELS = {
  percent: '% Sign',
  hp: 'HP Mark',
  ready: 'Ready',
  go: 'Go!',
  game: 'Game!',
  time: 'Time!',
  sudden: 'Sudden',
  death: 'Death',
  success: 'Success!',
  failure: 'Failure',
  complete: 'Complete!',
}

// mode 'glyphs' = percent digits / % / HP; mode 'words' = the READY / GO! /
// GAME! banner set. Same backend mod, different slot groups.
export default function PercentFontEditor({ mod, onBack, mode = 'glyphs', isDraft = false, onSaveDraft, onDiscardDraft }) {
  const [glyphs, setGlyphs] = useState([])
  const [error, setError] = useState('')
  const [busyKey, setBusyKey] = useState(null)
  const [bust, setBust] = useState({})        // key -> cache-bust stamp
  const [pickerKey, setPickerKey] = useState(null)
  const fileInputRef = useRef(null)

  const fetchGlyphs = useCallback(async () => {
    try {
      const data = await api.get(`/menus/percent/${mod.id}/${mode === 'words' ? 'words' : 'glyphs'}`)
      setGlyphs(data.glyphs || [])
      setError('')
    } catch (err) {
      setError(err.message || 'Failed to load glyphs')
    }
  }, [mod.id, mode])

  useEffect(() => { fetchGlyphs() }, [fetchGlyphs])

  // backendMediaUrl carries the backend token: these are /api/ routes, and a
  // bare <img src> has no auth header (every banner 401'd in the packaged app).
  const glyphUrl = (g) => backendMediaUrl(g.url, bust[g.key])

  const openPicker = (key) => {
    if (busyKey !== null) return
    playSound('boop')
    setPickerKey(key)
    fileInputRef.current?.click()
  }

  const handleFile = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    const key = pickerKey
    setPickerKey(null)
    if (!file || key === null) return

    setBusyKey(key)
    const formData = new FormData()
    formData.append('key', key)
    formData.append('file', file)
    try {
      await api.post(`/menus/percent/${mod.id}/replace_glyph`, formData)
      playSound('newSkin')
      setBust(prev => ({ ...prev, [key]: Date.now() }))
      await fetchGlyphs()
    } catch (err) {
      setError(err.message || 'Replace failed')
    } finally {
      setBusyKey(null)
    }
  }

  const handleRevert = async (key) => {
    setBusyKey(key)
    try {
      await api.post(`/menus/percent/${mod.id}/revert_glyph`, { key })
      playSound('boop')
      setBust(prev => ({ ...prev, [key]: Date.now() }))
      await fetchGlyphs()
    } catch (err) {
      setError(err.message || 'Revert failed')
    } finally {
      setBusyKey(null)
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
        <h3 className="pause-editor-title">{isDraft ? `New ${mode === 'words' ? 'Ready/Go Pack' : 'Percent Font'} (draft)` : mod.name}</h3>
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
          <span className="pause-editor-hint">Click a glyph to replace it</span>
        )}
      </div>

      {error && <div className="import-message error">{error}</div>}

      <div className="percent-editor-glyphs">
        {glyphs.map((g) => {
          const label = GLYPH_LABELS[g.key] || g.key
          return (
            <div key={g.key} className={`pause-editor-chip percent-editor-glyph ${g.replaced ? 'replaced' : ''}`}>
              <button
                className={`percent-editor-glyph-preview ${busyKey === g.key ? 'busy' : ''}`}
                onMouseEnter={playHoverSound}
                onClick={() => openPicker(g.key)}
                title={`Replace the "${label}" glyph everywhere it appears`}
              >
                <img src={glyphUrl(g)} alt={label} draggable={false} />
              </button>
              <div className="pause-editor-chip-info">
                <span className="pause-editor-chip-name">{label}</span>
                {g.replaced && (
                  <button
                    className="mod-card-btn"
                    onMouseEnter={playHoverSound}
                    onClick={() => handleRevert(g.key)}
                    disabled={busyKey !== null}
                    title="Restore this glyph's original texture"
                  >
                    Revert
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
