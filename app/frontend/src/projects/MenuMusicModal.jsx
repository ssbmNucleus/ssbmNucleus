import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../shared/ui/appContentPortal'
import { CloseIcon } from '../shared/ui/Icons'
import PlaylistEditor from '../shared/audio/PlaylistEditor'
import { playSound } from '../shared/audio/sounds'
import { uploadPlaylistTracks, summarizeUpload } from './playlistUpload'
import { api } from '../shared/transport/api'

/**
 * Editor for the open project's menu playlist. Menu music is global —
 * one weighted playlist shared by every menu (vanilla is two songs at
 * 75% / 25%) — so this edits the project directly, no vault packs.
 * Play shares always total 100%.
 */
export default function MenuMusicModal({ show, onClose }) {
  const [tracks, setTracks] = useState([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const base = api.url('/menu-music')

  const loadTracks = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.get(base)
      setTracks(data.tracks || [])
    } catch (err) {
      setError(err.message || 'Failed to load menu music')
    } finally {
      setLoading(false)
    }
  }, [base])

  useEffect(() => {
    if (show) loadTracks()
    else {
      setMessage('')
      setError('')
    }
  }, [show, loadTracks])

  const saveWeights = async (chances) => {
    try {
      const entries = tracks.map((t, i) => ({ music_id: t.music_id, chance: chances[i] }))
      const data = await api.post(`${base}/set`, { entries })
      setTracks(data.tracks || [])
    } catch (err) {
      setMessage(`Save failed: ${err.message || 'Failed to save play chances'}`)
      loadTracks()
    }
  }

  const removeTrack = async (track) => {
    setBusy(true)
    try {
      const entries = tracks
        .filter(t => t.index !== track.index)
        .map(t => ({ music_id: t.music_id, chance: t.chance }))
      const data = await api.post(`${base}/set`, { entries })
      setTracks(data.tracks || [])
      setMessage('')
    } catch (err) {
      setMessage(`Remove failed: ${err.message || 'Failed to remove song'}`)
    } finally {
      setBusy(false)
    }
  }

  // Uploads run one at a time (see playlistUpload) and the list grows as
  // each song lands, so a big batch shows progress instead of freezing.
  const addTracks = async (files) => {
    setBusy(true)
    try {
      const result = await uploadPlaylistTracks({
        files,
        url: `${base}/tracks/add`,
        onProgress: ({ index, total, name }) => setMessage(
          total > 1
            ? `Converting and adding “${name}” (${index + 1} of ${total})…`
            : 'Converting and adding song…'
        ),
        onAdded: (data) => setTracks(data.tracks || []),
      })
      setMessage(summarizeUpload(result))
      if (result.added.length) playSound('newSkin')
    } finally {
      setBusy(false)
    }
  }

  if (!show) return null

  const modal = (
    <div className="music-modal-overlay" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <div className="music-modal">
        <div className="music-modal-header">
          <div className="music-modal-title">
            <span>Menu Music</span>
            <small>All Menus</small>
          </div>
          <button className="music-modal-close" onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>
        {message && <div className="music-modal-message">{message}</div>}
        <div className="music-modal-body">
          {loading ? (
            <div className="music-modal-empty">Loading menu music…</div>
          ) : error ? (
            <div className="music-modal-empty music-modal-error">{error}</div>
          ) : (
            <>
              {tracks.length === 0 && (
                <div className="music-modal-empty">No menu songs found in this project.</div>
              )}
              <PlaylistEditor
                tracks={tracks}
                busy={busy}
                minTracks={1}
                lastTrackHint="Menus always need one song — add a replacement first"
                trackUrl={(track) => `${base}/track/${track.index}?v=${track.music_id ?? 0}`}
                onSaveWeights={saveWeights}
                onRemove={removeTrack}
                onAddFiles={addTracks}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
