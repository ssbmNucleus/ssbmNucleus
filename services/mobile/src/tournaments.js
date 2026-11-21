// Tournaments tab — "Your start.gg" on the phone. Same data path as desktop:
// the public startgg-proxy edge function (the start.gg token never ships in a
// client), the same tournamentMath derivations, and the desktop trick of
// attaching your actual replays to the sets they belong to — which works even
// better here, because the whole library is already cached in memory.
//
// Layout (top to bottom, mirroring what the desktop page knows but stacked
// for a thumb): profile + statline, THE RUN (latest event, expanded, with
// seeds/upset factors/replay chips), the seed-vs-finish trajectory strip,
// best wins, bracket demons, the full head-to-head list, then the remaining
// events as compact expandable cards.
import {
  groupEvents, headToHead, demons, bestWins, trajectory,
  ordinal, scoreLabel, matchReplaysToSets,
} from '../../../app/frontend/src/tracker/tournaments/tournamentMath'
import { startgg, prefsGet, prefsSet } from './api'
import { el, esc, toast, shortDate, num } from './ui'

const SLUG_KEY = 'nucleus.startgg.slug'
const SETS_KEY = 'nucleus.vault.startgg.sets'
const PAGES = 8   // 8×25 = up to 200 most recent sets per refresh

const getSlug = () => { try { return localStorage.getItem(SLUG_KEY) || '' } catch { return '' } }
const setSlug = (s) => { try { s ? localStorage.setItem(SLUG_KEY, s) : localStorage.removeItem(SLUG_KEY) } catch { /* */ } }

function parseSlug(input) {
  const s = (input || '').trim()
  if (!s) return ''
  const m = s.match(/start\.gg\/user\/([A-Za-z0-9_-]+)/i)
  if (m) return m[1]
  return s.replace(/[/\s]+$/, '').replace(/^.*\//, '')
}

// Melee only — the same start.gg profile may enter other games (the desktop's
// mergePage has the same guard; this port originally missed it and a Hbox
// profile surfaced Ultimate events). game == null predates the proxy field.
const isMelee = (s) => s?.event?.game == null || s.event.game === 1

function readCache() {
  try {
    const data = JSON.parse(localStorage.getItem(SETS_KEY))
    // older caches may hold other games' sets synced before the guard
    if (data?.sets) data.sets = data.sets.filter(isMelee)
    return data
  } catch { return null }
}
function writeCache(data) {
  try { localStorage.setItem(SETS_KEY, JSON.stringify(data)) } catch { /* full */ }
}

async function syncSets(slug, existing) {
  // The proxy's start.gg token is shared and rate-limited — be a polite
  // tenant: small page count, gap between requests, serve cache on failure.
  const byId = new Map((existing?.sets || []).filter(isMelee).map((s) => [s.id, s]))
  let playerId = existing?.player_id ?? null
  let tag = existing?.gamer_tag ?? null
  for (let page = 1; page <= PAGES; page++) {
    const out = await startgg({ op: 'sets', slug, page })
    playerId = out.player_id ?? playerId
    tag = out.gamer_tag ?? tag
    for (const s of (out.sets || []).filter(isMelee)) byId.set(s.id, s)
    if (!out.sets?.length || page >= (out.total_pages || 1)) break
    await new Promise((r) => setTimeout(r, 700))
  }
  const data = {
    player_id: playerId, gamer_tag: tag,
    sets: [...byId.values()], synced_at: Date.now(),
  }
  writeCache(data)
  return data
}

// ── small formatters ──────────────────────────────────────────────────────

const dateOf = (unixSeconds) => shortDate(
  unixSeconds ? new Date(unixSeconds * 1000).toISOString() : null)

/** "Winners Semi-Final" → "WSF", "Losers Round 2" → "LR2" — full round names
 * are a third of the row width on a phone. Order matters: finals before
 * rounds, grands before winners. */
function shortRound(t) {
  if (!t) return ''
  return t
    .replace(/Grand Final Reset/i, 'GF reset')
    .replace(/Grand Finals?/i, 'GF')
    .replace(/Winners? Finals?/i, 'WF')
    .replace(/Winners? Semi-?Finals?/i, 'WSF')
    .replace(/Winners? Quarter-?Finals?/i, 'WQF')
    .replace(/Losers? Finals?/i, 'LF')
    .replace(/Losers? Semi-?Finals?/i, 'LSF')
    .replace(/Losers? Quarter-?Finals?/i, 'LQF')
    .replace(/Winners? Round (\d+)/i, 'WR$1')
    .replace(/Losers? Round (\d+)/i, 'LR$1')
    .replace(/Round (\d+)/i, 'R$1')
}

const deltaBadge = (d) => (d == null ? ''
  : d === 0 ? '<span class="delta delta--even">on seed</span>'
  : d > 0 ? `<span class="delta delta--up">+${d} over seed</span>`
  : `<span class="delta delta--down">−${-d} under seed</span>`)

// tap-through to the tournament on start.gg (event slug first, tournament
// slug as fallback — compactEvent carries both)
const GG_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>`
const ggUrl = (ev) => (ev?.slug ? `https://start.gg/${ev.slug}`
  : ev?.tslug ? `https://start.gg/${ev.tslug}` : null)
const ggBtn = (ev) => {
  const url = ggUrl(ev)
  return url ? `<button class="gg-link" data-gg="${esc(url)}"
    aria-label="Open on start.gg">${GG_ICON}</button>` : ''
}
const wireGg = (rootEl) => {
  rootEl.querySelectorAll('.gg-link').forEach((b) => b.addEventListener('click', (e) => {
    e.stopPropagation()
    window.open(b.dataset.gg, '_blank', 'noopener,noreferrer')
  }))
}

// gold / silver / bronze accents for podium placements (desktop parity)
const placeCls = (p) => (p === 1 ? 'tm-place--gold' : p === 2 ? 'tm-place--silver'
  : p === 3 ? 'tm-place--bronze' : '')

// same 7px winbar the stats tab uses — duplicated on purpose, the tabs share
// a pattern, not a component
function winbar(wr, n) {
  if (wr == null || !n) return '<span class="winbar winbar--lg"><b></b></span>'
  const cls = wr >= 0.5 ? 'is-up' : 'is-down'
  return `<span class="winbar winbar--lg"><i class="${cls}" style="width:${(wr * 100).toFixed(1)}%"></i><b></b></span>`
}

function sectionEl(title, sub) {
  return el(`<section class="section">
    <header class="section-head"><h3>${esc(title)}</h3>${sub ? `<span>${esc(sub)}</span>` : ''}</header>
  </section>`)
}

// Loss quality — the consoling stat every player checks after a bracket:
// WHO knocked you out, and how far did they go? (desktop parity)
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

// ── one set as one line: W/L chip · opponent+seed · badges · score · round ──
function setRowHtml(s, replayMap) {
  const linked = replayMap?.get(s.id) || []
  const score = scoreLabel(s)
  return `<button class="set-row" data-set="${s.id}" ${linked.length ? '' : 'disabled'}>
    <span class="set-wl ${s.won ? 'w' : 'l'}">${s.won ? 'W' : 'L'}</span>
    <span class="set-opp">${esc(s.opp?.name || '?')}
      ${s.opp?.seed != null ? `<small>seed ${s.opp.seed}</small>` : ''}</span>
    ${s.upset ? `<span class="tm-badge" title="Upset factor ${s.uf}">UF ${s.uf}</span>` : ''}
    ${s.gotUpset ? '<span class="tm-badge tm-badge--down">UPSET</span>' : ''}
    ${linked.length ? `<span class="set-replays">▶ ${linked.length}</span>` : ''}
    <span class="set-score">${esc(score)}</span>
    <span class="set-round">${esc(shortRound(s.round_text))}</span>
  </button>`
}

// ── THE RUN: the latest event, expanded and promoted ──────────────────────
function runSectionEl(run, replayMap, wireSets) {
  const ev = run.event
  const matched = run.sets.reduce((n, s) => n + (replayMap.get(s.id)?.length || 0), 0)
  const quality = lossQuality(run)
  const sec = el(`<section class="section tm-run">
    <header class="section-head"><h3>The run</h3>
      <span>${esc(dateOf(run.lastAt))}${ev.city ? ` · ${esc(ev.city)}` : ''}${ev.online ? ' · online' : ''}</span>
    </header>
    <div class="tm-run-title" style="display:flex;align-items:center;gap:6px">
      <span style="flex:1 1 auto;min-width:0">
        <span class="t">${esc(ev.tournament || ev.name || '')}</span>
        <span class="s">${esc(ev.name || '')}</span>
      </span>
      ${ggBtn(ev)}
    </div>
    <div class="tm-run-hero">
      <span class="tm-run-place ${placeCls(run.placement)}">${ordinal(run.placement)}</span>
      <span class="tm-run-sub">
        <span>of ${num(ev.entrants)} entrants</span>
        <span>${run.seed != null ? `seeded ${run.seed}` : 'seed unknown'} · went ${run.wins}–${run.losses}</span>
      </span>
      ${deltaBadge(run.delta)}
    </div>
    ${quality ? `<p class="tm-run-insight">${esc(quality)}</p>` : ''}
    <div class="sets">${run.sets.map((s) => setRowHtml(s, replayMap)).join('')}</div>
    ${matched ? `<p class="footnote">▶ ${num(matched)} local replay${matched > 1 ? 's' : ''} matched this bracket by time — tap a set to watch the actual games.</p>` : ''}
  </section>`)
  wireSets(sec)
  wireGg(sec)
  return sec
}

// ── trajectory strip: seedDelta per event, green above / red below the line ──
const TRAJ_MAX = 40

function trajSectionEl(allSeries) {
  const truncated = allSeries.length > TRAJ_MAX
  const series = truncated ? allSeries.slice(-TRAJ_MAX) : allSeries
  const sec = sectionEl('Paper vs bracket',
    truncated ? `seed vs finish · last ${TRAJ_MAX} events` : 'seed vs finish, every event')
  if (series.length < 2) {
    sec.appendChild(el('<p class="footnote">Play a couple more seeded events and your seed-vs-finish chart appears here.</p>'))
    return sec
  }
  const maxAbs = Math.max(1, ...series.map((ev) => Math.abs(ev.delta)))
  const bars = el(`<div class="tm-traj">${series.map((ev) => {
    const h = Math.max(4, (Math.abs(ev.delta) / maxAbs) * 46)
    const cls = ev.delta > 0 ? 'is-up' : ev.delta < 0 ? 'is-down' : 'is-even'
    return `<span class="tm-traj-col" data-k="${esc(String(ev.key))}">
      <span class="tm-traj-bar ${cls}"${ev.delta === 0 ? '' : ` style="height:${h.toFixed(1)}%"`}></span>
    </span>`
  }).join('')}</div>`)
  const hint = '<span class="hint">Tap a bar: green = beat your seed, red = fell short</span>'
  const readout = el(`<div class="chart-readout">${hint}</div>`)
  const byKey = new Map(series.map((ev) => [String(ev.key), ev]))
  let sel = null
  bars.addEventListener('click', (e) => {
    const col = e.target.closest('.tm-traj-col')
    if (!col) return
    sel = sel === col.dataset.k ? null : col.dataset.k
    for (const x of bars.querySelectorAll('.tm-traj-col.is-sel')) x.classList.remove('is-sel')
    const ev = sel != null ? byKey.get(sel) : null
    if (ev) {
      col.classList.add('is-sel')
      readout.innerHTML = `<b>${esc(ev.event.tournament || ev.event.name || '')}</b>`
        + ` · seed ${ev.seed ?? '?'} → placed ${ordinal(ev.placement)}`
    } else {
      readout.innerHTML = hint
    }
  })
  sec.append(bars, readout)
  return sec
}

// ── best wins: proudest scalps ranked by upset factor ─────────────────────
function bestWinsEl(scalps) {
  const sec = sectionEl('Best wins', 'ranked by upset factor')
  if (!scalps.length) {
    sec.appendChild(el('<p class="footnote">No seed upsets synced yet — go steal a bracket spot.</p>'))
    return sec
  }
  sec.appendChild(el(`<div>${scalps.map((s) => `
    <div class="srow tm-tworow">
      <span class="tm-badge" title="Upset factor ${s.uf}">UF ${s.uf}</span>
      <span class="tm-rowmain">
        <span class="n">${esc(s.opp.name || '?')}${s.opp.seed != null ? `<small>seed ${s.opp.seed}</small>` : ''}</span>
        <span class="e">${esc(s.eventInfo.tournament || s.eventInfo.name || '')} · ${esc(dateOf(s.completed_at))}</span>
      </span>
      <span class="set-score">${esc(scoreLabel(s))}</span>
    </div>`).join('')}</div>`))
  return sec
}

// ── demons: the people who keep beating you ───────────────────────────────
function demonsEl(list) {
  const sec = sectionEl('Bracket demons', 'they keep sending you to losers')
  if (!list.length) {
    sec.appendChild(el('<p class="footnote">Nobody has a winning record on you (2+ sets). Keep it that way.</p>'))
    return sec
  }
  sec.appendChild(el(`<div>${list.map((r) => `
    <div class="srow tm-tworow">
      <span class="tm-demon-rec">${r.losses}–${r.wins}</span>
      <span class="tm-rowmain">
        <span class="n">${esc(r.name || '?')}</span>
        <span class="e">${r.wins === 0 ? 'never beaten' : `last met ${esc(dateOf(r.lastAt))}`}</span>
      </span>
    </div>`).join('')}</div>`))
  return sec
}

// ── full head-to-head list, collapsed to the top 8 by sets played ─────────
const H2H_SHOWN = 8

function h2hEl(h2h) {
  const sorted = h2h.slice().sort((a, b) => (b.wins + b.losses) - (a.wins + a.losses)
    || (b.lastAt || 0) - (a.lastAt || 0))
  const sec = sectionEl('Head-to-head',
    sorted.length ? `${num(sorted.length)} opponents · singles sets` : 'singles sets')
  if (!sorted.length) {
    sec.appendChild(el('<p class="footnote">No singles head-to-heads synced yet.</p>'))
    return sec
  }
  const host = el('<div></div>')
  let showAll = false
  const draw = () => {
    const visible = showAll ? sorted : sorted.slice(0, H2H_SHOWN)
    host.innerHTML = visible.map((r) => {
      const total = r.wins + r.losses
      const wr = total ? r.wins / total : null
      return `<div class="srow srow--lg">
        <span class="srow-name">${esc(r.name || '?')}</span>
        <span class="srow-games">${num(total)}</span>
        ${winbar(wr, total)}
        <span class="tm-h2h-rec"><span class="is-up">${r.wins}</span>–<span class="is-down">${r.losses}</span></span>
      </div>`
    }).join('')
    if (sorted.length > H2H_SHOWN) {
      const btn = el(`<button class="show-all">${showAll ? 'Show fewer' : `Show all ${num(sorted.length)}`}</button>`)
      btn.addEventListener('click', () => { showAll = !showAll; draw() })
      host.appendChild(btn)
    }
  }
  draw()
  sec.appendChild(host)
  return sec
}

// ── past events: the existing compact cards, collapsed, tap to expand ─────
function eventCard(ev, expanded) {
  return `<section class="section event-card" data-ev="${ev.key}">
    <div class="event-top">
      <span class="event-place">${ordinal(ev.placement)}<small>of ${num(ev.event.entrants)}</small></span>
      <span class="event-name">
        <span class="t">${esc(ev.event.tournament || ev.event.name || '')}</span>
        <span class="s">${esc(ev.event.name || '')}${ev.event.city ? ` · ${esc(ev.event.city)}` : ''}
          · ${esc(dateOf(ev.event.start_at))}</span>
      </span>
      ${deltaBadge(ev.delta)}
      ${ggBtn(ev.event)}
    </div>
    ${expanded ? '<div class="sets">__SETS__</div>' : ''}
  </section>`
}

const PAST_SHOWN = 12

export function renderTournaments(root, games, onWatchGame) {
  root.innerHTML = ''
  root.appendChild(el('<div class="head frosted"><div><h1>Tournaments</h1></div></div>'))
  const pagebody = el('<div class="pagebody"></div>')
  root.appendChild(pagebody)

  const slug = getSlug()
  if (!slug) {
    const hero = el('<div class="connect-hero"></div>')
    const row = el(`<div class="tourney-connect">
      <input type="text" placeholder="start.gg profile URL or slug"
             autocapitalize="off" spellcheck="false">
      <button>Connect</button></div>`)
    const input = row.querySelector('input')
    row.querySelector('button').addEventListener('click', () => {
      const s = parseSlug(input.value)
      if (!s) return
      setSlug(s)
      prefsSet({ startgg_slug: s }).catch(() => {})   // other devices inherit it
      renderTournaments(root, games, onWatchGame)
    })
    hero.appendChild(row)
    pagebody.append(hero)
    // The slug may already live in the vault (typed on another device) —
    // adopt it silently and skip the form.
    prefsGet().then((p) => {
      if (p?.startgg_slug && !getSlug()) {
        setSlug(p.startgg_slug)
        renderTournaments(root, games, onWatchGame)
      }
    }).catch(() => {})
    return
  }

  const body = el('<div></div>')
  pagebody.appendChild(body)

  const cached = readCache()

  function draw(data, note) {
    body.innerHTML = ''
    const profile = el(`<div class="tourney-profile">
      <span class="tag">${esc(data?.gamer_tag || slug)}</span>
      <span class="slug">start.gg/user/${esc(slug)}</span>
      <button class="disconnect">Disconnect</button>
    </div>`)
    profile.querySelector('.disconnect').addEventListener('click', () => {
      setSlug(''); writeCache(null)
      prefsSet({ startgg_slug: null }).catch(() => {})
      renderTournaments(root, games, onWatchGame)
    })
    body.appendChild(profile)
    if (note) body.appendChild(el(`<p class="footnote">${esc(note)}</p>`))
    if (!data?.sets?.length) {
      body.appendChild(el('<p class="empty">No tournament sets found yet.</p>'))
      return
    }

    const events = groupEvents(data.sets, data.player_id)
    if (!events.length) {
      body.appendChild(el('<p class="empty">No completed events yet.</p>'))
      return
    }

    // attach local replays to sets — the whole cached library is in memory,
    // shaped close enough to the desktop rows for matchReplaysToSets
    let replayMap = new Map()
    try {
      const asRows = games.map((g) => ({
        id: g.content_hash, start_at: g.start_at, stage: g.stage,
        duration_s: g.duration_s, players: g.players, user_port: g.user_port,
        result: g.result, is_teams: g.is_teams,
      }))
      replayMap = matchReplaysToSets(
        events.flatMap((ev) => ev.sets), asRows) || new Map()
    } catch { /* matcher is best-effort */ }

    // sets with linked replays are tappable everywhere they appear
    const wireSets = (card) => {
      card.addEventListener('click', (e) => {
        const btn = e.target.closest('.set-row')
        if (!btn || btn.disabled) return
        const linked = replayMap.get(Number(btn.dataset.set))
          || replayMap.get(btn.dataset.set) || []
        const first = linked[0]
        if (!first) return
        const g = games.find((x) => x.content_hash === (first.id ?? first))
        if (g) onWatchGame(g)
      })
    }

    const totalWins = events.reduce((n, ev) => n + ev.wins, 0)
    const totalLosses = events.reduce((n, ev) => n + ev.losses, 0)
    body.appendChild(el(`<div class="statline">
      <span class="stat"><span class="stat-num">${num(events.length)}</span><span class="stat-label">events</span></span>
      <span class="stat-div"></span>
      <span class="stat"><span class="stat-num is-up">${num(totalWins)}</span><span class="stat-label">set wins</span></span>
      <span class="stat-div"></span>
      <span class="stat"><span class="stat-num is-down">${num(totalLosses)}</span><span class="stat-label">set losses</span></span>
    </div>`))

    // the desktop derivations, all from the same event groups
    const h2h = headToHead(events)
    const demonList = demons(h2h)
    const scalps = bestWins(events, 6)
    const series = trajectory(events)

    body.appendChild(runSectionEl(events[0], replayMap, wireSets))
    body.appendChild(trajSectionEl(series))
    body.appendChild(bestWinsEl(scalps))
    body.appendChild(demonsEl(demonList))
    body.appendChild(h2hEl(h2h))

    // ── past events ──
    const past = events.slice(1)
    if (past.length) {
      body.appendChild(el(`<h2 class="tm-subhead">Past events <span>${num(past.length)}</span></h2>`))
      const list = el('<div></div>')
      body.appendChild(list)
      const expanded = new Set()
      let showAllPast = false
      const drawPast = () => {
        list.innerHTML = ''
        const visible = showAllPast ? past : past.slice(0, PAST_SHOWN)
        for (const ev of visible) {
          const isOpen = expanded.has(ev.key)
          let html = eventCard(ev, isOpen)
          if (isOpen) {
            html = html.replace('__SETS__',
              ev.sets.map((s) => setRowHtml(s, replayMap)).join(''))
          }
          const card = el(html)
          card.querySelector('.event-top').addEventListener('click', () => {
            if (expanded.has(ev.key)) expanded.delete(ev.key)
            else expanded.add(ev.key)
            drawPast()
          })
          wireSets(card)
          wireGg(card)
          list.appendChild(card)
        }
        if (past.length > PAST_SHOWN) {
          const btn = el(`<button class="show-all">${showAllPast ? 'Show fewer' : `Show all ${num(past.length)} events`}</button>`)
          btn.addEventListener('click', () => { showAllPast = !showAllPast; drawPast() })
          list.appendChild(btn)
        }
      }
      drawPast()
    } else {
      body.appendChild(el('<p class="footnote" style="text-align:center">Your first synced event — more runs stack up here.</p>'))
    }

    // Required attribution (start.gg ToS §2.3): visible credit, unaltered name.
    body.appendChild(el(`<p class="tm-attrib">Tournament data provided by
      <a href="https://www.start.gg" target="_blank" rel="noopener">start.gg</a>
      — your results, always free.</p>`))
  }

  if (cached && cached.sets) {
    draw(cached, null)
    // quiet background refresh when stale (15+ min)
    if (Date.now() - (cached.synced_at || 0) > 15 * 60 * 1000) {
      syncSets(slug, cached).then((d) => draw(d, null)).catch(() => {})
    }
  } else {
    body.appendChild(el('<p class="spin">Syncing your sets from start.gg…</p>'))
    syncSets(slug, null).then((d) => draw(d, null)).catch((e) => {
      body.innerHTML = ''
      toast(`start.gg sync failed: ${e.message}`)
      body.appendChild(el('<p class="empty">Could not reach start.gg. Try again later.</p>'))
    })
  }
}
