import './StatsPage.css'

export default function StatsLoading({ error, onRetry }) {
  return <div className="stats-page stats-pending" aria-busy={!error}>
    <div className="stats-topbar" role={error ? 'alert' : 'status'}>
      <span>{error || 'Loading stats…'}</span>
      {error && <button className="stats-retry" onClick={onRetry}>Retry</button>}
    </div>
    <div aria-hidden="true" className="stats-pending-summary">
      {[0, 1, 2, 3].map(i => <div className="stats-placeholder" key={i} />)}
    </div>
    <div aria-hidden="true" className="stats-grid">
      {[0, 1, 2, 3].map(i => <div className="stats-placeholder stats-pending-card" key={i} />)}
    </div>
  </div>
}
