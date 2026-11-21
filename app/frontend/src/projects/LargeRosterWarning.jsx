import { rosterRisk } from './rosterRisk'
import './LargeRosterWarning.css'

export default function LargeRosterWarning({ fighters, status = 'ready', additions = 0, showUnknown = false, onRetry }) {
  const { count, selected, projected, warn } = rosterRisk(status === 'ready' ? fighters : null, additions)
  if (count === null) {
    if (!showUnknown) return null
    return (
      <aside className="large-roster-warning large-roster-warning--unknown" aria-label="Slippi roster check">
        <strong>{status === 'loading' ? 'Checking roster size…' : 'Roster size unavailable'}</strong>
        <p>Slippi desyncs have been reported with rosters above 63 fighter entries. The current count could not yet be checked.</p>
        {status !== 'loading' && onRetry && <button type="button" onClick={onRetry}>Retry roster check</button>}
      </aside>
    )
  }
  if (!warn) return null
  return (
    <aside className="large-roster-warning" aria-label="Large roster Slippi warning">
      <strong>Large roster: Slippi desync risk</strong>
      <p>
        {selected > 0
          ? `Adding ${selected} selected character${selected === 1 ? '' : 's'} could bring this project from ${count} to ${projected} fighter entries.`
          : `This project has ${count} fighter entries.`}
        {' '}Rosters above 63 entries have been reported to cause intermittent grab and command-grab desyncs, even when the game builds and launches successfully.
      </p>
      <details>
        <summary>About this count and warning</summary>
        <p>The count includes partners, hidden fighters and reserved slots, so it is higher than the character-select roster. 63 is a reported risk threshold, not a proven limit or a guarantee that smaller rosters are safe. This online risk is separate from character-select memory and effect-table capacity.</p>
      </details>
    </aside>
  )
}
