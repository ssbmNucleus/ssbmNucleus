import { useContext, useMemo, useState } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { TipCtx, TipCard } from './StatsTooltip'
import { WinBar } from './StatsBlocks'
import { API, num, pct, shortDate } from './statsHelpers'

// ── sortable column headers (shared by all row sections) ──

function sortRows(entries, sort) {
  return [...entries].sort((a, b) => {
    const av = a[sort.key], bv = b[sort.key]
    if (av == null && bv == null) return b.games - a.games
    if (av == null) return 1  // no-data rows always sink to the bottom
    if (bv == null) return -1
    const base = av < bv ? 1 : av > bv ? -1 : 0
    return sort.dir * base || b.games - a.games
  })
}

function useSort(defaultKey = 'games') {
  const [sort, setSort] = useState({ key: defaultKey, dir: 1 }) // dir 1 = desc
  const toggle = (key) => {
    playSound('boop')
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }))
  }
  return [sort, toggle]
}

function SortLabel({ label, k, sort, onSort, className = '' }) {
  const active = sort.key === k
  return (
    <button className={`stats-sort ${className} ${active ? 'is-active' : ''}`}
            onMouseEnter={playHoverSound} onClick={() => onSort(k)}>
      {label}{active ? (sort.dir > 0 ? ' ▾' : ' ▴') : ''}
    </button>
  )
}

// Shared row shape for matchups / stages: icon, name, games count, winrate
// meter, winrate figure. Click a column header to re-sort. `defaultFilter`
// limits the collapsed view (e.g. legal stages only); the full list stays
// one "Show all" away.
//
// When `filterId` (e -> id) is passed the rows also get interactive filtering:
// a hover "×" hides individual entries, and a `tierPreset` ({label, ids})
// renders a toggle that keeps only ids in that set (used to pin the matchup
// list to top tiers). Stages omit these props and behave exactly as before.
export function BreakdownRows({ entries, icon, label, initial = 12,
                         defaultFilter = null, filterId = null,
                         tierPreset = null }) {
  const [showAll, setShowAll] = useState(false)
  const [sort, toggleSort] = useSort('winrate')
  const [excluded, setExcluded] = useState(() => new Set())
  // matchups default to the top-tier view; stages have no preset so this is off
  const [tierOnly, setTierOnly] = useState(() => !!tierPreset)
  const tip = useContext(TipCtx)

  const filterable = !!filterId
  // full id -> entry map so hidden entries can still render restore chips
  const byId = useMemo(() => {
    if (!filterable) return null
    const m = new Map()
    entries.forEach((e) => m.set(filterId(e), e))
    return m
  }, [entries, filterId, filterable])

  const kept = filterable
    ? entries.filter((e) => {
        const id = filterId(e)
        if (excluded.has(id)) return false
        if (tierOnly && tierPreset && !tierPreset.ids.has(id)) return false
        return true
      })
    : entries

  const sorted = sortRows(kept, sort)
  const shortlist = defaultFilter ? sorted.filter(defaultFilter) : sorted
  // filterable lists (matchups) always show every kept row — the tier toggle
  // and hide chips are the filter. Others keep the "Show all" collapse.
  const visible = filterable ? sorted : (showAll ? sorted : shortlist.slice(0, initial))
  const rowTip = (e) => TipCard({
    title: label(e),
    icon: icon(e),
    rows: [
      ['Games', num(e.games)],
      ['Record', `${num(e.wins)}W – ${num(e.losses)}L`],
      ['Winrate', pct(e.winrate)],
      e.games > e.wins + e.losses
        && ['Unscored', num(e.games - e.wins - e.losses)],
    ],
  })

  const hide = (id) => {
    playSound('boop')
    setExcluded((s) => new Set(s).add(id))
  }
  const restore = (id) => {
    playSound('boop')
    setExcluded((s) => { const n = new Set(s); n.delete(id); return n })
  }
  const hiddenIds = [...excluded].filter((id) => byId?.has(id))

  return (
    <div className="stats-rows">
      {filterable && (tierPreset || hiddenIds.length > 0) && (
        <div className="stats-filterbar">
          {tierPreset && (
            <button
              type="button"
              className={`stats-filter-btn ${tierOnly ? 'is-active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); setTierOnly((v) => !v) }}
            >
              {tierOnly ? 'Show all characters' : tierPreset.label}
            </button>
          )}
          {hiddenIds.map((id) => {
            const e = byId.get(id)
            return (
              <button
                type="button" className="stats-filter-chip" key={`hide${id}`}
                onMouseEnter={playHoverSound} onClick={() => restore(id)}
                title="Show again"
              >
                <img src={icon(e)} alt="" />
                <span>{label(e)}</span>
                <span className="stats-filter-chip-x">+</span>
              </button>
            )
          })}
        </div>
      )}
      <div className="stats-rows-head">
        <span className="stats-head-name" />
        <SortLabel label="games" k="games" sort={sort} onSort={toggleSort} className="stats-head-games" />
        <span className="stats-head-bar" />
        <SortLabel label="winrate" k="winrate" sort={sort} onSort={toggleSort} className="stats-head-rate" />
      </div>
      {visible.map((e) => (
        <div className={`stats-row ${filterable ? 'stats-row--filterable' : ''}`} key={label(e)}
             onMouseMove={(ev) => tip.move(ev, rowTip(e))}
             onMouseLeave={tip.hide}>
          <img className="stats-row-icon" src={icon(e)} alt="" loading="lazy"
               onError={(ev) => { ev.target.style.visibility = 'hidden' }} />
          <span className="stats-row-name">{label(e)}</span>
          <span className="stats-row-games">{num(e.games)}</span>
          <WinBar winrate={e.winrate} games={e.wins + e.losses} />
          <span className={`stats-row-rate ${e.winrate == null ? '' : e.winrate >= 0.5 ? 'is-up' : 'is-down'}`}>
            {pct(e.winrate)}
          </span>
          {filterable && (
            <button
              type="button" className="stats-row-hide"
              onClick={() => hide(filterId(e))}
              title={`Hide ${label(e)}`}
            >×</button>
          )}
        </div>
      ))}
      {!filterable && (shortlist.length > visible.length || showAll) ? (
        <button className="stats-show-all" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setShowAll((s) => !s) }}>
          {showAll ? 'Show fewer' : `Show all ${sorted.length}`}
        </button>
      ) : null}
    </div>
  )
}

// Rivals list with its own sortable columns (last played / games / winrate)
// and a paginated tail — the backend sends everyone with 5+ games.
const RIVALS_PAGE = 20

export function RivalRows({ rivals }) {
  // always ordered by games played (backend sends them that way) — no
  // reordering, so a 5-0 stomp never jumps above a real head-to-head
  const [shown, setShown] = useState(RIVALS_PAGE)
  const tip = useContext(TipCtx)
  if (!rivals.length) return <p className="stats-footnote">No named opponents yet.</p>
  const sorted = rivals.slice(0, shown)
  const rowTip = (r) => TipCard({
    title: r.name ? `${r.name} (${r.code})` : r.code,
    icon: r.top_char != null ? `${API}/stock/${r.top_char}/0` : null,
    rows: [
      ['Games', num(r.games)],
      ['Record', `${num(r.wins)}W – ${num(r.losses)}L`],
      ['Winrate', pct(r.winrate)],
      ['Last played', shortDate(r.last_at)],
      r.quits > 0 && ['Their early quits', num(r.quits)],
    ],
  })
  return (
    <div className="stats-rows">
      <div className="stats-rows-head">
        <span className="stats-head-name" />
        <span className="stats-head-last">last played</span>
        <span className="stats-head-games">games</span>
        <span className="stats-head-bar" />
        <span className="stats-head-rate">winrate</span>
      </div>
      {sorted.map((r) => (
        <div className="stats-row stats-row--rival" key={r.code}
             onMouseMove={(ev) => tip.move(ev, rowTip(r))}
             onMouseLeave={tip.hide}>
          {r.top_char != null && (
            <img className="stats-row-icon" src={`${API}/stock/${r.top_char}/0`} alt=""
                 loading="lazy" onError={(ev) => { ev.target.style.visibility = 'hidden' }} />
          )}
          <span className="stats-row-name">
            {r.name || r.code}
            <span className="stats-rival-code">{r.code}</span>
          </span>
          <span className="stats-rival-last">{shortDate(r.last_at)}</span>
          <span className="stats-row-games">{num(r.games)}</span>
          <WinBar winrate={r.winrate} games={r.wins + r.losses} />
          <span className={`stats-row-rate ${r.winrate == null ? '' : r.winrate >= 0.5 ? 'is-up' : 'is-down'}`}>
            {pct(r.winrate)}
          </span>
        </div>
      ))}
      {shown < rivals.length && (
        <button className="stats-show-all" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setShown((n) => n + RIVALS_PAGE) }}>
          Show more ({(rivals.length - shown).toLocaleString()} more)
        </button>
      )}
    </div>
  )
}

// One salt column (Saltiest / Ragebaiters): opponents ranked by rage-quit
// count, with a magnitude bar. The tooltip shows BOTH quit directions.
// `shown` is owned by the parent so one button expands both columns together.
const SALT_PAGE = 8

function SaltList({ people, empty, shown }) {
  const tip = useContext(TipCtx)
  if (!people.length) return <p className="stats-footnote">{empty}</p>
  const rows = people.slice(0, shown)
  return (
    <div className="stats-rows">
      {rows.map((r) => (
        <div className="stats-row" key={r.code}
             onMouseMove={(ev) => tip.move(ev, TipCard({
               title: r.name ? `${r.name} (${r.code})` : r.code,
               icon: r.top_char != null ? `${API}/stock/${r.top_char}/0` : null,
               rows: [
                 ['They quit on you', `${num(r.opp_quits)}×`],
                 ['You quit on them', `${num(r.my_quits)}×`],
                 ['Games together', num(r.games)],
                 ['Your record', `${num(r.wins)}W – ${num(r.losses)}L`],
                 ['Your winrate', pct(r.winrate)],
               ],
             }))}
             onMouseLeave={tip.hide}>
          {r.top_char != null && (
            <img className="stats-row-icon" src={`${API}/stock/${r.top_char}/0`} alt=""
                 loading="lazy" onError={(ev) => { ev.target.style.visibility = 'hidden' }} />
          )}
          <span className="stats-row-name">
            {r.name || r.code}
            <span className="stats-rival-code">{r.code}</span>
          </span>
          <span className="stats-salt-count">{num(r.quits)}×</span>
          <WinBar winrate={r.winrate} games={r.wins + r.losses} />
          <span className={`stats-row-rate ${r.winrate == null ? '' : r.winrate >= 0.5 ? 'is-up' : 'is-down'}`}>
            {pct(r.winrate)}
          </span>
        </div>
      ))}
    </div>
  )
}

// Two salt columns side by side; one shared "Show more" expands both so
// the rankings stay row-aligned.
export function SaltReport({ salt }) {
  const [shown, setShown] = useState(SALT_PAGE)
  const maxLen = Math.max(salt.saltiest.length, salt.ragebaiters.length)
  return (
    <>
      <div className="stats-salt-cols">
        <div className="stats-salt-col">
          <div className="stats-salt-col-head">
            <h4>Saltiest opponents</h4>
            <span>quit on you {num(salt.opp_quits)}× total</span>
          </div>
          <SaltList people={salt.saltiest} shown={shown}
                    empty="Nobody's rage-quit on you. Suspicious." />
        </div>
        <div className="stats-salt-col">
          <div className="stats-salt-col-head">
            <h4>Biggest ragebaiters</h4>
            <span>made you quit {num(salt.my_quits)}× total</span>
          </div>
          <SaltList people={salt.ragebaiters} shown={shown}
                    empty="You've never rage-quit. Sure." />
        </div>
      </div>
      {shown < maxLen && (
        <button className="stats-show-all" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setShown((n) => n + SALT_PAGE) }}>
          Show more
        </button>
      )}
    </>
  )
}
