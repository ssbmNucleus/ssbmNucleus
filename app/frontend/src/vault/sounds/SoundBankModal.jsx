import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { CloseIcon } from '../../shared/ui/Icons'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { AUDIO_ACCEPT, toUploadableAudio } from '../../shared/audio/audioConvert'
import { API_URL, backendMediaUrl } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'

/**
 * Sound Bank browser: lists every sound in a fighter's SSM bank with
 * play / download / replace / revert per sound. The pristine bank is
 * kept server-side for lossless revert.
 *
 * Default endpoints target custom characters (`slug`), where edits are
 * folded back into fighter.zip. Pass `endpoint` (path after API_URL) to
 * point it elsewhere — e.g. vanilla-character vault sound packs
 * (`storage/characters/<name>/audio`), which install at ISO export.
 */
export default function SoundBankModal({ show, slug, displayName, onClose, endpoint }) {
  const [sounds, setSounds] = useState([])
  const [hasBackup, setHasBackup] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [playingIndex, setPlayingIndex] = useState(null)
  const [busyIndex, setBusyIndex] = useState(null)   // row with an in-flight replace/revert
  const [message, setMessage] = useState('')
  const [bust, setBust] = useState(0)                // cache-buster for decoded wavs
  const audioRef = useRef(null)
  const fileRef = useRef(null)
  const replaceTargetRef = useRef(null)
  const messageTimerRef = useRef(null)

  const base = `${API_URL}/${endpoint || `custom-characters/${slug}/audio`}`

  const fetchSounds = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get(`${base}/sounds`)
      setSounds(data.sounds)
      setHasBackup(data.has_original_backup)
    } catch (err) {
      setError(err.message || 'Failed to load sound bank')
    } finally {
      setLoading(false)
    }
  }, [base])

  useEffect(() => {
    if (show) fetchSounds()
  }, [show, fetchSounds])

  // stop playback when the modal closes/unmounts
  useEffect(() => {
    if (!show) {
      audioRef.current?.pause()
      audioRef.current = null
      setPlayingIndex(null)
    }
    return () => audioRef.current?.pause()
  }, [show])

  useEffect(() => () => clearTimeout(messageTimerRef.current), [])

  const flashMessage = (text) => {
    setMessage(text)
    clearTimeout(messageTimerRef.current)
    messageTimerRef.current = setTimeout(() => setMessage(''), 4000)
  }

  const togglePlay = (sound) => {
    if (playingIndex === sound.index) {
      audioRef.current?.pause()
      audioRef.current = null
      setPlayingIndex(null)
      return
    }
    audioRef.current?.pause()
    const audio = new Audio(backendMediaUrl(`${base}/sound/${sound.index}`, bust))
    audio.onended = () => setPlayingIndex(null)
    audio.onerror = () => setPlayingIndex(null)
    audioRef.current = audio
    audio.play().catch(() => setPlayingIndex(null))
    setPlayingIndex(sound.index)
  }

  const handleDownload = async (sound) => {
    playSound('boop')
    try {
      const blob = await api.blob(`${base}/sound/${sound.index}?v=${bust}`)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${sound.name || `sound_${sound.index}`}.wav`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      flashMessage(`Download failed: ${err.message}`)
    }
  }

  const pickReplacement = (sound) => {
    playSound('boop')
    replaceTargetRef.current = sound.index
    fileRef.current?.click()
  }

  const handleReplaceFile = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    const index = replaceTargetRef.current
    if (!file || index == null) return

    audioRef.current?.pause()
    setPlayingIndex(null)
    setBusyIndex(index)
    try {
      // Upload the original source; the server owns decoding and conversion so
      // large tracks never allocate decoded PCM in Electron's renderer.
      const upload = await toUploadableAudio(file)
      const formData = new FormData()
      formData.append('file', upload)
      await api.post(`${base}/sound/${index}/replace`, formData)
      playSound('newSkin')
      flashMessage(`Replaced sound ${index} with ${file.name}`)
      setBust(b => b + 1)
      await fetchSounds()
    } catch (err) {
      flashMessage(`Replace failed: ${err.message}`)
    } finally {
      setBusyIndex(null)
    }
  }

  const handleRevert = async (sound) => {
    playSound('back')
    audioRef.current?.pause()
    setPlayingIndex(null)
    setBusyIndex(sound.index)
    try {
      await api.post(`${base}/sound/${sound.index}/revert`)
      flashMessage(`Restored original sound ${sound.index}`)
      setBust(b => b + 1)
      await fetchSounds()
    } catch (err) {
      flashMessage(`Revert failed: ${err.message}`)
    } finally {
      setBusyIndex(null)
    }
  }

  const handleRevertAll = async () => {
    playSound('back')
    audioRef.current?.pause()
    setPlayingIndex(null)
    setBusyIndex(-1)
    try {
      await api.post(`${base}/sounds/revert-all`)
      flashMessage('Restored the original sound bank')
      setBust(b => b + 1)
      await fetchSounds()
    } catch (err) {
      flashMessage(`Revert failed: ${err.message}`)
    } finally {
      setBusyIndex(null)
    }
  }

  if (!show) return null

  const modifiedCount = sounds.filter(s => s.modified).length
  const formatDuration = (ms) => ms == null ? '—' : `${(ms / 1000).toFixed(2)}s`
  const formatFreq = (hz) => hz == null ? '' : `${(hz / 1000).toFixed(hz % 1000 ? 1 : 0)} kHz`

  const close = () => { playSound('back'); onClose() }

  const modal = (
    <div className="sb-overlay" onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="sb-modal">
        <div className="sb-header">
          <div className="sb-title">
            <span className="sb-title-label">{displayName || slug}</span>
            {sounds.length > 0 && (
              <span className="sb-count">
                {sounds.length} sounds{modifiedCount ? ` · ${modifiedCount} replaced` : ''}
              </span>
            )}
          </div>
          <div className="sb-header-actions">
            {hasBackup && modifiedCount > 0 && (
              <button
                className="sb-revert-all-btn"
                onMouseEnter={playHoverSound}
                onClick={handleRevertAll}
                disabled={busyIndex !== null}
                title="Restore every sound from the original bank"
              >
                ↩ Revert All
              </button>
            )}
            <button className="sb-close-btn" onClick={close}>
              <CloseIcon />
            </button>
          </div>
        </div>

        {message && <div className="sb-message">{message}</div>}

        <div className="sb-list">
          {loading ? (
            <div className="sb-empty">Loading…</div>
          ) : error ? (
            <div className="sb-empty sb-error">{error}</div>
          ) : sounds.length === 0 ? (
            <div className="sb-empty">This character has no sound bank.</div>
          ) : (
            sounds.map(sound => (
              <div
                key={sound.index}
                className={`sb-row ${sound.modified ? 'sb-row--modified' : ''} ${playingIndex === sound.index ? 'sb-row--playing' : ''}`}
              >
                <button
                  className={`sb-play-btn ${playingIndex === sound.index ? 'playing' : ''}`}
                  onMouseEnter={playHoverSound}
                  onClick={() => togglePlay(sound)}
                  disabled={busyIndex !== null}
                >
                  {playingIndex === sound.index ? '⏸' : '▶'}
                </button>
                <span className="sb-index">#{sound.index}</span>
                <span className="sb-name" title={sound.modified && sound.source ? `Replaced with ${sound.source}` : sound.name}>
                  {sound.name}
                  {sound.modified && <span className="sb-modified-badge">replaced</span>}
                </span>
                <span className="sb-meta">
                  {formatDuration(sound.durationMs)}
                  {sound.frequency ? ` · ${formatFreq(sound.frequency)}` : ''}
                </span>
                <span className="sb-actions">
                  <button
                    className="sb-action-btn"
                    onMouseEnter={playHoverSound}
                    onClick={() => handleDownload(sound)}
                    disabled={busyIndex !== null}
                    title="Download as WAV"
                  >
                    ⬇
                  </button>
                  <button
                    className="sb-action-btn sb-replace-btn"
                    onMouseEnter={playHoverSound}
                    onClick={() => pickReplacement(sound)}
                    disabled={busyIndex !== null}
                    title="Replace with supported audio — the server converts it automatically"
                  >
                    {busyIndex === sound.index ? '…' : 'Replace'}
                  </button>
                  {sound.modified && (
                    <button
                      className="sb-action-btn sb-revert-btn"
                      onMouseEnter={playHoverSound}
                      onClick={() => handleRevert(sound)}
                      disabled={busyIndex !== null}
                      title="Restore the original sound"
                    >
                      ↩
                    </button>
                  )}
                </span>
              </div>
            ))
          )}
        </div>

        <input
          ref={fileRef}
          type="file"
          accept={AUDIO_ACCEPT}
          onChange={handleReplaceFile}
          style={{ display: 'none' }}
        />
      </div>

      <style>{SOUND_BANK_STYLES}</style>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}

const SOUND_BANK_STYLES = `
        .sb-overlay {
          position: absolute;
          inset: 0;
          background: rgba(6, 12, 20, 0.92);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: calc(var(--z-modal) + 40);
          padding: var(--page-block-padding) var(--modal-inline-padding);
          overflow: auto;
          overscroll-behavior: contain;
        }

        .sb-modal {
          width: min(100%, 720px);
          max-height: min(100%, var(--modal-max-height));
          background: linear-gradient(
            165deg,
            var(--color-bg-elevated) 0%,
            var(--color-bg-base) 40%,
            var(--color-bg-deep) 100%
          );
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-2xl);
          box-shadow: var(--shadow-xl), 0 0 0 1px rgba(125, 211, 232, 0.08), 0 0 80px rgba(0, 0, 0, 0.6);
          display: flex;
          flex-direction: column;
          overflow: hidden;
          margin: auto;
          animation: modalSlideUp var(--duration-normal) var(--ease-spring);
        }

        .sb-overlay { animation: fadeIn var(--duration-fast) var(--ease-out); }

        .sb-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: var(--space-3) var(--space-6);
          background: rgba(0, 0, 0, 0.15);
          border-bottom: 1px solid var(--color-border-subtle);
          flex-shrink: 0;
        }

        .sb-title {
          display: flex;
          align-items: baseline;
          gap: var(--space-3);
          min-width: 0;
        }

        .sb-title-label {
          font-family: var(--font-display);
          font-size: var(--text-lg);
          font-weight: 700;
          color: var(--color-text-primary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .sb-count {
          color: var(--color-text-tertiary);
          font-size: var(--text-sm);
        }

        .sb-header-actions {
          display: flex;
          align-items: center;
          gap: var(--space-3);
        }

        .sb-revert-all-btn {
          background: transparent;
          border: 1px solid var(--color-danger-muted);
          color: var(--color-danger);
          border-radius: var(--radius-md);
          padding: 4px 10px;
          cursor: pointer;
          font-size: var(--text-sm);
        }

        .sb-revert-all-btn:hover:not(:disabled) {
          background: var(--color-danger-muted);
          color: var(--color-text-primary);
        }

        .sb-close-btn {
          background: transparent;
          border: none;
          color: var(--color-text-secondary);
          cursor: pointer;
          display: flex;
          padding: var(--space-1);
        }

        .sb-close-btn:hover {
          color: var(--color-text-primary);
        }

        .sb-message {
          margin: var(--space-2) var(--space-6) 0;
          padding: var(--space-2) var(--space-3);
          background: var(--color-bg-surface);
          border: 1px solid var(--color-border);
          border-radius: var(--radius-md);
          color: var(--color-text-secondary);
          font-size: var(--text-sm);
        }

        .sb-list {
          overflow-y: auto;
          padding: var(--space-3) var(--space-4);
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .sb-empty {
          padding: var(--space-8);
          text-align: center;
          color: var(--color-text-muted);
        }

        .sb-error {
          color: var(--color-danger);
        }

        .sb-row {
          display: flex;
          align-items: center;
          gap: var(--space-3);
          padding: var(--space-1) var(--space-2);
          border-radius: var(--radius-md);
          border: 1px solid transparent;
          transition: background var(--transition-fast), border-color var(--transition-fast);
        }

        .sb-row:hover {
          background: var(--color-bg-surface);
        }

        .sb-row--playing {
          border-color: var(--color-cyan);
        }

        .sb-row--modified .sb-name {
          color: var(--color-cyan);
        }

        .sb-play-btn {
          width: 28px;
          height: 28px;
          flex-shrink: 0;
          border-radius: 50%;
          border: 1px solid var(--color-border);
          background: var(--color-bg-surface);
          color: var(--color-text-primary);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 11px;
        }

        .sb-play-btn:hover:not(:disabled),
        .sb-play-btn.playing {
          border-color: var(--color-cyan);
          color: var(--color-cyan);
        }

        .sb-index {
          width: 36px;
          flex-shrink: 0;
          color: var(--color-text-muted);
          font-size: var(--text-sm);
          font-variant-numeric: tabular-nums;
        }

        .sb-name {
          flex: 1;
          min-width: 56px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          color: var(--color-text-primary);
          font-size: var(--text-sm);
        }

        .sb-modified-badge {
          margin-left: var(--space-2);
          padding: 1px 6px;
          border-radius: var(--radius-sm);
          background: rgba(125, 211, 232, 0.15);
          color: var(--color-cyan);
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }

        .sb-meta {
          flex-shrink: 0;
          color: var(--color-text-tertiary);
          font-size: var(--text-sm);
          font-variant-numeric: tabular-nums;
        }

        .sb-actions {
          display: flex;
          gap: var(--space-1);
          flex-shrink: 0;
        }

        .sb-action-btn {
          background: transparent;
          border: 1px solid var(--color-border);
          color: var(--color-text-secondary);
          border-radius: var(--radius-md);
          padding: 3px 8px;
          cursor: pointer;
          font-size: var(--text-sm);
        }

        .sb-action-btn:hover:not(:disabled) {
          border-color: var(--color-cyan);
          color: var(--color-cyan);
        }

        .sb-action-btn:disabled {
          opacity: 0.5;
          cursor: default;
        }

        .sb-revert-btn:hover:not(:disabled) {
          border-color: var(--color-danger);
          color: var(--color-danger);
        }
`
