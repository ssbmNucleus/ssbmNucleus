// Stats tab — the desktop StatsPage's core, recomputed client-side from the
// cached library. Same semantics: result/user_port come precomputed from the
// desktop's inference (never re-derived here), sessions break on a 45-minute
// gap, the salt report reads LRAS endings.
//
// The rendering is mobile-first rather than a desktop port: the overview leads
// with one big winrate (the one-glance answer) instead of five equal numbers,
// filters live in the games-tab bottom sheet instead of a chip strip, and the
// bar charts are tappable — desktop leans on hover tooltips that simply don't
// exist on touch, so each chart gets one shared readout line under it instead.
import { charName, stageName } from '../../../app/frontend/src/shared/data/meleeNames'
import { el, esc, stockSrc, stageSrc, monthLabel, shortDate, pct, num, sheet } from './ui'

export const state = { myChar: '', start: '', end: '' }

const SESSION_GAP_MS = 45 * 60 * 1000
// the 6 tournament-legal stages, same shortlist the desktop collapses to
const LEGAL_STAGES = new Set([2, 3, 8, 28, 31, 32])

const me = (g) => (g.user_port != null
  ? (g.players || []).find((p) => p.port === g.user_port) : null)
const opp = (g) => (g.user_port != null
  ? (g.players || []).find((p) => p.port !== g.user_port) : null)

export function compute(games, f) {
  const filtered = games.filter((g) => {
    // Stats are scoped harder than the library is. The desktop's row set
    // (backend/tracker/stats/aggregate.py:_fetch_rows) is 2-player singles
    // against a HUMAN opponent, attributed to one of the user's codes; the
    // library filter in main.js keeps doubles, CPU practice and unattributed
    // games because they are still watchable. Without these four predicates
    // every number on the tab is inflated by games the desktop never counted:
    // games, playtime, active days, stages, months, hours, opponents, rivals.
    const players = g.players || []
    if (players.length !== 2 || g.is_teams) return false
    if (!players.every((p) => p.type === 0)) return false
    if (g.user_port == null) return false
    const m = me(g)
    if (f.myChar !== '' && (!m || String(m.character) !== f.myChar)) return false
    if (f.start && (!g.start_at || g.start_at.slice(0, 10) < f.start)) return false
    if (f.end && (!g.start_at || g.start_at.slice(0, 10) > f.end)) return false
    return true
  })

  const o = { games: filtered.length, wins: 0, losses: 0, playtime_s: 0 }
  const oppCodes = new Set()
  const days = new Set()
  const matchups = new Map()   // opp char -> rec
  const myChars = new Map()
  const stages = new Map()
  const months = new Map()
  const hours = new Map()
  const rivals = new Map()     // opp code -> rec
  const salt = new Map()       // opp code -> {opp_quits, my_quits, ...}
  let saltOpp = 0, saltMine = 0

  const rec = (map, key) => {
    let r = map.get(key)
    if (!r) { r = { games: 0, wins: 0, losses: 0 }; map.set(key, r) }
    r.games += 1
    return r
  }
  const score = (r, g) => {
    if (g.result === 'win') r.wins += 1
    else if (g.result === 'loss') r.losses += 1
  }

  for (const g of filtered) {
    o.playtime_s += g.duration_s || 0
    if (g.result === 'win') o.wins += 1
    else if (g.result === 'loss') o.losses += 1
    if (g.start_at) {
      days.add(g.start_at.slice(0, 10))
      score(rec(months, g.start_at.slice(0, 7)), g)
      const d = new Date(g.start_at)
      if (!Number.isNaN(d.getTime())) score(rec(hours, d.getHours()), g)
    }
    // Salt: LRAS ("No Contest") endings, attributed to whoever pressed it.
    // lras_initiator is a 0-BASED port index (backend/tracker/
    // slp_meta.py:_parse_game_end, same convention as placements), so it is
    // compared against port - 1 like the desktop does (stats.py:130-135).
    // Comparing it to the 1-based port swapped the two lists outright in the
    // ordinary P1-vs-P2 game: "they quit on me" was reported as "I quit".
    // The totals are also counted for every game, not only games whose
    // opponent has a connect code — otherwise the headline number silently
    // drops every quit by a code-less opponent.
    const lras = g.end_method === 7 && g.lras_initiator != null ? g.lras_initiator : null
    const quitByMe = lras != null && lras === g.user_port - 1
    const quitByOpp = lras != null && !quitByMe
    if (quitByMe) saltMine += 1
    else if (quitByOpp) saltOpp += 1

    const m = me(g), op = opp(g)
    if (m && m.character != null) score(rec(myChars, m.character), g)
    if (op) {
      // teams games are out of scope entirely now, so a matchup row is always
      // a real 1v1 character matchup
      if (op.character != null) score(rec(matchups, op.character), g)
      const code = op.code
      if (code) {
        oppCodes.add(code)
        const r = rec(rivals, code)
        score(r, g)
        if (!r.name && op.name) r.name = op.name
        r.chars = r.chars || new Map()
        if (op.character != null) r.chars.set(op.character, (r.chars.get(op.character) || 0) + 1)
        if (!r.last_at || (g.start_at || '') > r.last_at) r.last_at = g.start_at
        // only the per-opponent breakdown needs a code to hang the quit on
        if (quitByMe || quitByOpp) {
          const s = salt.get(code) || { opp_quits: 0, my_quits: 0 }
          if (quitByMe) s.my_quits += 1
          else s.opp_quits += 1
          salt.set(code, s)
        }
      }
    }
  }
  o.opponents = oppCodes.size
  o.active_days = days.size
  o.winrate = o.wins + o.losses ? o.wins / (o.wins + o.losses) : null

  // sessions: sorted by time, break on the 45-minute gap between game STARTS —
  // the desktop measures start-to-start (stats.py:204). Measuring from the
  // previous game's end instead makes every gap shorter by that game's
  // duration, which merges sessions the desktop splits and shifts both the
  // session count and the games-per-session average.
  const timed = filtered.filter((g) => g.start_at)
    .sort((a, b) => a.start_at.localeCompare(b.start_at))
  const sessions = []
  let cur = null
  let lastT = null
  for (const g of timed) {
    const t = Date.parse(g.start_at)
    if (Number.isNaN(t)) continue
    if (cur == null || t - lastT > SESSION_GAP_MS) { cur = []; sessions.push(cur) }
    cur.push(g)
    lastT = t
  }
  const lens = sessions.map((s) => s.length).sort((a, b) => a - b)
  const sess = {
    count: sessions.length,
    avg_games: sessions.length ? Math.round(timed.length / sessions.length) : null,
    median_games: lens.length ? lens[Math.floor(lens.length / 2)] : null,
    longest: lens.length ? lens[lens.length - 1] : null,
  }

  const finish = (map) => [...map.entries()].map(([k, r]) => ({
    key: k, ...r,
    winrate: r.wins + r.losses ? r.wins / (r.wins + r.losses) : null,
  }))

  const rivalRows = finish(rivals).filter((r) => r.games >= 5)
    .sort((a, b) => b.games - a.games)
    .map((r) => ({
      ...r,
      top_char: r.chars ? [...r.chars.entries()].sort((x, y) => y[1] - x[1])[0]?.[0] : null,
    }))

  const saltRows = (dir) => [...salt.entries()]
    .map(([code, s]) => {
      const rv = rivals.get(code) || {}
      return { code, name: rv.name, quits: s[dir], both: s,
               games: rv.games || 0, wins: rv.wins || 0, losses: rv.losses || 0 }
    })
    .filter((r) => r.quits > 0)
    // desktop order (stats.py:254-255): most quits first, ties broken by how
    // FEW games it took to earn them, capped at 100 — without the tiebreak the
    // order of equally-salty opponents is whatever Map iteration happened to be
    .sort((a, b) => b.quits - a.quits || a.games - b.games)
    .slice(0, 100)

  return {
    overview: o,
    sessions: sess,
    matchups: finish(matchups).sort((a, b) => b.games - a.games),
    my_characters: finish(myChars).sort((a, b) => b.games - a.games),
    stages: finish(stages_fill(filtered)).sort((a, b) => b.games - a.games),
    months: finish(months).sort((a, b) => String(a.key).localeCompare(String(b.key))),
    hours: finish(hours),
    rivals: rivalRows,
    salt: { saltiest: saltRows('opp_quits'), ragebaiters: saltRows('my_quits'),
            opp_quits: saltOpp, my_quits: saltMine },
  }
}

// stages need their own pass (kept out of the main loop for clarity)
function stages_fill(filtered) {
  const stages = new Map()
  for (const g of filtered) {
    if (g.stage == null) continue
    let r = stages.get(g.stage)
    if (!r) { r = { games: 0, wins: 0, losses: 0 }; stages.set(g.stage, r) }
    r.games += 1
    if (g.result === 'win') r.wins += 1
    else if (g.result === 'loss') r.losses += 1
  }
  return stages
}

function playtimeLabel(seconds) {
  if (!seconds) return '—'
  const h = seconds / 3600
  return h >= 100 ? `${Math.round(h)} h` : `${h.toFixed(1)} h`
}

// ── rendering ─────────────────────────────────────────────────────────────

// same quiet icon as games.js — duplicated on purpose, the two tabs share a
// pattern, not a component
const FILTER_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round"><path d="M4 6h16M7 12h10M10 18h4"/></svg>`

// chart selections live at module scope so switching tabs (which re-renders
// from scratch) doesn't wipe the bar the user was looking at
const view = { sel: { month: null, hour: null } }

function winbar(winrate, games) {
  // --lg variant: the 5px desktop bar reads as a hairline on a phone
  if (winrate == null || !games) return '<span class="winbar winbar--lg"><b></b></span>'
  const cls = winrate >= 0.5 ? 'is-up' : 'is-down'
  return `<span class="winbar winbar--lg"><i class="${cls}" style="width:${(winrate * 100).toFixed(1)}%"></i><b></b></span>`
}

function breakdown(entries, { icon, label, initial = 8, defaultFilter = null }) {
  const host = el('<div></div>')
  let showAll = false
  const draw = () => {
    const short = defaultFilter && !showAll ? entries.filter(defaultFilter) : entries
    const visible = showAll ? entries : short.slice(0, initial)
    host.innerHTML = visible.map((e) => `
      <div class="srow srow--lg">
        ${icon(e)}
        <span class="srow-name">${esc(label(e))}</span>
        <span class="srow-games">${num(e.games)}</span>
        ${winbar(e.winrate, e.wins + e.losses)}
        <span class="srow-rate ${e.winrate == null ? '' : e.winrate >= 0.5 ? 'is-up' : 'is-down'}">${pct(e.winrate)}</span>
      </div>`).join('')
    if (entries.length > visible.length || showAll) {
      const btn = el(`<button class="show-all">${showAll ? 'Show fewer' : `Show all ${entries.length}`}</button>`)
      btn.addEventListener('click', () => { showAll = !showAll; draw() })
      host.appendChild(btn)
    }
  }
  draw()
  return host
}

const hourLabel = (h) => (h === 0 ? '12a' : h === 12 ? '12p' : h < 12 ? `${h}a` : `${h - 12}p`)

// month entries padded so calendar gaps stay visible; ticks on year boundaries
function monthCols(months) {
  if (!months.length) return []
  const filled = []
  let [y, m] = String(months[0].key).split('-').map(Number)
  const last = String(months[months.length - 1].key)
  const byKey = Object.fromEntries(months.map((mo) => [String(mo.key), mo]))
  for (;;) {
    const key = `${y}-${String(m).padStart(2, '0')}`
    filled.push(byKey[key] || { key, games: 0, wins: 0, losses: 0, winrate: null })
    if (key === last || filled.length > 240) break
    m += 1
    if (m > 12) { m = 1; y += 1 }
  }
  return filled.map((mo, i) => ({
    ...mo,
    tick: i === 0 || String(filled[i - 1].key).slice(0, 4) !== String(mo.key).slice(0, 4)
      ? String(mo.key).slice(2, 4) : null,
  }))
}

// ── Activity, the Health-app way: a period switcher and FEW FAT BARS, never
// the whole history as 3px slivers. 6M/1Y = recent months; All = one bar per
// year. The latest bar with games starts selected so the readout leads with
// an answer instead of an instruction.
const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function periodCols(months, period) {
  const all = monthCols(months)                   // gap-filled, oldest first
  if (period === 'all') {
    const byYear = new Map()
    for (const mo of all) {
      const y = String(mo.key).slice(0, 4)
      const r = byYear.get(y) || { key: y, games: 0, wins: 0, losses: 0 }
      r.games += mo.games; r.wins += mo.wins; r.losses += mo.losses
      byYear.set(y, r)
    }
    return [...byYear.values()].map((r) => ({
      ...r,
      winrate: r.wins + r.losses ? r.wins / (r.wins + r.losses) : null,
      tick: r.key,
      label: r.key,
    }))
  }
  const n = period === '6m' ? 6 : 12
  return all.slice(-n).map((mo) => ({
    ...mo,
    tick: MONTH_SHORT[Number(String(mo.key).slice(5, 7)) - 1],
    label: monthLabel(String(mo.key)),
  }))
}

/** Small segmented pill control (6M | 1Y | All), Health-style. */
function segmented(optionsList, value, onChange) {
  const root = el(`<div class="seg">${optionsList.map(([v, l]) =>
    `<button class="${v === value ? 'is-on' : ''}" data-v="${v}">${esc(l)}</button>`).join('')}</div>`)
  root.addEventListener('click', (e) => {
    const b = e.target.closest('button')
    if (!b || b.dataset.v === value) return
    onChange(b.dataset.v)
  })
  return root
}

function hourCols(hours) {
  const by = new Map(hours.map((h) => [h.key, h]))
  return Array.from({ length: 24 }, (_, i) => ({
    ...(by.get(i) || { key: i, games: 0, wins: 0, losses: 0, winrate: null }),
    tick: i % 6 === 0 ? hourLabel(i) : null,
  }))
}

/** A bar chart the finger can interrogate: tap a column and one shared readout
 * line under the chart shows label · games · W–L · winrate. No floating
 * tooltips — there is nothing to hover with. Tapping the same bar clears it.
 * Taps are delegated to the container so even 12px-wide columns are easy to
 * hit (the whole 72px-tall column strip is the target, not the bar itself). */
function tapChart(cols, selKey, labelOf, opts = {}) {
  // lead with an answer: when nothing's selected, preselect the most
  // interesting bar (latest with games, or the peak) instead of a hint
  if (view.sel[selKey] == null && opts.defaultKey != null) {
    view.sel[selKey] = String(opts.defaultKey)
  }
  if (view.sel[selKey] != null && !cols.some((c) => String(c.key) === String(view.sel[selKey]))) {
    view.sel[selKey] = opts.defaultKey != null ? String(opts.defaultKey) : null
  }
  const max = Math.max(1, ...cols.map((c) => c.games))
  const host = el('<div class="chart-bleed"></div>')
  const bars = el(`<div class="bars bars--tap ${opts.fat ? 'bars--fat' : ''}">${cols.map((c) => `
    <span class="col${String(view.sel[selKey]) === String(c.key) ? ' is-sel' : ''}"
          data-k="${esc(String(c.key))}">
      <span class="bar" style="height:${c.games ? Math.max(2, (100 * c.games) / max) : 0}%"></span>
      ${c.tick != null ? `<span class="tick">${esc(c.tick)}</span>` : ''}
    </span>`).join('')}</div>`)
  const readout = el('<div class="chart-readout"></div>')
  const byKey = new Map(cols.map((c) => [String(c.key), c]))
  const draw = () => {
    const c = byKey.get(String(view.sel[selKey]))
    if (!c) { readout.innerHTML = '<span class="hint">Tap a bar for details</span>'; return }
    const scored = (c.wins || 0) + (c.losses || 0)
    readout.innerHTML = `<b>${esc(labelOf(c))}</b> · ${num(c.games)} game${c.games === 1 ? '' : 's'}`
      + (scored ? ` · <span class="is-up">${num(c.wins)}</span>–<span class="is-down">${num(c.losses)}</span>`
        + ` · ${pct(c.winrate != null ? c.winrate : c.wins / scored)}` : '')
  }
  bars.addEventListener('click', (e) => {
    const col = e.target.closest('.col')
    if (!col) return
    view.sel[selKey] = view.sel[selKey] === col.dataset.k ? null : col.dataset.k
    for (const x of bars.querySelectorAll('.col.is-sel')) x.classList.remove('is-sel')
    if (view.sel[selKey] != null) col.classList.add('is-sel')
    draw()
  })
  draw()
  host.append(bars, readout)
  return host
}

function section(title, sub, child) {
  const s = el(`<section class="section">
    <header class="section-head"><h3>${esc(title)}</h3>${sub ? `<span>${esc(sub)}</span>` : ''}</header>
  </section>`)
  s.appendChild(child)
  return s
}

// ── filter sheet + pills (the games.js chrome, scoped to stats' two filters) ──

const filterCount = () => (state.myChar !== '' ? 1 : 0) + (state.start || state.end ? 1 : 0)

function openFilterSheet(charFacet, onChange) {
  const sh = sheet('Filter stats')

  sh.body.appendChild(el('<div class="sheet-group">My character</div>'))
  const row = el('<div class="sheet-chiprow"></div>')
  for (const [c, n] of charFacet) {
    const on = state.myChar === String(c)
    const chip = el(`<button class="sheet-chip ${on ? 'is-on' : ''}">
      <img src="${stockSrc(c, 0)}" alt="" onerror="this.remove()">${esc(charName(c))} (${n})</button>`)
    chip.addEventListener('click', () => {
      state.myChar = on ? '' : String(c)
      onChange()
      sh.close()
    })
    row.appendChild(chip)
  }
  sh.body.appendChild(row)

  sh.body.appendChild(el('<div class="sheet-group">Date range</div>'))
  const dates = el(`<div class="sheet-dates">
    <input type="date" value="${state.start}" aria-label="From">
    <input type="date" value="${state.end}" aria-label="To"></div>`)
  const [dS, dE] = dates.querySelectorAll('input')
  dS.addEventListener('change', () => { state.start = dS.value; onChange() })
  dE.addEventListener('change', () => { state.end = dE.value; onChange() })
  sh.body.appendChild(dates)

  if (filterCount() > 0) {
    const clear = el('<button class="wide" style="margin-top:12px;color:var(--danger)">Clear filters</button>')
    clear.addEventListener('click', () => {
      state.myChar = ''; state.start = ''; state.end = ''
      onChange()
      sh.close()
    })
    sh.body.appendChild(clear)
  }
}

function pillsHtml() {
  const out = []
  if (state.myChar !== '') {
    out.push(`<span class="pill" data-k="myChar"><b>Me:</b> ${esc(charName(Number(state.myChar)))}<span class="x">×</span></span>`)
  }
  if (state.start || state.end) {
    out.push(`<span class="pill" data-k="dates">${esc(`${state.start || '…'} → ${state.end || '…'}`)}<span class="x">×</span></span>`)
  }
  return out.join('')
}

export function renderStats(root, games) {
  root.innerHTML = ''

  const head = el(`<div class="head frosted">
    <div><h1>Stats</h1><div class="sub"></div></div>
    <span class="grow"></span>
    <button class="headbtn" id="st-filter" aria-label="Filter">${FILTER_ICON}</button>
  </div>`)
  root.appendChild(head)
  const sub = head.querySelector('.sub')

  const pagebody = el('<div class="pagebody"></div>')
  root.appendChild(pagebody)

  // facet from the unfiltered library, so picking a character never hides the
  // other options
  const chars = new Map()
  for (const g of games) {
    const m = me(g)
    if (m && m.character != null) chars.set(m.character, (chars.get(m.character) || 0) + 1)
  }
  const charFacet = [...chars.entries()].sort((a, b) => b[1] - a[1])

  const pills = el('<div class="pills"></div>')
  pagebody.appendChild(pills)
  pills.addEventListener('click', (e) => {
    const pill = e.target.closest('.pill')
    if (!pill) return
    if (pill.dataset.k === 'dates') { state.start = ''; state.end = '' }
    else state.myChar = ''
    refresh()
  })

  const body = el('<div></div>')
  pagebody.appendChild(body)

  const filterBtn = head.querySelector('#st-filter')
  const syncFilterDot = () => {
    filterBtn.querySelector('.dot')?.remove()
    if (filterCount() > 0) filterBtn.appendChild(el('<span class="dot"></span>'))
  }
  const refresh = () => { syncFilterDot(); pills.innerHTML = pillsHtml(); drawBody() }
  filterBtn.addEventListener('click', () => openFilterSheet(charFacet, refresh))
  syncFilterDot()
  pills.innerHTML = pillsHtml()

  function drawBody() {
    const s = compute(games, state)
    const o = s.overview
    sub.textContent = filterCount() > 0
      ? `${num(o.games)} of ${num(games.length)} games`
      : `${num(games.length)} games`
    body.innerHTML = ''
    if (!o.games) {
      body.appendChild(el('<p class="empty">No games in this period.</p>'))
      return
    }

    // The desktop's editorial statline, per user preference over the big
    // winrate hero: five values split by hairline dividers, winrate carrying
    // the one status color, the rest quiet.
    const wrCls = o.winrate == null ? '' : o.winrate >= 0.5 ? 'is-up' : 'is-down'
    body.appendChild(el(`<div class="statline">
      <span class="stat"><span class="stat-num">${num(o.games)}</span><span class="stat-label">games</span></span>
      <span class="stat-div"></span>
      <span class="stat"><span class="stat-num ${wrCls}">${pct(o.winrate)}</span><span class="stat-label">won</span></span>
      <span class="stat-div"></span>
      <span class="stat"><span class="stat-num">${playtimeLabel(o.playtime_s)}</span><span class="stat-label">played</span></span>
      <span class="stat-div"></span>
      <span class="stat"><span class="stat-num">${num(o.opponents)}</span><span class="stat-label">opponents</span></span>
      <span class="stat-div"></span>
      <span class="stat"><span class="stat-num">${num(s.sessions.count)}</span><span class="stat-label">sessions</span></span>
    </div>`))
    body.appendChild(el(`<p class="statline-caption">
      <span class="is-up">${num(o.wins)}</span> wins,
      <span class="is-down">${num(o.losses)}</span> losses
      ${o.active_days ? ` · ${num(o.active_days)} days played` : ''}
      ${s.sessions.avg_games ? ` · ~${s.sessions.avg_games} games each session` : ''}
    </p>`))
    // median + longest session were computed and thrown away; the desktop
    // states both under its session chart (StatsPage.jsx:1118-1122). The phone
    // has no session chart, so they ride the statline caption — the average
    // alone hides a corpus of one huge session and a lot of two-game ones.
    if (s.sessions.median_games) {
      body.appendChild(el(`<p class="statline-caption">
        Median session ${num(s.sessions.median_games)} games ·
        longest ${num(s.sessions.longest)} · a session ends after 45 minutes
        without a game
      </p>`))
    }

    // No unscored-games explainer (user call): resultless games (pre-code-era
    // replays, doubles, CPU/local friendlies) are already excluded from every
    // winrate — the note was explaining a non-problem.

    body.appendChild(section('Matchups', 'winrate vs each character', breakdown(
      s.matchups,
      { icon: (e) => `<img class="srow-icon" src="${stockSrc(e.key, 0)}" alt="" onerror="this.style.visibility='hidden'">`,
        label: (e) => charName(e.key), initial: 10 },
    )))

    if (s.my_characters.length > 1) {
      body.appendChild(section('Characters', 'share of games', breakdown(
        s.my_characters,
        { icon: (e) => `<img class="srow-icon" src="${stockSrc(e.key, 0)}" alt="" onerror="this.style.visibility='hidden'">`,
          label: (e) => charName(e.key), initial: 8 },
      )))
    }

    body.appendChild(section('Stages', 'winrate per stage', breakdown(
      s.stages,
      { icon: (e) => `<img class="srow-icon srow-icon--stage" src="${stageSrc(e.key)}" alt="" onerror="this.style.visibility='hidden'">`,
        label: (e) => stageName(e.key), initial: 6,
        defaultFilter: (e) => LEGAL_STAGES.has(e.key) },
    )))

    // Activity: period-switched fat bars (Health-style), never the whole
    // history as slivers. The switcher re-renders just this section.
    const activityHost = el('<div></div>')
    const drawActivity = () => {
      activityHost.innerHTML = ''
      const cols = periodCols(s.months, view.period)
      const latest = [...cols].reverse().find((c) => c.games > 0)
      activityHost.appendChild(segmented(
        [['6m', '6M'], ['1y', '1Y'], ['all', 'All']], view.period,
        (v) => { view.period = v; view.sel.month = null; drawActivity() }))
      activityHost.appendChild(tapChart(cols, 'month',
        (c) => c.label || String(c.key),
        { fat: true, defaultKey: latest ? latest.key : null }))
    }
    drawActivity()
    body.appendChild(section('Activity', 'games over time', activityHost))

    const hCols = hourCols(s.hours)
    const peak = hCols.reduce((a, b) => (b.games > (a?.games || 0) ? b : a), null)
    body.appendChild(section('Time of day', 'games per hour',
      tapChart(hCols, 'hour', (c) => hourLabel(Number(c.key)),
        { defaultKey: peak && peak.games ? peak.key : null })))

    if (s.rivals.length) {
      const rivalsHost = el('<div></div>')
      let shownRivals = 10
      const drawRivals = () => {
        rivalsHost.innerHTML = s.rivals.slice(0, shownRivals).map((r) => `
          <div class="srow srow--lg">
            ${r.top_char != null ? `<img class="srow-icon" src="${stockSrc(r.top_char, 0)}" alt="" onerror="this.style.visibility='hidden'">` : '<span class="srow-icon"></span>'}
            <span class="srow-name">${esc(r.name || r.code)}<small>${esc(r.code)}${r.last_at ? ` · ${esc(shortDate(r.last_at))}` : ''}</small></span>
            <span class="srow-games">${num(r.games)}</span>
            ${winbar(r.winrate, r.wins + r.losses)}
            <span class="srow-rate ${r.winrate == null ? '' : r.winrate >= 0.5 ? 'is-up' : 'is-down'}">${pct(r.winrate)}</span>
          </div>`).join('')
        if (s.rivals.length > shownRivals) {
          const btn = el(`<button class="show-all">Show more (${num(s.rivals.length - shownRivals)} more)</button>`)
          btn.addEventListener('click', () => { shownRivals += 20; drawRivals() })
          rivalsHost.appendChild(btn)
        }
      }
      drawRivals()
      body.appendChild(section('Rivals', 'most-played opponents (5+ games)', rivalsHost))
    }

    if (s.salt.saltiest.length || s.salt.ragebaiters.length) {
      const saltHost = el('<div></div>')
      const half = (title, sub2, rows, dirLabel) => `
        <p class="footnote" style="margin-top:10px"><b>${title}</b> — ${sub2}</p>
        ${rows.slice(0, 6).map((r) => `
          <div class="srow srow--lg">
            <span class="srow-name">${esc(r.name || r.code)}<small>${esc(r.code)}</small></span>
            <span class="srow-games">${num(r.quits)}× ${dirLabel}</span>
          </div>`).join('') || '<p class="footnote">Nobody. Suspicious.</p>'}`
      saltHost.innerHTML = half('Saltiest opponents', `quit on you ${num(s.salt.opp_quits)}× total`, s.salt.saltiest, 'quit')
        + half('Biggest ragebaiters', `made you quit ${num(s.salt.my_quits)}× total`, s.salt.ragebaiters, 'baited')
      body.appendChild(section('Salt report', 'early quits (No Contest endings)', saltHost))
    }
  }

  drawBody()
}
