import DolphinEmbedPanel, { canCaptureDolphin, useDolphinCapture } from '../../shared/viewer/DolphinEmbedPanel'
import { captureCrop } from '../../shared/viewer/captureCrop'
import { gameTestPhase, gameTestTitle } from './gameTestView'

/** The In game tab: the game is the picture. A quiet title with one status
    pill and two small actions, then the live capture at Melee's 4:3 with
    Dolphin's own window frame cropped away, and one hint line under it.
    While the test build runs the same stage holds a calm progress bar; when
    the session ends, one muted line. The session itself (start, Stop, the
    capture lease) is exactly the chat card's: GameTestCard owns it. */
export default function WorkbenchGameTest({ label, state, previewActive, captureSessionId, onStop }) {
  const phase = gameTestPhase(state)
  const capture = canCaptureDolphin()
  const showGame = phase.view === 'game' && previewActive
  const { videoRef, state: preview, popout } = useDolphinCapture({ active: showGame && capture, expectedSessionId: captureSessionId })
  const live = showGame && capture && preview.status === 'live'
  const crop = live ? captureCrop(preview.client) : null
  const stopping = phase.tone === 'stopping'
  return <section className={`workbench-game-test is-${phase.tone}`} aria-label={`In-game test: ${label}`}>
    <header className="workbench-game-head">
      <strong className="workbench-game-title" title={label}>{gameTestTitle(label)}</strong>
      <span className="workbench-game-pill" role="status"><i aria-hidden="true" />{phase.pill}</span>
      <span className="workbench-game-actions">
        {showGame && capture && <button type="button" className="workbench-game-action"
          onClick={popout} title="Play in Dolphin's own window">Open in Dolphin</button>}
        {phase.canStop && <button type="button" className="workbench-game-action" onClick={onStop}
          disabled={stopping}>{stopping ? 'Stopping…' : 'Stop'}</button>}
      </span>
    </header>
    {phase.view === 'ended' ? <p className="workbench-game-ended" role={phase.tone === 'failed' ? 'alert' : undefined}>{phase.line}</p>
      : <div className="workbench-game-fit">
        <div className="workbench-game-stage">
          {phase.view === 'progress' && <GameProgress phase={phase} />}
          {showGame && capture && <>
            <video ref={videoRef} muted playsInline className={crop ? 'is-cropped' : ''}
              style={{ ...(crop || {}), visibility: live ? 'visible' : 'hidden' }} />
            {!live && <p className="workbench-game-note">{preview.message}</p>}
          </>}
          {showGame && !capture && <div className="workbench-game-fallback">
            <DolphinEmbedPanel active fill expectedSessionId={captureSessionId} />
          </div>}
          {phase.view === 'game' && !previewActive && <p className="workbench-game-note">The game appears here once Dolphin boots…</p>}
        </div>
        {phase.view === 'game' && <p className="workbench-game-hint">{phase.line}</p>}
      </div>}
    {phase.problem && <p className="workbench-game-problem" role="alert">{phase.problem}</p>}
  </section>
}

function GameProgress({ phase }) {
  const known = phase.percent !== null
  return <div className="workbench-game-progress">
    <span className="workbench-game-spinner" aria-hidden="true" />
    <div className={`workbench-game-bar${known ? '' : ' is-indeterminate'}`} role="progressbar"
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={known ? phase.percent : undefined} aria-label="Preparing the game">
      <span style={known ? { width: `${Math.max(phase.percent, 4)}%` } : undefined} />
    </div>
    <p className="workbench-game-now"><span>{phase.line}</span>
      {known && <span className="workbench-game-percent">{phase.percent}%</span>}</p>
  </div>
}
