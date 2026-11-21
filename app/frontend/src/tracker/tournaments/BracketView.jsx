import { useMemo, useState } from 'react'

// In-app bracket: the event's sets laid out as winners/losers lanes of round
// columns, later rounds vertically centered so it reads as a real bracket
// tree. Your boxes get the accent edge; hovering any entrant lights up their
// whole path. Data is one on-demand fetch per event (see fetchStartggEventSets)
// — personal-use viewing of a bracket you played in, credited to start.gg.

// bracket identifiers run A..Z then AA..: shorter sorts first, then lexical
function idCmp(a, b) {
  const x = a || ''
  const y = b || ''
  return x.length - y.length || (x < y ? -1 : x > y ? 1 : 0)
}

function buildBlocks(sets) {
  const byPg = new Map()
  for (const s of sets) {
    const key = s.pg?.id ?? 0
    if (!byPg.has(key)) byPg.set(key, { pg: s.pg, sets: [] })
    byPg.get(key).sets.push(s)
  }
  const blocks = [...byPg.values()].sort((a, b) =>
    (a.pg?.order ?? 0) - (b.pg?.order ?? 0) || idCmp(a.pg?.label, b.pg?.label))
  return blocks.map(({ pg, sets: list }) => {
    const lanes = { winners: new Map(), losers: new Map() }
    for (const s of list) {
      const lane = (s.round ?? 0) < 0 ? lanes.losers : lanes.winners
      const r = Math.abs(s.round ?? 0)
      if (!lane.has(r)) lane.set(r, [])
      lane.get(r).push(s)
    }
    const columns = (lane) => [...lane.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([round, ss]) => ({
        round,
        title: ss[0].round_text || `Round ${round}`,
        sets: ss.slice().sort((x, y) => idCmp(x.identifier, y.identifier)),
      }))
    return { pg, winners: columns(lanes.winners), losers: columns(lanes.losers) }
  })
}

function SlotScore({ score }) {
  if (score === -1) return <span className="tgb-score tgb-score--dq">DQ</span>
  return <span className="tgb-score">{score ?? '–'}</span>
}

function BracketSet({ s, myEntrantId, hoverId, onHover, replays, onOpenSet }) {
  const mine = s.slots.some((sl) => sl.entrant_id != null && sl.entrant_id === myEntrantId)
  const watchable = mine && replays > 0 && onOpenSet
  const Tag = watchable ? 'button' : 'div'
  return (
    <Tag
      className={`tgb-set${mine ? ' tgb-set--mine' : ''}${watchable ? ' tgb-set--watch' : ''}`}
      {...(watchable ? {
        type: 'button',
        title: `${replays} local replay${replays > 1 ? 's' : ''} — click to watch this set`,
        onClick: () => onOpenSet(s.id),
      } : {})}
    >
      {s.slots.map((sl, i) => {
        const won = sl.entrant_id != null && sl.entrant_id === s.winner_id
        const hovered = hoverId != null && sl.entrant_id === hoverId
        return (
          <div
            key={sl.entrant_id ?? `tbd${i}`}
            className={`tgb-slot${won ? ' tgb-slot--win' : ''}${hovered ? ' tgb-slot--hover' : ''}`}
            onMouseEnter={() => onHover(sl.entrant_id ?? null)}
            onMouseLeave={() => onHover(null)}
          >
            <span className="tgb-name">
              {sl.name || '—'}
              {sl.seed != null && <small>{sl.seed}</small>}
            </span>
            <SlotScore score={sl.score} />
          </div>
        )
      })}
      {watchable && <span className="tgb-play" aria-hidden="true">▶</span>}
    </Tag>
  )
}

export default function BracketView({ sets, myEntrantId, replayMap, onOpenSet }) {
  const [hoverId, setHoverId] = useState(null)
  const blocks = useMemo(() => buildBlocks(sets), [sets])
  if (!blocks.length) return null

  return (
    <div className="tgb">
      {blocks.map((b) => (
        <div className="tgb-block" key={b.pg?.id ?? 'main'}>
          {(blocks.length > 1 || b.pg?.phase) && (
            <h4 className="tgb-phase">
              {b.pg?.phase || 'Bracket'}
              {b.pg?.label && b.pg.label !== '1' ? ` — ${b.pg.label}` : ''}
            </h4>
          )}
          {[['winners', b.winners], ['losers', b.losers]].map(([lane, cols]) => (
            cols.length > 0 && (
              <div className={`tgb-lane tgb-lane--${lane}`} key={lane}>
                {cols.map((col) => (
                  <div className="tgb-col" key={col.round}>
                    <span className="tgb-col-title">{col.title}</span>
                    <div className="tgb-col-sets">
                      {col.sets.map((s) => (
                        <BracketSet key={s.id} s={s} myEntrantId={myEntrantId}
                                    hoverId={hoverId} onHover={setHoverId}
                                    replays={replayMap?.get(s.id)?.length || 0}
                                    onOpenSet={onOpenSet} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )
          ))}
        </div>
      ))}
    </div>
  )
}
