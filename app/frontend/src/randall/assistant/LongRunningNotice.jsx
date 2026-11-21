import { showLongRunningNotice } from './transcript'
import { taskProgress } from './taskEnvelope'
import { activityLabel } from './activity'
import { ProgressCard } from './TaskCards'
import { useNow } from './clock'

// What a long task tells the user while it runs.
//
// It used to say "Randall will keep working and using AI credit until the task
// finishes or you stop it" -- a sentence with no stage, no elapsed time, no
// number and no boundary, which is anxiety rather than information. It now
// shows the stage it is actually on, how long that has taken, the spend
// reported so far, the limit Randall stops at, and Stop.
//
// It renders from the Session-1 envelope (`state`, `facts.stage_label`,
// `waiting_reason`) where a tool result carries one, and degrades to the
// activity vocabulary and the engine's own `started_at`/`model_rounds` where it
// does not. Nothing here invents an estimate: `estimate_seconds` is shown only
// if the backend sends it.
export default function LongRunningNotice({ message, onStop, stopping }) {
  // Also appears during one slow model/tool call; no server event is needed
  // at the threshold. The saved timestamp restores it after reopening chat.
  // The shared one-second tick: the import card above counts the same seconds.
  const now = useNow(Boolean(message) && message.status === 'running')

  if (!showLongRunningNotice(message, now)) return null
  const progress = taskProgress(message, now)
  const waiting = progress?.state === 'waiting_decision' || progress?.state === 'waiting_approval'
  return <ProgressCard
    title={progress?.stage || activityLabel(progress?.tool) || 'Still working'}
    progress={{ ...progress,
      stage: progress?.stage || (progress?.tool ? activityLabel(progress.tool) : 'Still working'),
      waitingReason: progress?.waitingReason || (waiting ? 'Waiting for your answer' : null) }}
    onStop={onStop} stopping={stopping} compact />
}
