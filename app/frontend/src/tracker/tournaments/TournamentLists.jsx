import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { ordinal, scoreLabel } from './tournamentMath'
import { DeltaBadge, Pager, placeClass, shortDate, usePager } from './tournamentShared'

// Every recent event as one boxscore line; click to load that run.
const EVENTS_PAGE = 12

export function EventList({ rows: allRows, selectedKey, onSelect }) {
  const { rows, page, pages, setPage } = usePager(allRows, EVENTS_PAGE)
  return (
    <div className="stats-rows">
      {rows.map((r) => (
        <button
          type="button"
          className={`tg-event${r.key === selectedKey ? ' is-active' : ''}${r.run ? '' : ' tg-event--flat'}`}
          key={r.key}
          onMouseEnter={playHoverSound}
          onClick={r.run ? () => { playSound('boop'); onSelect(r.key) } : undefined}
          title={r.eventName || undefined}
        >
          <span className="tg-event-date">{shortDate(r.at)}</span>
          <span className="tg-event-name">{r.name}</span>
          <DeltaBadge delta={r.delta} />
          <span className={`tg-event-place ${placeClass(r.placement)}`}>
            {ordinal(r.placement)}
            {r.entrants != null && <small>/{r.entrants}</small>}
          </span>
        </button>
      ))}
      <Pager page={page} pages={pages} onPage={setPage} />
    </div>
  )
}

// Seed vs bracket: one diverging bar per event — up/green = you out-placed
// your seed (in ladder tiers), down/red = you under-placed it.
export function TrajectoryChart({ series }) {
  const maxAbs = Math.max(1, ...series.map((ev) => Math.abs(ev.delta)))
  let lastYear = null
  return (
    <>
      <div className="tg-traj">
        <div className="tg-traj-mid"><span>your seed</span></div>
        {series.map((ev) => {
          const year = new Date(ev.lastAt * 1000).getFullYear()
          const showYear = year !== lastYear
          lastYear = year
          const h = Math.max(4, (Math.abs(ev.delta) / maxAbs) * 50)
          return (
            <div
              className="tg-traj-col" key={ev.key}
              title={`${ev.event.tournament || ev.event.name} — seeded ${ev.seed ?? '?'}, placed ${ordinal(ev.placement)} of ${ev.event.entrants ?? '?'}`}
            >
              <div
                className={`tg-traj-bar ${ev.delta >= 0 ? 'is-up' : 'is-down'}`}
                style={{ height: `${ev.delta === 0 ? 2 : h}%` }}
              />
              {showYear && <span className="tg-traj-year">{year}</span>}
            </div>
          )
        })}
      </div>
      <p className="stats-footnote">
        Each bar is one event: how far above (green) or below (red) your seed
        you finished, measured in bracket tiers — the honest version of
        &ldquo;am I actually improving?&rdquo;.
      </p>
    </>
  )
}

// Rows are buttons: clicking a demon opens the whole head-to-head history
// (every set, with any matched replays playable); clicking a best win opens
// that set. The set-detail sheet handles the replay lookup.
const H2H_PAGE = 6

export function DemonRows({ list, onOpenSets }) {
  const { rows, page, pages, setPage } = usePager(list, H2H_PAGE)
  if (!list.length) {
    return <p className="stats-footnote">Nobody has a winning record on you (2+ sets). Keep it that way.</p>
  }
  return (
    <div className="stats-rows">
      {rows.map((r) => (
        <button
          type="button" className="stats-row tg-row-btn" key={r.key}
          onMouseEnter={playHoverSound}
          onClick={() => {
            playSound('boop')
            onOpenSets({ title: `vs ${r.name}`, subtitle: `${r.wins}–${r.losses} lifetime`, sets: r.sets })
          }}
        >
          <span className="stats-row-name">{r.name}</span>
          <span className="tg-h2h">
            <span className="is-down">{r.losses}</span>–<span className="is-up">{r.wins}</span>
          </span>
          <span className="tg-h2h-note">
            {r.wins === 0 ? 'never beaten' : `last ${shortDate(r.lastAt)}`}
          </span>
        </button>
      ))}
      <Pager page={page} pages={pages} onPage={setPage} />
    </div>
  )
}

export function BestWinRows({ list, onOpenSets }) {
  const { rows, page, pages, setPage } = usePager(list, H2H_PAGE)
  if (!list.length) {
    return <p className="stats-footnote">No seed upsets synced yet — go steal a bracket spot.</p>
  }
  return (
    <div className="stats-rows">
      {rows.map((s) => (
        <button
          type="button" className="stats-row tg-row-btn" key={s.id}
          onMouseEnter={playHoverSound}
          onClick={() => {
            playSound('boop')
            onOpenSets({
              title: `${s.round_text || 'Set'} vs ${s.opp.name}`,
              subtitle: s.eventInfo.tournament || s.eventInfo.name,
              sets: [s],
            })
          }}
        >
          <span className="tg-badge tg-badge--up" title={`Upset factor ${s.uf}`}>UF {s.uf}</span>
          <span className="stats-row-name">
            {s.opp.name}
            {s.opp.seed != null && <small className="tg-muted"> seed {s.opp.seed}</small>}
          </span>
          <span className="tg-h2h-note">{s.eventInfo.tournament || s.eventInfo.name}</span>
          <span className="tg-set-score">{scoreLabel(s)}</span>
        </button>
      ))}
      <Pager page={page} pages={pages} onPage={setPage} />
    </div>
  )
}
