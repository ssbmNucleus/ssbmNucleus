import { useEffect, useRef, useState } from 'react'
import { playSound, playHoverSound } from './sounds'
import { rebalanceWeights } from './playlistWeights'
import { AUDIO_ACCEPT } from './audioConvert'
import { backendMediaUrl } from '../config/config'
import MusicLoopEditor from './MusicLoopEditor'

/**
 * Weighted playlist editor shared by Menu Music and Stage Music. One
 * card per track — name on top, play-share slider below (the Smash
 * Ultimate "My Music" look). Shares always total 100%: dragging one
 * slider rescales the others live, and the result is saved when the
 * drag ends (or the % field blurs).
 */
export default function PlaylistEditor({
  tracks,            // [{index, music_id, name, chance, has_file}]
  busy,
  minTracks = 0,     // menus keep >= 1 song (no vanilla fallback)
  lastTrackHint = 'Remove this song',
  trackUrl,          // (track) => preview stream URL
  onSaveWeights,     // async (chances aligned with tracks)
  onRemove,          // async (track)
  onAddFiles,        // async (File[]) — the picker takes a multi-select
  header,
  footer,
}) {
  const [weights, setWeights] = useState(() => tracks.map(t => t.chance))
  const [playingTrack, setPlayingTrack] = useState(null)
  const [editingLoop, setEditingLoop] = useState(null)
  const [audioVersion, setAudioVersion] = useState(0)
  const audioRef = useRef(null)
  const fileRef = useRef(null)
  const dirtyRef = useRef(false)
  const draggingRef = useRef(false)

  // resync local weights whenever the server sends fresh tracks (but
  // never mid-drag — the user's hand wins over an in-flight response)
  const trackKey = tracks.map(t => `${t.music_id}:${t.chance}`).join('|')
  useEffect(() => {
    if (!draggingRef.current) {
      setWeights(tracks.map(t => t.chance))
      dirtyRef.current = false
    }
  }, [trackKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const stopAudio = () => {
    audioRef.current?.pause()
    audioRef.current = null
    setPlayingTrack(null)
  }

  useEffect(() => () => audioRef.current?.pause(), [])

  const toggleTrack = (track) => {
    if (playingTrack === track.index) {
      stopAudio()
      return
    }
    stopAudio()
    const url = trackUrl(track)
    const audio = new Audio(backendMediaUrl(`${url}${url.includes('?') ? '&' : '?'}loopVersion=${audioVersion}`))
    audio.onended = () => setPlayingTrack(null)
    audio.onerror = () => setPlayingTrack(null)
    audioRef.current = audio
    audio.play().catch(() => setPlayingTrack(null))
    setPlayingTrack(track.index)
  }

  const moveWeight = (i, value) => {
    if (Number.isNaN(value)) return
    setWeights(prev => rebalanceWeights(prev, i, value))
    dirtyRef.current = true
  }

  // commit reads through a ref so pointerup sees the latest drag value
  const weightsRef = useRef(weights)
  weightsRef.current = weights

  const commitWeights = () => {
    draggingRef.current = false
    if (!dirtyRef.current) return
    dirtyRef.current = false
    onSaveWeights([...weightsRef.current])
  }

  const removeTrack = (track) => {
    stopAudio()
    playSound('boop')
    onRemove(track)
  }

  // Multi-select: the whole picked set goes up in one call so the modal can
  // upload them in order and report a single summary.
  const addFiles = async (event) => {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    if (files.length) onAddFiles(files)
  }

  const locked = tracks.length === 1

  if (editingLoop) return <MusicLoopEditor track={editingLoop} onClose={() => setEditingLoop(null)} onSaved={() => setAudioVersion(v => v + 1)} />

  return (
    <>
      {header}
      <div className="playlist-tracks">
        {tracks.map((track, i) => (
          <div key={track.index} className="playlist-track">
            <div className="playlist-track-top">
              <button
                className={`music-modal-play ${playingTrack === track.index ? 'playing' : ''}`}
                onMouseEnter={playHoverSound}
                onClick={() => toggleTrack(track)}
                disabled={!track.has_file || busy}
                title="Preview"
              >
                {playingTrack === track.index ? '⏸' : '▶'}
              </button>
              <span className="playlist-name" title={track.name}>{track.name}</span>
              <button type="button" className="playlist-edit-loop" disabled={busy || !track.has_file}
                onClick={() => { stopAudio(); setEditingLoop(track) }} aria-label={`Edit loop for ${track.name}`}>
                Edit loop
              </button>
              <button
                className="playlist-remove"
                onMouseEnter={playHoverSound}
                onClick={() => removeTrack(track)}
                disabled={busy || tracks.length <= minTracks}
                title={tracks.length <= minTracks ? lastTrackHint : 'Remove this song'}
              >
                ✕
              </button>
            </div>
            <div className="playlist-weight-row">
              <input
                type="range"
                min="0"
                max="100"
                value={weights[i] ?? track.chance}
                className="playlist-slider"
                style={{ '--fill': `${weights[i] ?? track.chance}%` }}
                onPointerDown={() => { draggingRef.current = true }}
                onChange={(e) => moveWeight(i, parseInt(e.target.value, 10))}
                onPointerUp={commitWeights}
                onKeyUp={commitWeights}
                disabled={busy || locked}
                title={locked ? 'Only song on this playlist — always plays' : 'How often this song plays'}
              />
              <span className="playlist-chance">
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={weights[i] ?? track.chance}
                  onChange={(e) => moveWeight(i, parseInt(e.target.value, 10))}
                  onBlur={commitWeights}
                  onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur() }}
                  className="playlist-chance-input"
                  disabled={busy || locked}
                />
                <span className="playlist-pct">%</span>
              </span>
            </div>
          </div>
        ))}
      </div>
      <button
        className="music-modal-add"
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('boop'); fileRef.current?.click() }}
        disabled={busy}
        title="WAV, MP3, OGG, M4A, FLAC, HPS, BRSTM, DSP"
      >
        {busy ? 'Working…' : '+ Add Songs'}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept={AUDIO_ACCEPT}
        multiple
        onChange={addFiles}
        style={{ display: 'none' }}
      />
      {footer}
    </>
  )
}
