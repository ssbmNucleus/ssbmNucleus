import { useEffect, useRef, useState } from 'react'
import { api } from '../transport/api'
import { getMasterVolume } from './sounds'
import { createMusicLoopPlayer } from './musicLoopPlayer'
import './MusicLoopEditor.css'

function waveform(buffer) {
  const samples = buffer.getChannelData(0)
  const points = []
  for (let x = 0; x < 320; x++) {
    let peak = 0
    const end = Math.floor((x + 1) * samples.length / 320)
    for (let i = Math.floor(x * samples.length / 320); i < end; i++) peak = Math.max(peak, Math.abs(samples[i]))
    points.push(`M${x},${40 - peak * 37}V${40 + peak * 37}`)
  }
  return points.join(' ')
}

function clockTime(seconds) {
  seconds = Math.floor(seconds * 10) / 10
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, '0')}`
}

export default function MusicLoopEditor({ track, onClose, onSaved }) {
  const [info, setInfo] = useState(null)
  const [start, setStart] = useState('0')
  const [wave, setWave] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [position, setPosition] = useState(0)
  const [volume, setVolume] = useState(getMasterVolume)
  const player = useRef(null)
  const mounted = useRef(true)
  const base = `/music/${track.music_id}/loop`

  const pause = () => {
    player.current?.pause()
    setPosition(player.current?.position() || 0)
    setPlaying(false)
  }

  useEffect(() => {
    mounted.current = true
    setLoading(true)
    setPlaying(false)
    setPosition(0)
    setInfo(null)
    setError('')
    setMessage('')
    let disposed = false
    const controller = new AbortController()
    let context
    async function load() {
      try {
        const metadata = await api.get(base, { signal: controller.signal })
        const blob = await api.blob(`${base}/preview`, { query: { version: metadata.version }, signal: controller.signal })
        if (disposed) return
        context = new AudioContext()
        const buffer = await context.decodeAudioData(await blob.arrayBuffer())
        if (disposed) return
        player.current = createMusicLoopPlayer(context, buffer, { loopStart: metadata.loop_start_ms / 1000, volume })
        setWave(waveform(buffer))
        setInfo(metadata)
        setStart((metadata.loop_start_ms / 1000).toFixed(3))
      } catch (err) {
        if (!disposed) setError(err.message || 'Could not load song')
      } finally {
        if (!disposed) setLoading(false)
      }
    }
    load()
    return () => {
      disposed = true
      mounted.current = false
      controller.abort()
      player.current?.dispose()
      player.current = null
      context?.close().catch(() => {})
    }
  }, [base])

  useEffect(() => {
    if (!playing) return
    const timer = setInterval(() => setPosition(player.current?.position() || 0), 100)
    return () => clearInterval(timer)
  }, [playing])

  const duration = info ? info.duration_ms / 1000 : 0
  const seconds = Number(start)
  const valid = start !== '' && Number.isFinite(seconds) && seconds >= 0 && seconds < duration
  const changeStart = (value) => {
    setStart(value)
    if (value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) < duration) {
      player.current?.setLoopStart(Number(value))
    }
    setMessage('')
  }
  const listen = async (action, value) => {
    setError('')
    try {
      const transport = player.current
      await transport[action](value)
      if (!mounted.current) return
      setPlaying(transport.playing)
      setPosition(transport.position())
    } catch (err) {
      if (mounted.current) {
        setPlaying(player.current?.playing || false)
        setError(err.message || 'Could not play song')
      }
    }
  }
  const save = async () => {
    pause()
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const saved = await api.post(base, { version: info.version, loop_start_ms: seconds * 1000 })
      if (!mounted.current) return
      setInfo(saved)
      setStart((saved.loop_start_ms / 1000).toFixed(3))
      player.current?.setLoopStart(saved.loop_start_ms / 1000)
      setMessage('Loop saved.')
      onSaved()
    } catch (err) {
      if (mounted.current) setError(err.message || 'Could not save loop')
    } finally {
      if (mounted.current) setSaving(false)
    }
  }

  return (
    <section className="music-loop-editor" aria-label={`Edit loop for ${track.name}`}>
      <div className="music-loop-heading">
        <button type="button" onClick={onClose} disabled={saving}>← Songs</button>
        <strong>{track.name}</strong>
      </div>
      {loading ? <p role="status">Loading waveform…</p> : info && <>
        <section className="music-loop-panel music-loop-listen" aria-label="Listen">
          <h3>Listen</h3>
          <div className="music-loop-actions">
            <button type="button" className="music-loop-play" onClick={() => playing ? pause() : listen('play')} disabled={saving}>
              <span aria-hidden="true">{playing ? 'Ⅱ' : '▶'}</span> {playing ? 'Pause' : 'Play'}
            </button>
            <button type="button" onClick={() => listen('play', 0)} disabled={saving}>From start</button>
            <label className="music-loop-volume">Volume
              <input type="range" min="0" max="1" step="0.01" value={volume} onChange={event => {
                const value = Number(event.target.value)
                setVolume(value)
                player.current?.setVolume(value)
              }} />
            </label>
          </div>
          <div className="music-loop-wave" aria-hidden="true" title="Seek playback" onClick={(event) => {
            if (saving) return
            const rect = event.currentTarget.getBoundingClientRect()
            listen('seek', (event.clientX - rect.left) / rect.width * duration)
          }}>
            <svg viewBox="0 0 320 80" preserveAspectRatio="none">
              <rect x={valid ? seconds / duration * 320 : 0} y="0" width={valid ? (1 - seconds / duration) * 320 : 320} height="80" className="music-loop-region" />
              <path d={wave} />
              {valid && <line x1={seconds / duration * 320} x2={seconds / duration * 320} y1="0" y2="80" />}
              <line className="music-loop-playhead" x1={position / duration * 320} x2={position / duration * 320} y1="0" y2="80" />
            </svg>
            <span>Intro</span><span>Loop region</span>
          </div>
          <input className="music-loop-seek" aria-label="Playback position" type="range" min="0" max={Math.max(0, duration - 0.001)} step="0.001"
            value={position} onChange={event => listen('seek', Number(event.target.value))} disabled={saving}
            aria-valuetext={`${clockTime(position)} of ${clockTime(duration)}`} />
          <div className="music-loop-timestamps"><span>{clockTime(position)}</span><span>{clockTime(duration)}</span></div>
        </section>

        <section className="music-loop-panel music-loop-adjust" aria-label="Adjust loop">
          <h3>Adjust loop</h3>
          <label className="music-loop-time">Loop start (seconds)
            <input type="number" min="0" max={Math.max(0, duration - 0.001)} step="0.001" value={start}
              onChange={(e) => changeStart(e.target.value)} disabled={saving} aria-invalid={!valid} />
          </label>
          <input className="music-loop-slider" aria-label="Loop start" type="range" min="0" max={Math.max(0, duration - 0.001)} step="0.001"
            value={valid ? seconds : 0} onChange={(e) => changeStart(e.target.value)} disabled={saving} />
          {!valid && <p role="alert">Choose a time between zero and the end of the song.</p>}
          <div className="music-loop-actions music-loop-edit-actions">
            <button type="button" onClick={() => changeStart((player.current?.position() || 0).toFixed(3))} disabled={saving}>Use playhead</button>
            <button type="button" onClick={() => listen('play', Math.max(seconds, duration - 3))} disabled={!valid || saving}>Preview repeat</button>
            <button type="button" className="music-loop-save" onClick={save} disabled={!valid || saving}>{saving ? 'Saving…' : 'Save loop'}</button>
          </div>
          <p className="music-loop-note">Applies wherever this song plays in the project.</p>
        </section>
      </>}
      {error && <p className="music-loop-error" role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
    </section>
  )
}
