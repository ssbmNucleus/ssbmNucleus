// How the workbench's In game tab reads a play session: a quiet title, one
// status pill, and either the progress, the game, or one line saying it ended.
// Presentation only: what the session does is gameTestSession.js's business.

// Before these stages there is no Dolphin window to show (the same list the
// shared in-game panel uses to decide when to mount its preview).
const PREPARING = new Set(['starting', 'building', 'waiting', 'recovering'])

const cap = word => word ? word[0].toUpperCase() + word.slice(1) : word
const words = text => String(text || '').trim()
  .replace(/\b[a-z0-9]+(?:_+[a-z0-9]+)+\b/gi, name => name.split(/_+/).map(cap).join(' '))
// Backend progress lines end in "..." (build logs); the app writes an ellipsis.
const plain = text => words(text).replace(/\.{3}$/, '…')

/** "Young Link — Tung Tung Sahur" -> "Tung Tung Sahur · Young Link": the costume first, its fighter after. */
export function gameTestTitle(label) {
  const text = words(label)
  const [fighter, costume, ...rest] = text.split(' — ')
  if (!costume || rest.length || !fighter) return text
  return `${cap(costume)} · ${fighter}`
}

/** One reading of the session for the workbench: what the pill says, which body shows, and the one line under it. */
export function gameTestPhase({ snapshot, stopping = false, error = null, stopError = null } = {}) {
  const last = snapshot?.lastEvent
  const result = last?.event === 'test_complete' ? last.payload : null
  const failure = last?.event === 'test_error' ? last.payload?.error : null
  const problem = stopError || error || null
  if (!snapshot) return { tone: stopping ? 'stopping' : 'starting', pill: stopping ? 'Stopping…' : 'Starting…',
    view: 'progress', line: 'Connecting to the game…', percent: null, canStop: true, problem }
  if (!snapshot.running) {
    if (failure || (result && !result.success)) return { tone: 'failed', pill: 'Failed', view: 'ended',
      line: failure || ['Play session failed.', result?.reason].filter(Boolean).join(' '), canStop: false, problem: null }
    if (result) return { tone: 'ended', pill: 'Ended', view: 'ended', line: 'Play session ended.', canStop: false,
      problem: stopError || null }
    return { tone: 'ended', pill: 'Ended', view: 'ended', line: error || 'This game session is over.',
      canStop: false, problem: null }
  }
  const status = snapshot.status || { stage: 'starting' }
  const stage = status.stage || 'starting'
  const playing = stage === 'playing'
  const percent = !playing && Number.isFinite(status.percentage)
    ? Math.max(0, Math.min(100, Math.round(status.percentage))) : null
  return {
    tone: stopping ? 'stopping' : playing ? 'live' : 'starting',
    pill: stopping ? 'Stopping…' : playing ? 'Live' : 'Starting…',
    view: PREPARING.has(stage) ? 'progress' : 'game',
    line: playing ? `Playing on controller port ${status.controllerPort || 1}` : plain(status.message) || 'Getting the game ready…',
    percent, playing, canStop: true, problem,
  }
}
