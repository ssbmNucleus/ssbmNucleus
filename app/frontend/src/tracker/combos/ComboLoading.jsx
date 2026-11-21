import ComboLibraryStatus from './ComboLibraryStatus'
import './CombosPage.css'
import '../../shared/ui/IconSelect.css'
import '../../shared/ui/FilterSelect.css'

function FilterShell({ label, compact = false }) {
  return <div className={`icon-select${compact ? ' filter-select' : ''}`}>
    <button className="icon-select-button" disabled>
      <span className="icon-select-label">{label}</span><span className="icon-select-caret">▾</span>
    </button>
  </div>
}

// The lazy page's first paint already has the controls' normal geometry.
// No replay/player dependencies or requests are needed for this small shell.
export default function ComboLoading() {
  return <div className="combos-page combos-loading" aria-busy="true">
    <ComboLibraryStatus />
    <div className="combos-filters">
      <div className="combos-direction">
        <button className="combos-dir-btn active" disabled>My combos</button>
        <button className="combos-dir-btn" disabled>On me</button>
      </div>
      {['Me: any character', 'Vs: any character', 'Any stage'].map(label => <FilterShell key={label} label={label} />)}
      {['4+ moves', '50%+', 'Any start %', 'Combos & strings'].map(label => <FilterShell key={label} label={label} compact />)}
      <button className="combos-kills" disabled>Kills only</button>
      <form className="combos-opponent-search"><input placeholder="Opponent name or code…" disabled /></form>
      <div className="combos-sort" role="group" aria-label="Sort combos by">
        <span className="combos-sort-label">Sort:</span>
        {['Recent', 'Damage', 'Moves', 'Start %', 'Length'].map((label, i) =>
          <button key={label} className={`combos-sort-btn${i === 0 ? ' active' : ''}`} disabled>
            {label}{i === 0 && <span className="combos-sort-arrow">↓</span>}
          </button>)}
      </div>
      <span className="combos-count">Loading combos…</span>
      <div className="combos-playall-group">
        <button className="combos-playall" disabled>▶ Play</button>
        <input className="combos-playcount" type="number" value={25} readOnly disabled />
        <span className="combos-playall-suffix">combos</span>
      </div>
    </div>
    <div className="combos-list"><p className="combos-none" role="status">Loading combos…</p></div>
  </div>
}
