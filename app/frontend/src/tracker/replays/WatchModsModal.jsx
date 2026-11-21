import { useEffect, useState } from 'react'
import { BACKEND_URL } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { charName, stageName } from '../../shared/data/meleeNames'
import GallerySelect from '../../shared/ui/GallerySelect'
import { PremiumActionButton } from '../lib/LiteGate'
import { WatchPlayback, stopWatch, useWatchJob, useWatchPlayback } from './WatchPlayback'
import { popupPart } from './watchJob'
import '../lib/ModsModal.css'

const API = `${BACKEND_URL}/api/nucleome`

// The one "Watch" popup: pick vault skins for the players (and the stage),
// optionally record, then play. With mods a fresh one-shot ISO is built
// (stateless — no caching) and deleted afterwards; with nothing picked the
// vanilla ISO plays directly. The playback Dolphin shows IN the popup
// (WatchPlayback, shared with the playlist popup).
// `clip` (optional, from the Combos tab): {start, end} replay frames — plays
// just that slice instead of the whole game. The watch itself is a job
// (useWatchJob): the popup shows the newest one, also one already running.
export default function WatchModsModal({ game, clip, onClose }) {
  const [options, setOptions] = useState(null)
  const [picks, setPicks] = useState({}) // port -> skin_id ('' = vanilla)
  const [stagePick, setStagePick] = useState('') // stage variant id ('' = vanilla)
  const [record, setRecord] = useState(false)
  const [compress, setCompress] = useState(false)
  const [anonymize, setAnonymize] = useState(false)
  const [widescreen, setWidescreen] = useState(false)
  const [noMusic, setNoMusic] = useState(false)
  const [recordDir, setRecordDir] = useState('')
  const [error, setError] = useState(null)
  const { job, start: startWatch, dismiss } = useWatchJob()

  useEffect(() => {
    api.get(`/api/nucleome/watch-mods/options/${game.id}`)
      .then((d) => setOptions(d))
      .catch(() => setError('Backend unavailable'))
    api.get('/api/nucleome/watch-mods/recording-dir')
      .then((d) => setRecordDir(d.dir || ''))
      .catch(() => {})
  }, [game.id])

  // Pick the recording folder (native dialog in the app; typed path in a
  // browser preview). Persists server-side so it sticks across watches.
  const chooseRecordDir = async () => {
    let picked = null
    if (window.electron?.selectDirectory) {
      picked = await window.electron.selectDirectory()
    } else {
      picked = window.prompt('Recording folder (absolute path):', recordDir)
    }
    if (!picked) return
    const d = await api.post('/api/nucleome/watch-mods/recording-dir', { path: picked })
      .catch(() => null)
    if (d?.dir) setRecordDir(d.dir)
  }

  const busy = !!job?.busy
  const part = popupPart({ options, error, job })
  const playback = useWatchPlayback(job)

  const start = async () => {
    playSound('start')
    setError(null)
    const selections = Object.entries(picks)
      .filter(([, skinId]) => skinId)
      .map(([port, skinId]) => ({ port: Number(port), skin_id: skinId }))
    try {
      await startWatch('/api/nucleome/watch-mods/start', {
        game_id: game.id,
        selections,
        record,
        compress: record && compress,
        anonymize,
        widescreen,
        no_music: noMusic,
        ...(stagePick ? { stage_skin_id: stagePick } : {}),
        ...(clip ? { start_frame: clip.start, end_frame: clip.end } : {}),
      })
    } catch (e) {
      setError(e.message || 'start failed')
    }
  }

  const anyPicked = Object.values(picks).some(Boolean) || Boolean(stagePick)
  const humans = (options?.players || [])
  const stageMods = options?.stage_mods || []

  // Closing while the game plays ends the playback too — this popup IS its
  // window. The stop lands before the capture lets go, so the dying Dolphin's
  // windows are never handed back to the desktop.
  const closeModal = async () => {
    if (job?.state === 'playing') await stopWatch(job.id)
    onClose()
  }

  return (
    <div className="watchmods-overlay" onClick={busy ? undefined : closeModal}>
      <div className={`watchmods-modal ${playback.modalClass}`}
           onClick={(e) => e.stopPropagation()}>
        <div className="watchmods-head">
          <h3>{clip ? 'Watch combo' : 'Watch replay'}</h3>
          <button className="watchmods-close" onMouseEnter={playHoverSound}
                  onClick={closeModal} disabled={busy && job?.state !== 'playing'}>×</button>
        </div>

        {part === 'loading' && <p className="watchmods-loading">Loading…</p>}
        {part === 'load-error' && <p className="watchmods-warn">{error}</p>}

        {part === 'form' && (
          <>
            <div className="watchmods-players">
              {stageMods.length > 0 && (
                <div className="watchmods-player watchmods-stagerow">
                  <img className="watchmods-stageicon" alt=""
                       src={`${API}/stage-icon/${game.stage}`} />
                  <div className="watchmods-who">
                    <span className="watchmods-char">{stageName(game.stage)}</span>
                    <span className="watchmods-name">Stage</span>
                  </div>
                  <GallerySelect
                    value={stagePick}
                    onChange={setStagePick}
                    placeholder="Vanilla"
                    aspect="landscape"
                    searchPlaceholder="Search stage mods…"
                    options={stageMods.map((s) => ({
                      value: s.id,
                      label: s.name,
                      icon: s.screenshot ? `${BACKEND_URL}${s.screenshot}` : undefined,
                    }))}
                  />
                </div>
              )}
              {humans.map((p) => (
                <div key={p.port} className="watchmods-player">
                  <img className="watchmods-stock" alt=""
                       src={`${API}/stock/${p.character}/${p.costume ?? 0}`} />
                  <div className="watchmods-who">
                    <span className="watchmods-char">{charName(p.character)}</span>
                    <span className="watchmods-name">
                      {p.name || p.code || (p.type === 1 ? 'CPU' : `Port ${p.port}`)}
                    </span>
                  </div>
                  {p.skins.length > 0 ? (
                    <GallerySelect
                      value={picks[p.port] || ''}
                      onChange={(v) => setPicks((prev) => ({ ...prev, [p.port]: v }))}
                      placeholder="Vanilla"
                      aspect="portrait"
                      searchPlaceholder="Search skins…"
                      options={p.skins.map((s) => ({
                        value: s.id,
                        label: s.name,
                        icon: `${BACKEND_URL}${s.csp}`,
                      }))}
                    />
                  ) : (
                    <span className="watchmods-noskins">No vault skins for {charName(p.character)}</span>
                  )}
                </div>
              ))}
            </div>

            {!options.playback_ready && (
              <p className="watchmods-warn">Slippi playback Dolphin not found — install the Slippi Launcher.</p>
            )}
            {!options.vanilla_iso && (
              <p className="watchmods-warn">No vanilla ISO found in your Slippi Launcher settings.</p>
            )}
            {error && <p className="watchmods-warn">{error}</p>}

            <div className="watchmods-record-row">
              <label className="watchmods-record">
                <input
                  type="checkbox"
                  checked={record}
                  onChange={(e) => { playSound('boop'); setRecord(e.target.checked) }}
                />
                Record to video
              </label>
              {record && (
                <span className="watchmods-record-dir">
                  <span className="watchmods-record-path" title={recordDir}>{recordDir}</span>
                  <button className="watchmods-link" onMouseEnter={playHoverSound}
                          onClick={chooseRecordDir}>Change…</button>
                </span>
              )}
            </div>
            {record && (
              <label className="watchmods-compress">
                <input
                  type="checkbox"
                  checked={compress}
                  onChange={(e) => { playSound('boop'); setCompress(e.target.checked) }}
                />
                Compress for Discord (smaller 480p file, fits the 10&nbsp;MB limit)
              </label>
            )}
            <label className="watchmods-compress">
              <input
                type="checkbox"
                checked={widescreen}
                onChange={(e) => { playSound('boop'); setWidescreen(e.target.checked) }}
              />
              Widescreen (16:9)
            </label>
            <label className="watchmods-compress" title="Mutes the stage and menu music; sound effects, voices and the announcer stay">
              <input
                type="checkbox"
                checked={noMusic}
                onChange={(e) => { playSound('boop'); setNoMusic(e.target.checked) }}
              />
              No music
            </label>
            <label className="watchmods-compress">
              <input
                type="checkbox"
                checked={anonymize}
                onChange={(e) => { playSound('boop'); setAnonymize(e.target.checked) }}
              />
              Hide player names (anonymize)
            </label>

            {job?.last_recording && (
              <p className="watchmods-saved">
                Recording saved.{' '}
                <button
                  className="watchmods-link"
                  onClick={() => api.post('/api/nucleome/watch-mods/reveal-recording',
                    { path: job.last_recording }).catch(() => {})}
                >
                  Show in folder
                </button>
              </p>
            )}

            <div className="watchmods-actions">
              {/* The purchase-intent moment: free users browse the whole
                  modal, pick skins, and meet Patreon exactly here. */}
              <PremiumActionButton
                className="watchmods-start"
                onClick={start}
                disabled={!options.playback_ready || !options.vanilla_iso}
              >
                {anyPicked ? 'Build & watch' : 'Watch'}
              </PremiumActionButton>
              <button
                className="watchmods-link"
                onMouseEnter={playHoverSound}
                onClick={() => api.post('/api/nucleome/replays/reveal',
                  { path: game.path }).catch(() => {})}
              >
                Show .slp in folder
              </button>
            </div>
            <p className="watchmods-eta">
              {anyPicked ? 'Building takes a couple of minutes.'
                : 'Plays the replay right away.'}
            </p>
          </>
        )}

        {part === 'watch' && <WatchPlayback playback={playback} />}

        {part === 'failed' && (
          <div className="watchmods-progress">
            <p className="watchmods-warn">{job.error || 'The watch stopped when Nucleus closed.'}</p>
            <button className="watchmods-start" onMouseEnter={playHoverSound}
                    onClick={dismiss}>
              Back
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
