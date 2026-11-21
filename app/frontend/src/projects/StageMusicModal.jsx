import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../shared/ui/appContentPortal'
import { CloseIcon } from '../shared/ui/Icons'
import PlaylistEditor from '../shared/audio/PlaylistEditor'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { uploadPlaylistTracks, summarizeUpload } from './playlistUpload'
import { api } from '../shared/transport/api'

/**
 * Per-stage music editor for the six tournament stages — the stage-side
 * twin of MenuMusicModal. Edits the open project's stage playlist
 * directly; play shares always total 100%. An empty playlist is exactly
 * vanilla, and the backend then serves the stage's actual vanilla
 * song(s) as the tracks (`vanilla: true`) — so the list always shows
 * what plays, and any edit materializes a custom playlist built on it.
 * "Restore Vanilla" just clears the playlist again.
 */
export default function StageMusicModal({ show, stage, displayName, onClose }) {
  const [tracks, setTracks] = useState([])
  const [vanilla, setVanilla] = useState(true)
  const [projectOpen, setProjectOpen] = useState(true)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [confirmVanilla, setConfirmVanilla] = useState(false)
  const base = api.url(`/das/${encodeURIComponent(stage)}/stage-music`)

  const loadTracks = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.get(base)
      setTracks(data.tracks || [])
      setVanilla(!!data.vanilla)
      setProjectOpen(data.project_open)
    } catch (err) {
      setError(err.message || 'Failed to load stage music')
    } finally {
      setLoading(false)
    }
  }, [base])

  useEffect(() => {
    if (show) loadTracks()
    else {
      setMessage('')
      setError('')
      setConfirmVanilla(false)
    }
  }, [show, loadTracks])

  const setPlaylist = async (entries) => {
    const data = await api.post(`${base}/set`, { entries })
    setTracks(data.tracks || [])
    setVanilla(!!data.vanilla)
  }

  const saveWeights = async (chances) => {
    try {
      await setPlaylist(tracks.map((t, i) => ({ music_id: t.music_id, chance: chances[i] })))
    } catch (err) {
      setMessage(`Save failed: ${err.message}`)
      loadTracks()
    }
  }

  const removeTrack = async (track) => {
    setBusy(true)
    try {
      const entries = tracks
        .filter(t => t.index !== track.index)
        .map(t => ({ music_id: t.music_id, chance: t.chance }))
      await setPlaylist(entries)
      setMessage(entries.length === 0 ? 'Vanilla music restored.' : '')
    } catch (err) {
      setMessage(`Remove failed: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  const restoreVanilla = async () => {
    setConfirmVanilla(false)
    setBusy(true)
    playSound('back')
    try {
      await setPlaylist([])
      setMessage('Vanilla music restored.')
    } catch (err) {
      setMessage(`Restore failed: ${err.message}`)
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
        onAdded: (data) => {
          setTracks(data.tracks || [])
          setVanilla(!!data.vanilla)
        },
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
            <span>Stage Music</span>
            <small>{displayName || stage}</small>
          </div>
          <button className="music-modal-close" onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>
        {message && <div className="music-modal-message">{message}</div>}
        <div className="music-modal-body">
          {loading ? (
            <div className="music-modal-empty">Loading stage music…</div>
          ) : error ? (
            <div className="music-modal-empty music-modal-error">{error}</div>
          ) : !projectOpen ? (
            <div className="music-modal-empty">
              Open a project to choose the music {displayName || stage} plays.
            </div>
          ) : (
            <PlaylistEditor
              tracks={tracks}
              busy={busy}
              minTracks={vanilla ? 1 : 0}
              lastTrackHint="Add a song before removing the last vanilla track"
              trackUrl={(track) => `${base}/track/${track.index}?v=${track.music_id ?? 0}`}
              onSaveWeights={saveWeights}
              onRemove={removeTrack}
              onAddFiles={addTracks}
              header={vanilla && <div className="playlist-vanilla-note">Vanilla Music</div>}
              footer={!vanilla && (
                <button
                  className={`playlist-vanilla-btn ${confirmVanilla ? 'confirm' : ''}`}
                  onMouseEnter={playHoverSound}
                  onClick={() => {
                    if (confirmVanilla) restoreVanilla()
                    else { playSound('boop'); setConfirmVanilla(true) }
                  }}
                  disabled={busy}
                  title="Restore this stage's default playlist"
                >
                  {confirmVanilla
                    ? `Remove ${tracks.length} song${tracks.length === 1 ? '' : 's'} and restore vanilla?`
                    : 'Restore Vanilla Music'}
                </button>
              )}
            />
          )}
        </div>
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
