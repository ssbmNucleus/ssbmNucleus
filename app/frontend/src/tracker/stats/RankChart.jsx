import { useContext, useMemo } from 'react'
import { TipCtx, TipCard } from './StatsTooltip'
import { num, shortDate } from './statsHelpers'

// Slippi tier START thresholds (ordinal where each tier begins)
const TIER_LINES = [
  [1054.87, 'Silver'], [1435.48, 'Gold'], [1751.83, 'Plat'],
  [2003.92, 'Diamond'], [2191.75, 'Master'],
]
// fixed categorical order, one color per connect code (validated vs the
// nucleome dark surface; identity is never color-alone — lines carry a
// direct code label at their endpoint)
const SERIES_COLORS = ['var(--color-accent)', '#a78bfa', '#f2a35c', '#7da5e8']

// Rating over time: past seasons' FINAL ratings (all Slippi publishes) as
// backfill, plus the samples nucleOME records locally on every rank fetch —
// so the line gets denser from first install onward.
export default function RankChart({ history }) {
  const tip = useContext(TipCtx)
  const series = useMemo(() => {
    const out = []
    for (const [code, h] of Object.entries(history || {})) {
      const pts = []
      for (const s of h.seasons || []) {
        const t = Date.parse(s.ended_at)
        if (!Number.isNaN(t)) {
          pts.push({ t, rating: s.rating, tier: s.tier,
                     label: `${s.name} final`, wins: s.wins, losses: s.losses })
        }
      }
      for (const smp of h.samples || []) {
        const t = Date.parse(smp.at)
        if (!Number.isNaN(t)) {
          pts.push({ t, rating: smp.rating, tier: smp.tier,
                     label: shortDate(smp.at), wins: smp.wins, losses: smp.losses })
        }
      }
      pts.sort((a, b) => a.t - b.t)
      if (pts.length) out.push({ code, pts })
    }
    // stable assignment: biggest history first (the "main" account), then name
    out.sort((a, b) => b.pts.length - a.pts.length || a.code.localeCompare(b.code))
    return out.slice(0, SERIES_COLORS.length)
  }, [history])

  if (!series.length) return null

  const W = 860, H = 230
  const padL = 56, padR = 84, padT = 14, padB = 24
  const allPts = series.flatMap((s) => s.pts)
  const tMin = Math.min(...allPts.map((p) => p.t))
  const tMax = Math.max(...allPts.map((p) => p.t), Date.now())
  const tPad = Math.max((tMax - tMin) * 0.02, 1)
  const rMin = Math.min(...allPts.map((p) => p.rating)) - 70
  const rMax = Math.max(...allPts.map((p) => p.rating)) + 70
  const x = (t) => padL + ((t - tMin + tPad) / (tMax - tMin + 2 * tPad)) * (W - padL - padR)
  const y = (r) => padT + (1 - (r - rMin) / (rMax - rMin)) * (H - padT - padB)

  const years = []
  for (let yr = new Date(tMin).getFullYear() + 1; yr <= new Date(tMax).getFullYear(); yr++) {
    years.push(yr)
  }

  return (
    <svg className="stats-rankchart" viewBox={`0 0 ${W} ${H}`}>
      {TIER_LINES.filter(([r]) => r > rMin && r < rMax).map(([r, name]) => (
        <g key={name}>
          <line x1={padL} x2={W - padR} y1={y(r)} y2={y(r)} className="stats-rank-tierline" />
          <text x={padL - 6} y={y(r) + 3} className="stats-rank-tierlabel" textAnchor="end">{name}</text>
        </g>
      ))}
      {years.map((yr) => {
        const t = new Date(yr, 0, 1).getTime()
        if (t < tMin || t > tMax) return null
        return (
          <g key={yr}>
            <line x1={x(t)} x2={x(t)} y1={padT} y2={H - padB} className="stats-rank-yearline" />
            <text x={x(t)} y={H - 8} className="stats-rank-yearlabel" textAnchor="middle">{yr}</text>
          </g>
        )
      })}
      {series.map((s, i) => (
        <g key={s.code} style={{ color: SERIES_COLORS[i] }}>
          {s.pts.length > 1 && (
            <polyline
              className="stats-rank-line"
              points={s.pts.map((p) => `${x(p.t).toFixed(1)},${y(p.rating).toFixed(1)}`).join(' ')}
            />
          )}
          {s.pts.map((p) => (
            <circle key={p.t} cx={x(p.t)} cy={y(p.rating)} r="3.5" className="stats-rank-dot"
                    onMouseMove={(ev) => tip.move(ev, TipCard({
                      title: `${s.code} — ${p.label}`,
                      rows: [['Rating', p.rating],
                             ['Tier', p.tier || '—'],
                             ['Record', `${num(p.wins)}W – ${num(p.losses)}L`]],
                    }))}
                    onMouseLeave={tip.hide} />
          ))}
          <text
            x={x(s.pts[s.pts.length - 1].t) + 8}
            y={y(s.pts[s.pts.length - 1].rating) + 3}
            className="stats-rank-serieslabel"
          >
            {s.code}
          </text>
        </g>
      ))}
    </svg>
  )
}
