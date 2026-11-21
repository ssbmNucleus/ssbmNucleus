import { useEffect, useState } from 'react'
import { BACKEND_URL } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { charName, stageName } from '../../shared/data/meleeNames'
import GallerySelect from '../../shared/ui/GallerySelect'
import LiteButton, { PremiumActionButton } from '../lib/LiteGate'
import { WatchPlayback, stopWatch, useWatchJob, useWatchPlayback } from './WatchPlayback'
import { popupPart } from './watchJob'
import '../lib/ModsModal.css'

const API = `${BACKEND_URL}/api/nucleome`

const STOP_BATCH_TITLE = 'Stop after saving the game in progress; finished videos are kept'

// The playlist twin of WatchModsModal: instead of dressing the players of one
// replay, it picks ONE skin per character and ONE variant per stage across the
// whole filtered set of combos, builds a single stateless ISO that covers
// every clip, and plays them back-to-back. `clips` is
// [{game_id, start_frame, end_frame, full?}, …] (`full` = a whole game, the
// Replays tab's multi-select); `unit` names the items in the copy ('combo' |
// 'game'). Playback renders IN the popup (WatchPlayback, as for one replay);
// the watch is the same job (useWatchJob).
export default function PlaylistModsModal({ clips, title, unit = 'combo', onClose, onWatchLite }) {
  const [options, setOptions] = useState(null)
  const [charPicks, setCharPicks] = useState({})   // char id -> skin id ('' = vanilla)
  const [stagePicks, setStagePicks] = useState({}) // stage id -> variant id
  const [record, setRecord] = useState(false)
  const [compress, setCompress] = useState(false)
  const [widescreen, setWidescreen] = useState(false)
  const [noMusic, setNoMusic] = useState(false)
  const [recordDir, setRecordDir] = useState('')
  const [error, setError] = useState(null)
  const { job, start: startWatch, dismiss } = useWatchJob()

  useEffect(() => {
    api.post('/api/nucleome/watch-mods/playlist-options', { clips })
      .then((d) => setOptions(d))
      .catch(() => setError('Backend unavailable'))
    api.get('/api/nucleome/watch-mods/recording-dir')
      .then((d) => setRecordDir(d.dir || ''))
      .catch(() => {})
  }, [clips])

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
    try {
      await startWatch('/api/nucleome/watch-mods/playlist-start', {
        clips,
        char_selections: charPicks,
        stage_selections: stagePicks,
        record,
        compress: record && compress,
        widescreen,
        no_music: noMusic,
        // the folder shown in the popup is the one this recording writes to
        record_dir: record ? recordDir : undefined,
      })
    } catch (e) {
      setError(e.message || 'start failed')
    }
  }

  const characters = options?.characters || []
  const stageMods = (options?.stages || []).filter((s) => (s.mods || []).length > 0)
  const anyPicked = Object.values(charPicks).some(Boolean)
    || Object.values(stagePicks).some(Boolean)
  const clipCount = options?.clip_count ?? clips.length

  // A whole-game playlist records one video per game; `batch_total` is set
  // for such a batch (Stop ends it after saving the current game).
  const batchRunning = busy && (job?.batch_total || 0) > 0
  const perGame = unit === 'game'
  const stop = () => {
    playSound('back')
    stopWatch(job?.id)
  }

  // Closing while it plays ends playback (this popup IS the game's window).
  // The stop lands before the capture lets go, so the dying Dolphin's windows
  // are never handed back to the desktop.
  const closeModal = async () => {
    if (job?.state === 'playing' || batchRunning) await stopWatch(job.id)
    onClose()
  }

  const saved = job?.recordings || []

  return (
    <div className="watchmods-overlay" onClick={busy ? undefined : closeModal}>
      <div className={`watchmods-modal ${playback.modalClass}`}
           onClick={(e) => e.stopPropagation()}>
        <div className="watchmods-head">
          <h3>{title || 'Watch playlist'}</h3>
          <button className="watchmods-close" onMouseEnter={playHoverSound}
                  onClick={closeModal}
                  disabled={busy && job?.state !== 'playing' && !batchRunning}>×</button>
        </div>

        {part === 'loading' && <p className="watchmods-loading">Loading…</p>}
        {part === 'load-error' && <p className="watchmods-warn">{error}</p>}

        {part === 'form' && (
          <>
            <p className="watchmods-playlist-note">
              Playing {clipCount} {unit}{clipCount === 1 ? '' : 's'} back-to-back
              {unit === 'game' ? ', start to finish' : ''}.
              {perGame && ' Record to video to save each game as its own file.'}{' '}
              Pick a skin for any character or stage below — one ISO dresses the
              whole playlist.
            </p>
            <div className="watchmods-players">
              {stageMods.map((s) => (
                <div key={`stage-${s.stage}`} className="watchmods-player watchmods-stagerow">
                  <img className="watchmods-stageicon" alt=""
                       src={`${API}/stage-icon/${s.stage}`} />
                  <div className="watchmods-who">
                    <span className="watchmods-char">{stageName(s.stage)}</span>
                    <span className="watchmods-name">Stage</span>
                  </div>
                  <GallerySelect
                    value={stagePicks[s.stage] || ''}
                    onChange={(v) => setStagePicks((prev) => ({ ...prev, [s.stage]: v }))}
                    placeholder="Vanilla"
                    aspect="landscape"
                    searchPlaceholder="Search stage mods…"
                    options={s.mods.map((m) => ({
                      value: m.id,
                      label: m.name,
                      icon: m.screenshot ? `${BACKEND_URL}${m.screenshot}` : undefined,
                    }))}
                  />
                </div>
              ))}
              {characters.map((c) => (
                <div key={`char-${c.character}`} className="watchmods-player">
                  <img className="watchmods-stock" alt=""
                       src={`${API}/stock/${c.character}/${c.costumes?.[0] ?? 0}`} />
                  <div className="watchmods-who">
                    <span className="watchmods-char">{charName(c.character)}</span>
                    <span className="watchmods-name">
                      {c.costumes && c.costumes.length > 1
                        ? `${c.costumes.length} colors in playlist` : 'Character'}
                    </span>
                  </div>
                  {c.skins.length > 0 ? (
                    <GallerySelect
                      value={charPicks[c.character] || ''}
                      onChange={(v) => setCharPicks((prev) => ({ ...prev, [c.character]: v }))}
                      placeholder="Vanilla"
                      aspect="portrait"
                      searchPlaceholder="Search skins…"
                      options={c.skins.map((s) => ({
                        value: s.id,
                        label: s.name,
                        icon: `${BACKEND_URL}${s.csp}`,
                      }))}
                    />
                  ) : (
                    <span className="watchmods-noskins">No vault skins for {charName(c.character)}</span>
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
                  <span className="watchmods-record-label">
                    {perGame ? 'Each game saves to' : 'Saves to'}
                  </span>
                  <span className="watchmods-record-path" title={recordDir}>{recordDir}</span>
                  <button className="watchmods-link" onMouseEnter={playHoverSound}
                          onClick={chooseRecordDir}>Change…</button>
                </span>
              )}
            </div>
            {record && perGame && clipCount > 1 && (
              <p className="watchmods-record-note">
                {clipCount} separate videos, one per game, in the order they play.
              </p>
            )}
            {record && (
              <label className="watchmods-compress">
                <input
                  type="checkbox"
                  checked={compress}
                  onChange={(e) => { playSound('boop'); setCompress(e.target.checked) }}
                />
                {perGame
                  ? <>Compress for Discord (each game&apos;s video fits the 10&nbsp;MB limit)</>
                  : <>Compress for Discord (smaller 480p file, fits the 10&nbsp;MB limit)</>}
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

            {saved.length > 0 && (
              <p className="watchmods-saved">
                {saved.length > 1 ? `${saved.length} recordings saved.` : 'Recording saved.'}{' '}
                <button
                  className="watchmods-link"
                  onClick={() => api.post('/api/nucleome/watch-mods/reveal-recording',
                    { path: saved[saved.length - 1] }).catch(() => {})}
                >
                  Show in folder
                </button>
              </p>
            )}

            <div className="watchmods-actions">
              {onWatchLite && (
                <LiteButton
                  className="watchmods-lite"
                  onOpen={() => onWatchLite(clips)}
                  disabled={clipCount === 0}
                  title="Watch the playlist instantly in-app as character clips (no Dolphin, no skins)"
                >
                  ⚡ Watch Lite
                </LiteButton>
              )}
              <PremiumActionButton
                className="watchmods-start"
                onClick={start}
                disabled={!options.playback_ready || !options.vanilla_iso || clipCount === 0}
              >
                {anyPicked ? 'Build & watch' : 'Watch in Dolphin'}
              </PremiumActionButton>
            </div>
            <p className="watchmods-eta">
              {anyPicked ? 'Building one ISO for the whole playlist takes a couple of minutes.'
                : 'Watch Lite plays instantly; Dolphin gives full-quality with your skins.'}
            </p>
          </>
        )}

        {part === 'watch' && (
          <WatchPlayback playback={playback}
                         stopTitle={batchRunning ? STOP_BATCH_TITLE : undefined}>
            {batchRunning && (
              <p className="watchmods-batch">
                {saved.length} of {job.batch_total} saved
                <button className="watchmods-link" onMouseEnter={playHoverSound}
                        onClick={stop} title={STOP_BATCH_TITLE}>
                  Stop recording
                </button>
              </p>
            )}
          </WatchPlayback>
        )}

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
