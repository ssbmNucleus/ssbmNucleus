import { useEffect, useRef, useState } from 'react'
import { api } from '../../shared/transport/api'
import { InGameTestRunning } from '../../shared/viewer/InGameTestPanel'
import { observeGameTest } from './gameTestSession'
import { ResultCard } from './TaskCards'
import { verificationResult } from './taskEnvelope'
import WorkbenchGameTest from './WorkbenchGameTest'

/** `layout="workbench"` is the In game tab's own presentation; the session it observes is the same. */
export default function GameTestCard({ tool, chatId, visible, live, layout }) {
  const game = tool.result?.game_test
  const [state, setState] = useState({ snapshot: null, stopping: false })
  const monitor = useRef(null)
  useEffect(() => {
    setState({ snapshot: null, stopping: false })
    if (!game?.session_id || !chatId || !live) return undefined
    const url = `/api/assistant/chats/${chatId}/game-tests/${game.session_id}`
    const session = observeGameTest({
      read: signal => api.get(url, { signal }),
      stop: signal => api.delete(url, undefined, { signal }),
      onState: patch => setState(previous => ({ ...previous, ...patch })),
    })
    monitor.current = session
    return () => { session.dispose(); monitor.current = null }
  }, [game?.session_id, chatId, live])
  return <GameTestView tool={tool} visible={visible} live={live} layout={layout} state={state} onStop={() => monitor.current?.stop()} />
}

export function GameTestView({ tool, visible, live, layout, state, onStop }) {
  const game = tool.result?.game_test
  if (tool.result?.error) return <p className="assistant-error" role="alert">{tool.result.error}</p>
  // The automated costume checks return `game_verification`, which this card
  // used to drop on the floor and report as "No game session was started".
  // They are a RESULT, and their scope (one costume, one slot, a throwaway test
  // build) is part of what they say.
  const verification = verificationResult(tool.result)
  if (verification) return <ResultCard {...verification} />
  if (!game) return tool.result?.items ? <div className="assistant-tool">
    {tool.result.items.length ? <ul>{tool.result.items.map(item => <li key={`${item.kind}:${item.slug || `${item.stage_code}:${item.variant_id}`}`}>{item.name}</li>)}</ul>
      : <p>No matching custom characters or stages.</p>}
  </div> : <p role="status">{tool.status === 'running' ? 'Getting the game ready…' : tool.result?.note || 'No game was started.'}</p>
  // An older session keeps its own outcome instead of collapsing to a label:
  // playing it yourself is not an automatic check, and the card says which.
  if (!live) return <div className="assistant-test-receipt">
    <strong>You played this yourself: {game.label}</strong>
    <p className="assistant-task-scope">Trying it by hand is not the automatic movement check. Ask for those
      separately if you want them.</p>
    {game.outcome && <p>{game.outcome}</p>}
  </div>
  const snapshot = state.snapshot
  const previewActive = visible && (!!snapshot?.capture_session_id || snapshot?.capture_supported === false)
  if (layout === 'workbench') return <WorkbenchGameTest label={game.label} state={state} previewActive={previewActive}
    captureSessionId={snapshot?.capture_session_id} onStop={onStop} />
  const last = snapshot?.lastEvent
  const result = last?.event === 'test_complete' ? last.payload : null
  const failed = last?.event === 'test_error' ? last.payload.error : null
  return <section className="assistant-game-test" aria-label={`In-game test: ${game.label}`}>
    <strong>{game.label}</strong>
    {!snapshot && <p role="status">Connecting to in-game session…</p>}
    {snapshot?.running && <InGameTestRunning previewActive={previewActive}
      captureSessionId={snapshot.capture_session_id} test={{
        testStatus: snapshot.status || { stage: 'starting' }, testMode: 'test',
        testError: state.error, stoppingTest: state.stopping, stopError: state.stopError,
        stopTest: onStop,
      }} />}
    {(!snapshot || !snapshot.running) && state.error && <p role="alert">{state.error}</p>}
    {!snapshot && <button className="assistant-secondary" disabled={state.stopping}
      onClick={onStop}>{state.stopping ? 'Stopping…' : 'Stop'}</button>}
    {state.stopError && !snapshot?.running && <p role="alert">{state.stopError}</p>}
    {failed && <p role="alert">{failed}</p>}
    {result && <p>{result.success ? 'Play session ended.' : 'Play session failed.'} {result.reason}</p>}
  </section>
}
