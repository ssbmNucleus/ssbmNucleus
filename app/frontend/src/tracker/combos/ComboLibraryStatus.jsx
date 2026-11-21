// Keep one header row mounted while library metadata arrives after the clips.
export default function ComboLibraryStatus({ identity, status, error, onScan, onRetry }) {
  const counts = status?.counts
  const scan = status?.scan
  const running = scan?.running
  const pending = counts?.games_pending || 0
  const needsScan = counts && counts.combos === 0 && counts.games_scanned === 0
  const complete = !!counts && !running && !pending && !needsScan
  let message = 'Loading library details…'
  if (error) message = 'Some library details could not load.'
  else if (running) message = `Analyzing… ${(scan.done || 0).toLocaleString()}${scan.total ? ` / ${scan.total.toLocaleString()}` : ''} games${scan.found ? ` — ${scan.found.toLocaleString()} combos with 4+ moves found` : ''}`
  else if (scan?.error) message = `Analysis failed: ${scan.error}`
  else if (needsScan && identity) message = identity.index?.parsed ? 'Your replays are ready to analyze.' : 'Scan your replays in the Replays tab first.'
  else if (pending) message = `${pending.toLocaleString()} game${pending === 1 ? '' : 's'} not analyzed yet.`
  else if (counts) message = `Analysis complete. ${(counts.combos || 0).toLocaleString()} combos with 4+ moves across your library.`
  return (
    <div className="combos-library-status" role="status" aria-live="polite">
      <div className="combos-library-progress" aria-hidden="true"
           style={{ width: running ? `${scan.total ? Math.min(100, 100 * scan.done / scan.total) : 100}%` : '0%' }} />
      <span className="combos-library-message">{message}</span>
      {error ? <button className="combos-pending-btn" onClick={onRetry}>Retry details</button>
        : !complete && <button className="combos-pending-btn" onClick={onScan}
                  disabled={!!running || !counts || !identity?.index?.parsed || (!pending && !needsScan)}>
          {running ? 'Analyzing…' : needsScan ? 'Scan combos' : 'Analyze now'}
        </button>}
    </div>
  )
}
