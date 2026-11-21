import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { ordinal, scoreLabel } from './tournamentMath'
import { DeltaBadge, openExternal, placeClass, Section, shortDate } from './tournamentShared'

// One set of the run: result pip, round, opponent (+seed), UF badge, score,
// and a ▶ chip when local Slippi replays matched this set's time window.
// The chip opens the set-detail sheet (game-by-game, each playable).
function SetRow({ set, replays, onOpenSet }) {
  return (
    <div className="tg-set">
      <span className={`tg-set-pip ${set.won ? 'is-up' : 'is-down'}`}>{set.won ? 'W' : 'L'}</span>
      <span className="tg-set-round">{set.round_text || 'Set'}</span>
      <span className="tg-set-opp">
        {set.opp.name || '—'}
        {set.opp.seed != null && <small>seed {set.opp.seed}</small>}
      </span>
      {set.upset && <span className="tg-badge tg-badge--up" title={`Upset factor ${set.uf} — you beat a seed ${set.uf} bracket tiers above you`}>UF {set.uf}</span>}
      {set.gotUpset && <span className="tg-badge tg-badge--down" title={`They upset you — seeded ${set.uf} bracket tiers below you`}>upset</span>}
      <span className={`tg-set-score${set.dq ? ' tg-set-score--dq' : ''}`}>{scoreLabel(set)}</span>
      {replays?.length ? (
        <button
          type="button" className="tg-watch"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); onOpenSet(set) }}
          title={`${replays.length} local replay${replays.length > 1 ? 's' : ''} matched this set — open them`}
        >
          ▶ {replays.length}
        </button>
      ) : <span className="tg-watch tg-watch--none" />}
    </div>
  )
}

// Loss quality — the consoling stat every player checks after a bracket:
// WHO knocked you out, and how far did they go? "Both your losses finished
// top 3" reframes a 5th place; "you lost to 33rd" is honest too.
function lossQuality(run) {
  if (run.losses === 0 && run.placement === 1) {
    return 'Undefeated — nobody took a set off you.'
  }
  const byOpp = new Map()
  for (const s of run.sets) {
    if (s.won || s.dq || s.opp.placement == null) continue
    const key = s.opp.name || s.opp.entrant_id
    if (!byOpp.has(key)) byOpp.set(key, { name: s.opp.name, placement: s.opp.placement })
  }
  if (!byOpp.size) return null
  const parts = [...byOpp.values()]
    .sort((a, b) => a.placement - b.placement)
    .slice(0, 3)
    .map((o) => `${o.name} (finished ${ordinal(o.placement)})`)
  return `Your losses: ${parts.join(', ')}.`
}

// The hero: your latest (or selected) bracket run, set by set.
export default function RunSection({ run, replayMap, onOpenSet, onBracket, bracketOpen }) {
  const ev = run.event
  const matched = run.sets.reduce((n, s) => n + (replayMap.get(s.id)?.length || 0), 0)
  const quality = lossQuality(run)
  return (
    <Section
      title="The run"
      sub={`${shortDate(run.lastAt)}${ev.city ? ` · ${ev.city}` : ''}${ev.online ? ' · online' : ''}`}
    >
      <div className="tg-run-head">
        <div className="tg-run-title">
          <strong>{ev.tournament || ev.name}</strong>
          <span>{ev.name}</span>
        </div>
        <div className="tg-run-links">
          <button
            type="button" className={`tg-btn${bracketOpen ? ' tg-btn--active' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); onBracket() }}
          >
            {bracketOpen ? 'hide bracket' : 'view bracket'}
          </button>
          {ev.slug && (
            <button
              type="button" className="tg-link"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); openExternal(`https://www.start.gg/${ev.slug}`) }}
            >
              start.gg ↗
            </button>
          )}
        </div>
      </div>
      <div className="tg-run-hero">
        <span className={`tg-run-place ${placeClass(run.placement)}`}>{ordinal(run.placement)}</span>
        <div className="tg-run-hero-sub">
          <span>of {run.event.entrants ?? '—'} entrants</span>
          <span>
            {run.seed != null ? `seeded ${run.seed}` : 'seed unknown'}
            {' '}· went {run.wins}–{run.losses}
          </span>
          <DeltaBadge delta={run.delta} />
        </div>
      </div>
      {quality && <p className="tg-run-insight">{quality}</p>}
      <div className="tg-sets">
        {run.sets.map((s) => (
          <SetRow key={s.id} set={s} replays={replayMap.get(s.id)} onOpenSet={onOpenSet} />
        ))}
      </div>
      {matched > 0 && (
        <p className="stats-footnote">
          {matched} local Slippi replay{matched > 1 ? 's' : ''} matched this
          bracket by time — press ▶ on a set to watch the actual games.
        </p>
      )}
    </Section>
  )
}
