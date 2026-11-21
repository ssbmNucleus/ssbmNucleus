import { useContext, useMemo, useState } from 'react'
import { charName } from '../../shared/data/meleeNames'
import { TipCtx, TipCard } from './StatsTooltip'
import { API, num, pct } from './statsHelpers'

// character-share donut: fixed hue order (CVD-validated vs the nucleome
// surface); gray is reserved for the "Other" fold, never a character
const PIE_COLORS = ['#7de8d3', '#a78bfa', '#f2a35c', '#7da5e8',
                    '#e87d9d', '#b8e87d', '#d97de8']
const PIE_OTHER_COLOR = '#8a93a3'

function arcPath(cx, cy, r0, r1, a0, a1) {
  const large = a1 - a0 > Math.PI ? 1 : 0
  const pt = (r, a) => `${(cx + r * Math.sin(a)).toFixed(2)},${(cy - r * Math.cos(a)).toFixed(2)}`
  return `M ${pt(r1, a0)} A ${r1} ${r1} 0 ${large} 1 ${pt(r1, a1)}`
       + ` L ${pt(r0, a1)} A ${r0} ${r0} 0 ${large} 0 ${pt(r0, a0)} Z`
}

// Share-of-games donut for "My characters": stock icons sit ON the slices
// (no legend); hovering a slice swaps the donut center to that character's
// details (name, games, share, winrate). Center shows the total otherwise.
export function CharPie({ entries }) {
  const [hover, setHover] = useState(null)
  const tip = useContext(TipCtx)
  const top = entries.slice(0, PIE_COLORS.length)
  const rest = entries.slice(PIE_COLORS.length)
  const slices = top.map((e, i) => ({
    label: charName(e.character), character: e.character,
    color: PIE_COLORS[i], games: e.games, winrate: e.winrate,
  }))
  if (rest.length) {
    const games = rest.reduce((n, e) => n + e.games, 0)
    const wins = rest.reduce((n, e) => n + e.wins, 0)
    const losses = rest.reduce((n, e) => n + e.losses, 0)
    slices.push({
      label: `Other (${rest.length} chars)`, character: null, color: PIE_OTHER_COLOR,
      games, winrate: wins + losses ? wins / (wins + losses) : null,
      isOther: true,
    })
  }
  const total = slices.reduce((n, s) => n + s.games, 0)
  if (!total) return null

  let angle = 0
  const arcs = slices.map((s) => {
    const a0 = angle
    angle += (s.games / total) * 2 * Math.PI
    // an SVG arc degenerates when start == end, so a ~full circle gets
    // clipped a hair short
    return { ...s, a0, a1: Math.min(angle, a0 + 2 * Math.PI - 0.001) }
  })

  // hovering "Other" opens the full folded-character breakdown as a menu
  const otherTip = (
    <>
      <div className="stats-tip-title">Everyone else</div>
      <div className="stats-tip-grid">
        {rest.map((e) => (
          <div className="stats-tip-grid-row" key={e.character}>
            <img className="stats-tip-icon" src={`${API}/stock/${e.character}/0`} alt="" />
            <span className="stats-tip-grid-name">{charName(e.character)}</span>
            <span className="stats-tip-grid-val">{num(e.games)}</span>
          </div>
        ))}
      </div>
    </>
  )
  const sliceTip = (s) => (s.isOther ? otherTip : TipCard({
    title: s.label,
    icon: `${API}/stock/${s.character}/0`,
    rows: [['Games', num(s.games)],
           ['Share', `${Math.round((100 * s.games) / total)}%`],
           ['Winrate', pct(s.winrate)]],
  }))

  const R0 = 58, R1 = 98, MID = (R0 + R1) / 2
  return (
    <div className="stats-pie">
      <svg className="stats-pie-svg" viewBox="0 0 220 220"
           onMouseLeave={() => { setHover(null); tip.hide() }}>
        {arcs.map((s) => (
          <path key={s.label} d={arcPath(110, 110, R0, R1, s.a0, s.a1)}
                fill={s.color}
                className={`stats-pie-slice ${hover && hover.label !== s.label ? 'is-dimmed' : ''}`}
                onMouseEnter={() => setHover(s)}
                onMouseMove={(ev) => tip.move(ev, sliceTip(s))} />
        ))}
        {arcs.map((s) => {
          // icons only fit on slices past ~3.5% share; hover covers the rest
          if (s.character == null || s.a1 - s.a0 < 0.22) return null
          const mid = (s.a0 + s.a1) / 2
          return (
            <image key={`i${s.label}`} className="stats-pie-slice-icon"
                   href={`${API}/stock/${s.character}/0`}
                   x={110 + MID * Math.sin(mid) - 9}
                   y={110 - MID * Math.cos(mid) - 9}
                   width="18" height="18" />
          )
        })}
        {hover ? (
          <>
            <text x="110" y="96" textAnchor="middle" className="stats-pie-center-name">{hover.label}</text>
            <text x="110" y="118" textAnchor="middle" className="stats-pie-center">{num(hover.games)}</text>
            <text x="110" y="134" textAnchor="middle" className="stats-pie-center-sub">
              {`${Math.round((100 * hover.games) / total)}% · ${pct(hover.winrate)} wr`}
            </text>
          </>
        ) : (
          <>
            <text x="110" y="106" textAnchor="middle" className="stats-pie-center">{num(total)}</text>
            <text x="110" y="124" textAnchor="middle" className="stats-pie-center-sub">games</text>
          </>
        )}
      </svg>
    </div>
  )
}

// Winrate at each exact game-number-within-session, as diverging bars
// around the 50% break-even line (up/green = winning, down/red = losing).
// Exact bars run only while the depth still has a real sample (30+ games);
// past that, individual positions are one-marathon coin flips, so the whole
// tail pools into a single "N+" bar with an honest combined sample.
const POS_MIN_GAMES = 30

export function PositionChart({ positions }) {
  const tip = useContext(TipCtx)
  const usable = positions.filter((p) => p.winrate != null)
  if (!usable.length) return null
  const solid = usable.filter((p) => p.games >= POS_MIN_GAMES)
  const cutoff = solid.length ? Math.max(...solid.map((p) => p.position))
                              : positions[positions.length - 1].position
  const byPos = Object.fromEntries(positions.map((p) => [p.position, p]))

  const tail = positions.filter((p) => p.position > cutoff)
  const tailWins = tail.reduce((n, p) => n + p.wins, 0)
  const tailLosses = tail.reduce((n, p) => n + p.losses, 0)
  const tailGames = tail.reduce((n, p) => n + p.games, 0)
  const tailWr = tailWins + tailLosses ? tailWins / (tailWins + tailLosses) : null

  // Baseline = YOUR OWN average winrate across all these games, not 50%.
  // Centering on 50% just makes every bar green when you win overall; what
  // reveals tilt/stamina is where a position beats or trails your own norm.
  const totWins = usable.reduce((n, p) => n + p.wins, 0)
  const totLosses = usable.reduce((n, p) => n + p.losses, 0)
  const baseline = totWins + totLosses ? totWins / (totWins + totLosses) : 0.5

  const maxDev = Math.max(0.03, ...solid.map((p) => Math.abs(p.winrate - baseline)),
                          tailWr != null ? Math.abs(tailWr - baseline) : 0)
  const bar = (wr) => {
    const dev = Math.max(-maxDev, Math.min(maxDev, wr - baseline))
    return { h: Math.max(2, (Math.abs(dev) / maxDev) * 50), up: dev >= 0 }
  }
  const signed = (d) => `${d >= 0 ? '+' : '−'}${(Math.abs(d) * 100).toFixed(1)} pts`
  const posRows = (p, title) => TipCard({
    title,
    rows: [['Winrate', pct(p.winrate)],
           ['vs your average', signed(p.winrate - baseline)],
           ['Record', `${num(p.wins)}W – ${num(p.losses)}L`],
           ['Times reached', num(p.games)]],
  })

  return (
    <>
      <div className="stats-poschart" role="img"
           aria-label="Winrate by game number within a session, relative to your average">
        <div className="stats-poschart-mid">
          <span className="stats-poschart-baseline">avg {pct(baseline)}</span>
        </div>
        {Array.from({ length: cutoff }, (_, i) => {
          const pos = i + 1
          const p = byPos[pos]
          if (!p || p.winrate == null) {
            return <div className="stats-poschart-col" key={pos} />
          }
          const { h, up } = bar(p.winrate)
          return (
            <div className="stats-poschart-col" key={pos}
                 onMouseMove={(ev) => tip.move(ev, posRows(p, `Game #${pos} of a session`))}
                 onMouseLeave={tip.hide}>
              <div className={`stats-poschart-bar ${up ? 'is-up' : 'is-down'}`}
                   style={{ height: `${h}%`,
                            opacity: 0.25 + 0.75 * Math.min(1, p.games / 150) }} />
              {(pos === 1 || pos % 10 === 0) && (
                <span className="stats-sesshist-tick">{pos}</span>
              )}
            </div>
          )
        })}
        {tailWr != null && (
          <div className="stats-poschart-col stats-poschart-col--tail"
               onMouseMove={(ev) => tip.move(ev, posRows(
                 { winrate: tailWr, wins: tailWins, losses: tailLosses, games: tailGames },
                 `Game #${cutoff + 1} or deeper (pooled)`))}
               onMouseLeave={tip.hide}>
            <div className={`stats-poschart-bar ${bar(tailWr).up ? 'is-up' : 'is-down'}`}
                 style={{ height: `${bar(tailWr).h}%`,
                          opacity: 0.25 + 0.75 * Math.min(1, (tailWins + tailLosses) / 150) }} />
            <span className="stats-sesshist-tick">{cutoff + 1}+</span>
          </div>
        )}
      </div>
      <p className="stats-footnote">
        Bars show each game&apos;s winrate against your own {pct(baseline)}
        {' '}average — up = you play above your norm that deep, down = below.
      </p>
    </>
  )
}

// Session-length distribution: one thin column per exact length (1 game,
// 2 games, …), height = how many sessions were that long. No buckets.
export function SessionHist({ dist }) {
  const tip = useContext(TipCtx)
  if (!dist?.length) return null
  const maxLen = dist[dist.length - 1].games
  const byLen = Object.fromEntries(dist.map((d) => [d.games, d.sessions]))
  const max = Math.max(...dist.map((d) => d.sessions))
  const cols = Array.from({ length: maxLen }, (_, i) => ({
    len: i + 1, n: byLen[i + 1] || 0,
  }))
  return (
    <div className="stats-sesshist" role="img" aria-label="Sessions by length in games">
      {cols.map((c) => (
        <div className="stats-sesshist-col" key={c.len}
             onMouseMove={(ev) => tip.move(ev, TipCard({
               title: `${c.len}-game session${c.n === 1 ? '' : 's'}`,
               rows: [['Sessions', num(c.n)]],
             }))}
             onMouseLeave={tip.hide}>
          <div className="stats-sesshist-bar"
               style={{ height: c.n ? `${Math.max(2, (100 * c.n) / max)}%` : 0 }} />
          {(c.len === 1 || c.len % 10 === 0) && (
            <span className="stats-sesshist-tick">{c.len}</span>
          )}
        </div>
      ))}
    </div>
  )
}

// Games-by-hour bar chart (local time): bar height = games played that hour,
// bar color = that hour's winrate against YOUR OWN average. The shade carries
// the magnitude — near your average reads washed-out gray, far above/below
// saturates to full green/red. Hours with a real sample set the color scale;
// thin-sample hours clamp to it. Gray = no decided games.
const hourLabel = (h) => (h === 0 ? '12a' : h === 12 ? '12p'
                          : h < 12 ? `${h}a` : `${h - 12}p`)
const HOUR_MIN_GAMES = 20

export function HourChart({ cells }) {
  const tip = useContext(TipCtx)
  const hours = useMemo(() => {
    const h = Array.from({ length: 24 }, () => ({ games: 0, wins: 0, losses: 0 }))
    for (const c of cells) {
      h[c.h].games += c.games
      h[c.h].wins += c.wins
      h[c.h].losses += c.losses
    }
    return h
  }, [cells])
  if (!cells.length) return null

  const totWins = hours.reduce((n, h) => n + h.wins, 0)
  const totLosses = hours.reduce((n, h) => n + h.losses, 0)
  if (!totWins && !totLosses) return null
  const baseline = totWins / (totWins + totLosses)
  const max = Math.max(1, ...hours.map((h) => h.games))

  const wr = (h) => (h.wins + h.losses ? h.wins / (h.wins + h.losses) : null)
  const solid = hours.filter((h) => h.wins + h.losses >= HOUR_MIN_GAMES)
  const maxDev = Math.max(0.03, ...solid.map((h) => Math.abs(wr(h) - baseline)))
  const shade = (dev) => {
    const t = Math.min(1, Math.abs(dev) / maxDev)
    const color = dev >= 0 ? 'var(--color-success)' : 'var(--color-danger)'
    // full color only at the scale's edge; near-baseline fades to neutral
    return `color-mix(in srgb, ${color} ${Math.round(20 + 80 * t)}%, var(--color-text-muted))`
  }
  const signed = (d) => `${d >= 0 ? '+' : '−'}${(Math.abs(d) * 100).toFixed(1)} pts`

  return (
    <>
      <div className="stats-hours" role="img"
           aria-label="Games per hour of day, colored by winrate relative to your average">
        {hours.map((h, i) => {
          const rate = wr(h)
          return (
            <div className="stats-hour-col" key={i}
                 onMouseMove={(ev) => tip.move(ev, TipCard({
                   title: `${hourLabel(i)} – ${hourLabel((i + 1) % 24)}`,
                   rows: [
                     ['Games', num(h.games)],
                     rate != null && ['Winrate', pct(rate)],
                     rate != null && ['vs your average', signed(rate - baseline)],
                     rate != null && ['Record', `${num(h.wins)}W – ${num(h.losses)}L`],
                   ],
                 }))}
                 onMouseLeave={tip.hide}>
              {h.games > 0 && (
                <div className={`stats-hour-bar ${rate == null ? 'is-none' : ''}`}
                     style={{ height: `${Math.max(2, (100 * h.games) / max)}%`,
                              ...(rate != null && { background: shade(rate - baseline) }) }} />
              )}
              {i % 3 === 0 && <span className="stats-sesshist-tick">{hourLabel(i)}</span>}
            </div>
          )
        })}
      </div>
      <p className="stats-footnote">
        Bar height = games played that hour; color = winrate vs your own
        {' '}{pct(baseline)} average. Vivid green = well above it, vivid red =
        well below, washed-out = close to it.
      </p>
    </>
  )
}

// Fill calendar gaps with zero-game months so the time axis stays honest —
// a skipped dead month would silently compress the timeline.
function fillMonths(months) {
  if (months.length < 2) return months
  const out = []
  let [y, mo] = months[0].month.split('-').map(Number)
  const last = months[months.length - 1].month
  const byKey = Object.fromEntries(months.map((m) => [m.month, m]))
  for (;;) {
    const key = `${y}-${String(mo).padStart(2, '0')}`
    out.push(byKey[key] || { month: key, games: 0, winrate: null })
    if (key === last) break
    mo += 1
    if (mo > 12) { mo = 1; y += 1 }
  }
  return out
}

// Monthly activity: one thin column per month, height = games played.
// Winrate stays in the tooltip — magnitude is the single encoded value.
export function MonthChart({ months: rawMonths }) {
  const months = useMemo(() => fillMonths(rawMonths), [rawMonths])
  const tip = useContext(TipCtx)
  const max = Math.max(1, ...months.map((m) => m.games))
  const monthTip = (m) => TipCard({
    title: m.month,
    rows: [
      ['Games', num(m.games)],
      m.winrate != null && ['Record', `${num(m.wins)}W – ${num(m.losses)}L`],
      m.winrate != null && ['Winrate', pct(m.winrate)],
    ],
  })
  return (
    <div className="stats-months" role="img" aria-label="Games played per month">
      {months.map((m, i) => {
        const year = m.month.slice(0, 4)
        const newYear = i === 0 || months[i - 1].month.slice(0, 4) !== year
        return (
          <div className="stats-month-col" key={m.month}
               onMouseMove={(ev) => tip.move(ev, monthTip(m))}
               onMouseLeave={tip.hide}>
            <div className="stats-month-bar"
                 style={{ height: m.games ? `${Math.max(2, (100 * m.games) / max)}%` : 0 }} />
            {newYear && <span className="stats-month-year">{year}</span>}
          </div>
        )
      })}
    </div>
  )
}
