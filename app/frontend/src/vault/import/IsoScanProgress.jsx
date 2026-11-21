import { useEffect, useState } from 'react'
import { scanProgressView, elapsedTime } from './isoScanProgressModel'
import HexagonLoader from '../../shared/ui/HexagonLoader'
import './IsoScanProgress.css'

export default function IsoScanProgress({ progress, isoPaths, startedAt, importing = false,
  count = 0, cancelling = false, cancelError, onCancel }) {
  const [now, setNow] = useState(Date.now)
  const [changedAt, setChangedAt] = useState(Date.now)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => { setChangedAt(Date.now()) },
    [progress.status, progress.percent, progress.current, progress.total, progress.message, progress.categories])
  const view = scanProgressView(progress,
    { importing, count, cancelling, quietFor: now - changedAt })
  const detail = cancelError || view.detail
  const source = isoPaths.length === 1 ? String(isoPaths[0]).split(/[\\/]/).pop() : `${isoPaths.length} ISOs`
  return <div className="iso-scan-progress" data-scan-progress="true">
    <header className="iso-progress-header">
      <p title={isoPaths.join('\n')}>{source}</p>
    </header>
    <div className="iso-progress-main">
      <div className="iso-progress-shine"
        role="progressbar" aria-label={view.title} aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={view.percent ?? undefined} aria-valuetext={[view.title, detail].filter(Boolean).join('. ')}>
        <HexagonLoader size={122} decorative progress={view.percent} minimumVisibleProgress={3}
          centerLabel={view.percent === null ? null : `${view.percent}%`} />
      </div>
      <div className="iso-progress-copy" aria-live="polite">
        <h2>{view.title}</h2>
        <p role={cancelError ? 'alert' : undefined}>{detail || '\u00a0'}</p>
      </div>
    </div>
    <footer className="iso-progress-footer">
      <span>{elapsedTime(now - startedAt)} <small>elapsed</small></span>
      {!importing && <button type="button" disabled={cancelling} onClick={onCancel}>
        {cancelling ? 'Stopping…' : 'Cancel'}
      </button>}
    </footer>
  </div>
}
