import { num, pct, playtimeLabel } from './statsHelpers'

// Editorial career line: the headline numbers read as one typeset row of
// value + quiet label, split by hairline dividers — a boxscore, not a wall of
// identical KPI chips. Winrate carries the one status color; the split, days,
// and session pace drop to a muted caption below.
function Stat({ value, label, cls = '' }) {
  return (
    <span className="stats-stat">
      <span className={`stats-stat-num ${cls}`}>{value}</span>
      <span className="stats-stat-label">{label}</span>
    </span>
  )
}

export function StatLine({ o, sessions }) {
  const wrCls = o.winrate == null ? '' : o.winrate >= 0.5 ? 'is-up' : 'is-down'
  return (
    <div className="stats-statline">
      <Stat value={num(o.games)} label="games" />
      <span className="stats-stat-div" />
      <Stat value={pct(o.winrate)} label="won" cls={wrCls} />
      <span className="stats-stat-div" />
      <Stat value={playtimeLabel(o.playtime_s)} label="played" />
      <span className="stats-stat-div" />
      <Stat value={num(o.opponents)} label="opponents" />
      <span className="stats-stat-div" />
      <Stat value={num(sessions.count)} label="sessions" />
    </div>
  )
}

export function StatLineCaption({ o, sessions }) {
  const bits = [
    o.active_days ? `${num(o.active_days)} days played` : null,
    sessions.avg_games ? `~${sessions.avg_games} games each session` : null,
  ].filter(Boolean)
  return (
    <p className="stats-statline-caption">
      <span className="is-up">{num(o.wins)}</span> wins,{' '}
      <span className="is-down">{num(o.losses)}</span> losses
      {bits.map((b) => <span key={b}> · {b}</span>)}
    </p>
  )
}

// Thin winrate meter: fill from 0 to winrate, tick at the 50% break-even
// line. Green at/above 50, red below — win/loss is a genuine status color.
export function WinBar({ winrate, games }) {
  if (winrate == null || !games) {
    return <div className="stats-winbar stats-winbar--empty" />
  }
  const cls = winrate >= 0.5 ? 'is-up' : 'is-down'
  return (
    <div className="stats-winbar">
      <div className={`stats-winbar-fill ${cls}`} style={{ width: `${winrate * 100}%` }} />
      <div className="stats-winbar-mid" />
    </div>
  )
}

export function Section({ title, sub, children, wide, fill }) {
  const cls = [
    'stats-section',
    wide && 'stats-section--wide',
    fill && 'stats-section--fill',
  ].filter(Boolean).join(' ')
  return (
    <section className={cls}>
      <header className="stats-section-head">
        <h3>{title}</h3>
        {sub && <span>{sub}</span>}
      </header>
      {children}
    </section>
  )
}
