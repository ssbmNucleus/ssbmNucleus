import { useState } from 'react'
import { api } from '../../shared/transport/api'
import { gamesForMonth as loadGamesForMonth } from './tournamentReplays'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { matchReplaysToSets } from './tournamentMath'

// Shared by the Tournaments page and its sections: the API base, the local
// replay lookup, date/link helpers, and the small section/badge/pager widgets.

export const API = '/api/nucleome'

// ── local replay lookup ──
// One fetch per calendar month of local games, shared by every surface that
// wants to attach replays to sets (the run, best wins, demons, the bracket).
const gamesForMonth = (month, revision) => (
  loadGamesForMonth(api, `${API}/replays`, month, revision)
)

const ym = (ms) => {
  const d = new Date(ms)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export async function matchForSets(sets, revision = '') {
  // both the report month AND the month the games could fall in — a set
  // reported after midnight on the 1st has its games in the previous month
  const months = [...new Set(sets
    .filter((s) => s.completed_at)
    .flatMap((s) => [
      ym(s.completed_at * 1000),
      ym(s.completed_at * 1000 - 5 * 60 * 60 * 1000),
    ]))].slice(0, 8)
  if (!months.length) return new Map()
  const lists = await Promise.all(months.map((month) => gamesForMonth(month, revision)))
  // the two-month case can overlap in pathological indexes — dedupe by id
  const seen = new Set()
  const games = lists.flat().filter((g) => !seen.has(g.id) && seen.add(g.id))
  return matchReplaysToSets(sets, games)
}

export const openExternal = (url) => {
  if (window.electron?.openExternal) window.electron.openExternal(url)
  else window.open(url, '_blank')
}

export const shortDate = (unixSeconds) => {
  if (!unixSeconds) return '—'
  return new Date(unixSeconds * 1000).toLocaleDateString(undefined,
    { year: 'numeric', month: 'short', day: 'numeric' })
}

export function Section({ title, sub, children, wide }) {
  return (
    <section className={`stats-section${wide ? ' stats-section--wide' : ''}`}>
      <header className="stats-section-head">
        <h3>{title}</h3>
        {sub && <span>{sub}</span>}
      </header>
      {children}
    </section>
  )
}

// "+2 over seed" / "−1 under seed" / "on seed" — ladder tiers, not raw seeds
export function DeltaBadge({ delta }) {
  if (delta == null) return null
  if (delta === 0) return <span className="tg-delta tg-delta--even">on seed</span>
  const cls = delta > 0 ? 'tg-delta--up' : 'tg-delta--down'
  const text = delta > 0 ? `+${delta} over seed` : `−${Math.abs(delta)} under seed`
  return <span className={`tg-delta ${cls}`}>{text}</span>
}

// gold / silver / bronze accents for podium placements
export const placeClass = (p) => (p === 1 ? 'tg-place--gold' : p === 2 ? 'tg-place--silver'
  : p === 3 ? 'tg-place--bronze' : '')

// Shared compact pager: fixed page size, ‹ page/pages › — grinders have
// hundreds of events, so lists page instead of growing without bound.
export function usePager(items, perPage) {
  const [page, setPage] = useState(0)
  const pages = Math.max(1, Math.ceil(items.length / perPage))
  const current = Math.min(page, pages - 1) // clamp when the list shrinks
  return {
    rows: items.slice(current * perPage, (current + 1) * perPage),
    page: current,
    pages,
    setPage,
  }
}

export function Pager({ page, pages, onPage }) {
  if (pages <= 1) return null
  const go = (next) => { playSound('boop'); onPage(next) }
  return (
    <div className="tg-pager">
      <button type="button" disabled={page === 0} aria-label="Previous page"
              onMouseEnter={playHoverSound} onClick={() => go(page - 1)}>‹</button>
      <span>{page + 1} / {pages}</span>
      <button type="button" disabled={page >= pages - 1} aria-label="Next page"
              onMouseEnter={playHoverSound} onClick={() => go(page + 1)}>›</button>
    </div>
  )
}
