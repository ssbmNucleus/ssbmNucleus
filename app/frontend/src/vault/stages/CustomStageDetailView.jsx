import { useState, useEffect, useCallback, useRef } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import ConfirmDialog from '../../shared/ui/ConfirmDialog'
import InGameTestPanel from '../../shared/viewer/InGameTestPanel'
import { useInGameTest } from '../hooks/useInGameTest'
import { AUDIO_ACCEPT, toUploadableAudio } from '../../shared/audio/audioConvert'
import { API_URL, backendMediaUrl } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'
import './StagePlaylist.css'

export default function CustomStageDetailView({ stage, onBack, onDelete, onRename }) {
  const [editingName, setEditingName] = useState(false)
  const [nameValue, setNameValue] = useState(stage.name)
  const [saving, setSaving] = useState(false)
  const [showConfirmDialog, setShowConfirmDialog] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [playingTrack, setPlayingTrack] = useState(null)
  const [tracks, setTracks] = useState([])
  const [trackBusy, setTrackBusy] = useState(false)
  const [trackMessage, setTrackMessage] = useState('')
  const [assetBust, setAssetBust] = useState(0)
  const [hasIcon, setHasIcon] = useState(stage.has_icon)
  const [hasBanner, setHasBanner] = useState(stage.has_banner)
  const [seriesNames, setSeriesNames] = useState({})
  const audioRef = useRef(null)
  const iconFileRef = useRef(null)
  const bannerFileRef = useRef(null)
  const trackFileRef = useRef(null)
  const messageTimerRef = useRef(null)
  const inGameTest = useInGameTest()

  const fetchTracks = useCallback(async () => {
    try {
      const data = await api.get(`/custom-stages/${stage.slug}/playlist`)
      setTracks(data.tracks)
    } catch (err) {
      console.error('Failed to fetch stage playlist:', err)
    }
  }, [stage.slug, API_URL])

  useEffect(() => { fetchTracks() }, [fetchTracks])

  // series id -> name (shared list with custom characters)
  useEffect(() => {
    api.get(`/custom-characters/series-list`)
      .then(d => {
        setSeriesNames(Object.fromEntries(d.series.map(s => [s.id, s.name])))
      })
      .catch(() => {})
  }, [API_URL])

  // stop audio when leaving the page
  useEffect(() => () => {
    audioRef.current?.pause()
    clearTimeout(messageTimerRef.current)
  }, [])

  const flashTrackMessage = (text) => {
    setTrackMessage(text)
    clearTimeout(messageTimerRef.current)
    messageTimerRef.current = setTimeout(() => setTrackMessage(''), 4000)
  }

  const toggleTrack = (index) => {
    if (playingTrack === index) {
      audioRef.current?.pause()
      audioRef.current = null
      setPlayingTrack(null)
      return
    }
    audioRef.current?.pause()
    const audio = new Audio(`${API_URL}/custom-stages/${stage.slug}/audio/track/${index}?v=${assetBust}`)
    audio.onended = () => setPlayingTrack(null)
    audio.onerror = () => setPlayingTrack(null)
    audioRef.current = audio
    audio.play().catch(() => setPlayingTrack(null))
    setPlayingTrack(index)
  }

  const handleSaveRename = async () => {
    const trimmed = nameValue.trim()
    if (!trimmed || trimmed === stage.name) {
      setEditingName(false)
      setNameValue(stage.name)
      return
    }
    setSaving(true)
    try {
      await api.post(`/custom-stages/${stage.slug}/rename`, { newName: trimmed })
      setEditingName(false)
      onRename({ ...stage, name: trimmed })
    } catch (err) {
      alert(err.message || 'Rename failed')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await api.post(`/custom-stages/${stage.slug}/delete`)
      onDelete()
    } catch (err) {
      alert(err.message || 'Delete failed')
    } finally {
      setDeleting(false)
      setShowConfirmDialog(false)
    }
  }

  const handleExport = () => {
    const link = document.createElement('a')
    link.href = backendMediaUrl(`${API_URL}/custom-stages/${stage.slug}/export`)
    // Without `download` a click is a navigation, which the Electron shell
    // blocks for the backend origin (will-navigate), so nothing downloads.
    link.download = '' // keep the filename supplied by Content-Disposition
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const handleReplaceAsset = async (which, e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    try {
      const formData = new FormData()
      formData.append('file', file)
      await api.post(`/custom-stages/${stage.slug}/replace-asset/${which}`, formData)
      playSound('newSkin')
      if (which === 'icon') setHasIcon(true)
      if (which === 'banner') setHasBanner(true)
      setAssetBust(Date.now())
    } catch (err) {
      alert(err.message || 'Replace failed')
    }
  }

  const handleAddTrack = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setTrackBusy(true)
    try {
      // Upload the original source; the server validates and converts it.
      const upload = await toUploadableAudio(file)
      const formData = new FormData()
      formData.append('file', upload)
      formData.append('name', file.name.replace(/\.[^.]+$/, ''))
      const data = await api.post(`/custom-stages/${stage.slug}/playlist/add`, formData)
      playSound('newSkin')
      flashTrackMessage(`Added "${data.track.name}"`)
      await fetchTracks()
    } catch (err) {
      flashTrackMessage(`Add failed: ${err.message}`)
    } finally {
      setTrackBusy(false)
    }
  }

  const saveTrackChance = async (index, chance) => {
    try {
      await api.post(`/custom-stages/${stage.slug}/playlist/${index}/update`, { chance })
    } catch (err) {
      flashTrackMessage(`Save failed: ${err.message}`)
    }
  }

  const handleChanceInput = (index, value) => {
    const chance = Math.max(0, Math.min(100, parseInt(value, 10) || 0))
    setTracks(prev => prev.map(t => t.index === index ? { ...t, chance } : t))
  }

  const handleRemoveTrack = async (index) => {
    if (playingTrack != null) {
      audioRef.current?.pause()
      setPlayingTrack(null)
    }
    setTrackBusy(true)
    try {
      await api.post(`/custom-stages/${stage.slug}/playlist/${index}/remove`)
      playSound('back')
      flashTrackMessage('Track removed')
      setAssetBust(Date.now())
      await fetchTracks()
    } catch (err) {
      flashTrackMessage(`Remove failed: ${err.message}`)
    } finally {
      setTrackBusy(false)
    }
  }

  const iconUrl = hasIcon
    ? backendMediaUrl(`${API_URL}/custom-stages/${stage.slug}/icon`, assetBust || undefined)
    : null
  const bannerUrl = hasBanner
    ? backendMediaUrl(`${API_URL}/custom-stages/${stage.slug}/banner`, assetBust || undefined)
    : null

  const testActive = inGameTest.testingInGame || inGameTest.testResult || inGameTest.testError

  // Read-only facts (compact strip, mirrors the custom character page)
  const infoPairs = [
    ['Source', stage.source === 'zip' ? 'Imported ZIP' : stage.source === 'iso-scan' ? 'ISO Scan' : 'Project Scan'],
    ['Added', new Date(stage.date_added).toLocaleDateString()],
    stage.series_id != null && ['Series', seriesNames[stage.series_id] || `#${stage.series_id}`],
    stage.sound_bank != null && ['Sound Bank', stage.sound_bank],
    tracks.length > 0 && ['Music Tracks', tracks.length],
    stage.dat_files && stage.dat_files.length > 0 && ['Files', stage.dat_files.join(', ')],
  ].filter(Boolean)

  return (
    <div className="storage-viewer">
      <div className="character-detail">
        {/* ── Top bar: back + test CTA ── */}
        <div className="detail-top-bar">
          <button
            onClick={() => { playSound('back'); onBack(); }}
            className="back-button"
          >
            ← Back to Custom Stages
          </button>
          {!testActive && (
            <button
              className="ingame-test-cta"
              onMouseEnter={playHoverSound}
              onClick={() => {
                playSound('start')
                inGameTest.startCustomStageTest({ slug: stage.slug, name: stage.name })
              }}
              title="Build a one-mod test ISO and play a short match to verify it loads"
            >
              🎮 Test in Game
            </button>
          )}
        </div>

        {testActive && (
          <div className="ingame-test-stage">
            <InGameTestPanel
              test={inGameTest}
              onStart={() => inGameTest.startCustomStageTest({ slug: stage.slug, name: stage.name })}
            />
          </div>
        )}

        {/* ── Header: editable icon + name + editable banner ── */}
        <div className="custom-char-header">
          <div
            className="custom-char-icon-wrap"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); iconFileRef.current?.click() }}
            title="Stage select icon (64x56) — click to replace"
          >
            {iconUrl ? (
              <img src={iconUrl} alt={`${stage.name} icon`} className="custom-char-icon" />
            ) : (
              <span className="custom-char-icon-placeholder">{(stage.name || '?')[0]}</span>
            )}
            <span className="custom-char-icon-edit">✎</span>
          </div>
          <input
            ref={iconFileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => handleReplaceAsset('icon', e)}
            style={{ display: 'none' }}
          />

          <div className="custom-char-title">
            {editingName ? (
              <div className="custom-char-name-edit">
                <input
                  type="text"
                  value={nameValue}
                  onChange={(e) => setNameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSaveRename()
                    if (e.key === 'Escape') { setEditingName(false); setNameValue(stage.name) }
                  }}
                  autoFocus
                  className="edit-name-input"
                  disabled={saving}
                />
                <button className="mode-btn" onClick={handleSaveRename} disabled={saving}>
                  {saving ? 'Saving...' : 'Save'}
                </button>
                <button className="mode-btn" onClick={() => { setEditingName(false); setNameValue(stage.name) }}>
                  Cancel
                </button>
              </div>
            ) : (
              <h2 className="custom-char-name">
                {stage.name}
                <button
                  className="series-change-btn"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); setEditingName(true) }}
                  title="Rename stage"
                >
                  ✎
                </button>
              </h2>
            )}
          </div>

          <div
            className="custom-char-banner-wrap"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); bannerFileRef.current?.click() }}
            title="Stage select banner (224x56) — click to replace"
          >
            {bannerUrl ? (
              <img
                src={bannerUrl}
                alt="stage banner"
                className="custom-stage-banner-img"
              />
            ) : (
              <span className="custom-stage-banner-empty">+ banner</span>
            )}
            <span className="custom-char-icon-edit">✎</span>
          </div>
          <input
            ref={bannerFileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(e) => handleReplaceAsset('banner', e)}
            style={{ display: 'none' }}
          />
        </div>

        {/* ── Read-only info strip ── */}
        <div className="char-info-strip">
          {infoPairs.map(([label, value]) => (
            <span key={label} className="char-info-pair">
              <span className="char-strip-label">{label}</span>
              <span className="char-strip-value">{value}</span>
            </span>
          ))}
        </div>

        {/* ── Music playlist ── */}
        <div className="stage-playlist">
          <div className="custom-char-section-header">
            <h3 className="custom-char-section-title">Music</h3>
            <span className="stage-playlist-hint">
              Played on this stage — % sets how often each song is picked. Ported into your project on install.
            </span>
          </div>

          {trackMessage && <div className="stage-playlist-message">{trackMessage}</div>}

          <div className="stage-playlist-tracks">
            {tracks.map((track) => (
              <div key={track.index} className="stage-playlist-track">
                <button
                  className={`char-audio-btn ${playingTrack === track.index ? 'playing' : ''}`}
                  onMouseEnter={playHoverSound}
                  onClick={() => toggleTrack(track.index)}
                  disabled={!track.has_file}
                  title={track.has_file ? 'Preview' : 'Track file missing — rescan the source ISO'}
                >
                  {playingTrack === track.index ? '⏸' : '▶'}
                </button>
                <span className="char-audio-name" title={track.name}>{track.name}</span>
                <span className="stage-track-ratio">
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={track.chance}
                    onChange={(e) => handleChanceInput(track.index, e.target.value)}
                    onBlur={(e) => saveTrackChance(track.index, Math.max(0, Math.min(100, parseInt(e.target.value, 10) || 0)))}
                    onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur() }}
                    className="stage-track-chance-input"
                    disabled={trackBusy}
                    title="Chance to play (%)"
                  />
                  <span className="stage-track-pct">%</span>
                </span>
                <button
                  className="stage-track-remove"
                  onMouseEnter={playHoverSound}
                  onClick={() => handleRemoveTrack(track.index)}
                  disabled={trackBusy}
                  title="Remove this song"
                >
                  ✕
                </button>
              </div>
            ))}

            <button
              className="stage-track-add"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); trackFileRef.current?.click() }}
              disabled={trackBusy}
              title="Add WAV, MP3, OGG, M4A, FLAC, HPS, BRSTM, or DSP — the server converts it"
            >
              {trackBusy ? 'Working…' : '+ Add Song'}
            </button>
            <input
              ref={trackFileRef}
              type="file"
              accept={AUDIO_ACCEPT}
              onChange={handleAddTrack}
              style={{ display: 'none' }}
            />
          </div>
        </div>

        {/* ── Actions ── */}
        <div className="custom-stage-actions">
          <button
            className="intake-import-btn"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); handleExport() }}
            disabled={stage.source !== 'zip'}
            title={stage.source !== 'zip' ? 'Export only available for ZIP imports' : 'Download original ZIP'}
          >
            Export ZIP
          </button>
          <button
            className="intake-import-btn"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); setShowConfirmDialog(true) }}
            style={{ background: 'var(--color-danger, #e53e3e)' }}
            disabled={deleting}
          >
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>

      <ConfirmDialog
        show={showConfirmDialog}
        title="Delete Custom Stage"
        message={`Are you sure you want to delete "${stage.name}"? This cannot be undone.`}
        confirmText="Delete"
        onConfirm={handleDelete}
        onCancel={() => setShowConfirmDialog(false)}
      />
    </div>
  )
}
