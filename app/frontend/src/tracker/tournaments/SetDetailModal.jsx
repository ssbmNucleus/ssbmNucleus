import { useEffect, useMemo, useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { stageName, formatDuration } from '../../shared/data/meleeNames'
import LiteButton from '../lib/LiteGate'
import { scoreLabel } from './tournamentMath'
import { matchForSets, shortDate } from './tournamentShared'

// ── set-detail sheet ──
// Every replay-aware surface funnels here: one or more sets, each expanded
// into its actual games (from the local Slippi index) with per-game playback.
function GameChips({ set, games, onWatch }) {
  if (games === undefined) return <span className="tg-detail-nogames">matching…</span>
  if (!games?.length) return <span className="tg-detail-nogames">no local replays matched</span>
  const clips = games.map((g, i) => ({
    gameId: g.id,
    title: `${set.round_text || 'Set'} — Game ${i + 1}`,
    subtitle: `vs ${set.opp.name || '?'} · ${set.event?.tournament || set.event?.name || ''}`,
  }))
  return (
    <span className="tg-detail-games">
      {games.map((g, i) => (
        <LiteButton
          key={g.id}
          className={`tg-gamechip ${g.result === 'win' ? 'is-up' : g.result === 'loss' ? 'is-down' : ''}`}
          onOpen={() => onWatch(clips, i)}
          title={`${stageName(g.stage)} · ${formatDuration(g.duration_s)}${g.result ? ` · ${g.result}` : ''}`}
        >
          ▶ G{i + 1}
        </LiteButton>
      ))}
      {games.length > 1 && (
        <LiteButton className="tg-gamechip tg-gamechip--all" onOpen={() => onWatch(clips, 0)}>
          watch set
        </LiteButton>
      )}
    </span>
  )
}

export default function SetDetailModal({ detail, onClose, onWatch, replayRevision }) {
  const [map, setMap] = useState(null)
  const sets = useMemo(
    () => detail.sets.slice().sort((a, b) => (b.completed_at || 0) - (a.completed_at || 0)),
    [detail.sets])

  useEffect(() => {
    let live = true
    setMap(null)
    matchForSets(sets, replayRevision).then((m) => { if (live) setMap(m) })
      .catch(() => { if (live) setMap(new Map()) })
    return () => { live = false }
  }, [sets, replayRevision])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="tg-detail-backdrop" onClick={() => { playSound('boop'); onClose() }}>
      <div className="tg-detail" onClick={(e) => e.stopPropagation()}>
        <div className="tg-detail-head">
          <div className="tg-detail-title">
            <strong>{detail.title}</strong>
            {detail.subtitle && <span>{detail.subtitle}</span>}
          </div>
          <button type="button" className="tg-detail-close" aria-label="Close"
                  onClick={() => { playSound('boop'); onClose() }}>✕</button>
        </div>
        <div className="tg-detail-sets">
          {sets.map((s) => (
            <div className="tg-detail-set" key={s.id}>
              <div className="tg-detail-set-line">
                <span className={`tg-set-pip ${s.won ? 'is-up' : 'is-down'}`}>{s.won ? 'W' : 'L'}</span>
                <span className="tg-detail-round">{s.round_text || 'Set'}</span>
                <span className="tg-detail-event">
                  {s.event?.tournament || s.event?.name || ''} · {shortDate(s.completed_at)}
                </span>
                <span className={`tg-set-score${s.dq ? ' tg-set-score--dq' : ''}`}>{scoreLabel(s)}</span>
              </div>
              <GameChips set={s} games={map === null ? undefined : (map.get(s.id) || [])} onWatch={onWatch} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
