// matchcard — the match summary card, one builder for every surface that names
// a game: the app's detail header and the public /replay/<id> page. It used to
// live inline in detail.js as the ".dsummary" section while the header above it
// said "Fox vs Sheik" in plain text -- the same information twice, the worse
// rendering on top. Now the card IS the header, everywhere, built here so the
// two pages cannot drift.
import { esc, stockSrc, stageSrc, rankSrc, shortDate } from './ui'
import { stageName, formatDuration, slippiProfileUrl } from '../../../app/frontend/src/shared/data/meleeNames'

function timeOf(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return ` · ${d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`
}

/** The card's HTML for a game row {players, user_port, result, end_stocks,
 *  stage, start_at, duration_s}. Owner-relative W/L renders wherever `result`
 *  and `user_port` exist -- the public payload carries both. `rankOf(code)`
 *  resolves a connect code to a cached Slippi rank ({ranked, tier}) or null --
 *  a resolver rather than a map so the app can hand in its session cache and
 *  the public page the server's, without either knowing about the other. */
export function matchCard(g, rankOf) {
  const me = g.user_port != null
    ? (g.players || []).find((p) => p.port === g.user_port)
    : (g.players || [])[0]
  const op = g.user_port != null
    ? (g.players || []).find((p) => p.port !== g.user_port)
    : (g.players || [])[1]

  const st = g.end_stocks || {}
  const pips = (p) => {
    const c = st[String(p?.port)]
    if (!p || !c) return ''
    return `<span class="pl-stocks">${Array.from({ length: Math.min(c, 4) })
      .map(() => `<img src="${stockSrc(p.character, p.costume)}" alt="">`).join('')}</span>`
  }
  // The rank badge holds the card's outer slot -- the character is already
  // told by the name and the stock pips, so a third telling (the big stock
  // icon that used to sit here) said nothing new. The slot always renders,
  // empty for the unranked, so a missing badge cannot fold the card
  // asymmetric. rankSrc is the gate, exactly like the games list: it returns
  // null for Pending and anything it has no icon for.
  const badge = (p) => {
    const r = rankOf && p?.code ? rankOf(p.code) : null
    const src = r && r.ranked ? rankSrc(r.tier) : null
    return `<span class="dsum-rank">${src
      ? `<img src="${src}" alt="${esc(r.tier)}" title="${esc(r.tier)}">`
      : '<span class="dsum-norank">–</span>'}</span>`
  }
  // Both sides emit the same DOM order; the right one mirrors VISUALLY via
  // row-reverse, so char icons sit at the outer edges and W/L + rank pair off
  // symmetrically around the vs.
  // the name is the player's front door: their slippi.gg profile
  const nameEl = (p) => {
    const url = slippiProfileUrl(p?.code)
    const label = esc(p?.name || 'Player')
    return url
      ? `<a class="dsum-name" href="${url}" target="_blank" rel="noopener">${label}</a>`
      : `<span class="dsum-name">${label}</span>`
  }
  const side = (p, res, flip) => `<div class="dsum-side dsum-side--${flip ? 'r' : 'l'}">
    ${badge(p)}
    <div class="dsum-id">
      ${nameEl(p)}
      ${p?.code ? `<span class="dsum-tag">${esc(p.code)}</span>` : ''}
      ${pips(p)}
    </div>
    ${res ? `<span class="result result--${res}">${res === 'win' ? 'W' : 'L'}</span>` : ''}
  </div>`

  return `<div class="dsum">
      ${side(me, g.result, false)}
      <span class="vs-mid">vs</span>
      ${side(op, g.result === 'win' ? 'loss' : g.result === 'loss' ? 'win' : null, true)}
    </div>
    <div class="row-meta" style="margin-top:8px">
      <img class="stage-ico" src="${stageSrc(g.stage)}" alt="" onerror="this.style.display='none'">
      <span class="stg">${esc(stageName(g.stage))}</span>
      <span class="dot">·</span><span>${shortDate(g.start_at)}${timeOf(g.start_at)}</span>
      <span class="grow"></span>
      <span class="dur">${formatDuration(g.duration_s)}</span>
    </div>`
}
