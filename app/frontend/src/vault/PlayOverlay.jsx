/**
 * PlayOverlay - progress / error / launched card for the vault "Play"
 * action. Rendered by StorageViewer while a play is in flight.
 * Styles live in patches/PatchesGrid.css (.play-overlay, .vault-play-card ...).
 */
export default function PlayOverlay({
  playPercent, playMessage, playError, playLaunched, dismissPlay, doneText = 'Launched — switch to Dolphin!',
}) {
  return (
    <div className="play-overlay" onClick={(playError || playLaunched) ? dismissPlay : undefined}>
      <div className="vault-play-card" onClick={(e) => e.stopPropagation()}>
        {playError ? (
          <>
            <div className="play-icon error">âœ•</div>
            <p className="play-card-msg">{playError}</p>
            <button className="btn-secondary" onClick={dismissPlay}>Close</button>
          </>
        ) : playLaunched ? (
          <>
            <p className="play-card-msg">{doneText}</p>
            {doneText !== 'Launched — switch to Dolphin!' && (
              <button className="btn-secondary" onClick={dismissPlay}>Close</button>
            )}
          </>
        ) : (
          <>
            <div className="play-spinner" />
            <p className="play-card-msg">{playMessage}</p>
            <div className="play-bar"><div className="play-bar-fill" style={{ width: `${playPercent}%` }} /></div>
            <p className="play-card-pct">{playPercent}%</p>
          </>
        )}
      </div>
    </div>
  )
}
