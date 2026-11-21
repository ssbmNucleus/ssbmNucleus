import { useEffect, useState } from 'react'
import { BACKEND_URL } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { markJobSeen, useJob, useJobList } from '../../shared/jobs/useJobs'
import DolphinEmbedPanel, { canCaptureDolphin, useDolphinCapture } from '../../shared/viewer/DolphinEmbedPanel'
import { captureCrop } from '../../shared/viewer/captureCrop'
import { currentWatch } from './watchJob'

const API = `${BACKEND_URL}/api/nucleome`

// The watch both popups show: the newest replay_watch job in the window's job
// store (watchJob.js), so a popup opened while a watch runs takes it over and
// a stale record never replaces a newer one. From the Start click until the
// new job's record arrives it is STARTING (busy), so the popup cannot be
// closed on a watch it has just started. `start` returns the route's answer.
export function useWatchJob() {
  const jobs = useJobList()
  const [pending, setPending] = useState(false)
  const [startedId, setStartedId] = useState(null)
  useJob(startedId) // asks for the record if its event has not come yet
  const job = currentWatch({ jobs, pending, startedId })

  const start = async (path, body) => {
    setPending(true)
    try {
      const data = await api.post(path, body)
      setStartedId(data?.job_id || null)
      return data
    } finally {
      setPending(false)
    }
  }
  // Back from a failed watch: the user has seen it.
  const dismiss = () => { if (job?.id) markJobSeen(job.id).catch(() => {}) }
  return { job, start, dismiss }
}

// Stop the watch `id` and only that one: a stale id stops nothing.
export function stopWatch(id) {
  if (!id) return Promise.resolve()
  return api.post('/api/nucleome/watch-mods/stop', { job_id: id }).catch(() => {})
}

// The playing state both Watch popups share (one replay, or a playlist):
// while Dolphin boots and plays, the popup is the game's window. The game is
// a live capture of the playback Dolphin (the same one as Test in game): once
// its first frame arrives its own windows, the seek bar's too, go behind the
// app, and Pop out gives them back. Without the capture the legacy overlay
// panel pins Dolphin's render window over the stage instead.
// The popup puts `modalClass` on its .watchmods-modal (the is-playing layout
// in ModsModal.css) and renders <WatchPlayback> while the job is busy. `job`
// is useWatchJob's.
export function useWatchPlayback(job) {
  const [popout, setPopout] = useState(false)
  // Off Windows the embed backend answers supported:false -- Dolphin plays in
  // its own desktop window, so pop out/in controls are meaningless.
  const [embedUnsupported, setEmbedUnsupported] = useState(false)
  const viewing = ['launching', 'playing'].includes(job?.state)
  const capture = canCaptureDolphin()
  const { videoRef, state: preview, popout: popoutCapture } = useDolphinCapture({
    active: capture && viewing && !popout && !!job?.capture_session_id,
    expectedSessionId: job?.capture_session_id || undefined })
  const wide = !!job?.widescreen
  const crop = preview.status === 'live' ? captureCrop(preview.client, wide ? 16 / 9 : 4 / 3) : null

  // a finished/stopped playback clears the popout state for the next watch
  useEffect(() => {
    if (job?.state !== 'playing' && popout) setPopout(false)
  }, [job?.state, popout])

  // Detach Dolphin into its own window / bring it back into the modal.
  const togglePopout = async () => {
    playSound('boop')
    const next = !popout
    if (capture) {
      // Pop out hands Dolphin's windows back where it opened them; bringing it
      // back in attaches a new capture, which puts them behind the app again.
      if (next) await popoutCapture()
      setPopout(next)
      return
    }
    // Legacy overlay: the backend flag must be set BEFORE the panel unmounts,
    // so the panel's cleanup park() no-ops instead of yanking the freshly
    // detached window offscreen.
    const data = await api.post(`/api/nucleome/watch-mods/window/${next ? 'popout' : 'popin'}`)
      .catch((e) => e.data || null)
    // Off Windows the backend can't pop windows in or out — don't flip the
    // button into a "Bring back into app" that no-ops forever.
    if (data && data.supported === false) {
      setEmbedUnsupported(true)
      return
    }
    setPopout(next)
  }

  return {
    job, viewing, popout, capture, videoRef, preview, crop,
    embedUnsupported, setEmbedUnsupported, togglePopout,
    modalClass: `${viewing ? 'is-playing' : ''} ${wide ? 'is-wide' : ''} ${popout ? 'is-popout' : ''}`,
  }
}

// The busy popup's body: the status line, Pop out / Stop while it plays, and
// the game under them. `children` (a recording batch's progress) show only
// while nothing plays: the playing layout sizes the game to fill all the room
// below the title and controls rows.
export function WatchPlayback({ playback, stopTitle, children }) {
  const { job, viewing, popout, capture, videoRef, preview, crop,
    embedUnsupported, setEmbedUnsupported, togglePopout } = playback

  const stopPlayback = () => {
    playSound('boop')
    stopWatch(job?.id)
  }

  return (
    <div className="watchmods-progress">
      {!viewing && <div className="watchmods-spinner" />}
      <p className="watchmods-detail">
        {popout && job?.state === 'playing'
          ? 'Playing in its own window.'
          : job?.detail || job?.state}
      </p>
      {job?.state === 'playing' && (
        <div className="watchmods-playctl">
          {!embedUnsupported && (
            <button className="watchmods-link" onMouseEnter={playHoverSound}
                    onClick={togglePopout}>
              {popout ? '⇤ Bring back into app' : '⇱ Pop out window'}
            </button>
          )}
          <button className="watchmods-link" onMouseEnter={playHoverSound}
                  onClick={stopPlayback} title={stopTitle}>
            ■ Stop
          </button>
        </div>
      )}
      {viewing && !popout && (
        <div className="watchmods-stage">
          {capture ? (
            <>
              <video ref={videoRef} muted playsInline
                     style={{ ...(crop || {}), visibility: preview.status === 'live' ? 'visible' : 'hidden' }} />
              {preview.status !== 'live' && (
                <p className="watchmods-stage-note">
                  {preview.message || 'The game appears here once Dolphin boots…'}
                </p>
              )}
            </>
          ) : (
            <DolphinEmbedPanel active fill windowApi={`${API}/watch-mods/window`}
                               onUnsupported={() => setEmbedUnsupported(true)} />
          )}
        </div>
      )}
      {!viewing && children}
    </div>
  )
}
