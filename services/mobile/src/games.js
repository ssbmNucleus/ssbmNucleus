// Games tab — the desktop ReplaysPage row stacked for a phone. Visual
// hierarchy per the vAMP app: a large-title header with two quiet icon
// actions (sort, filter — filter wears an accent dot when active), search
// below, active filters as removable pills, then the stream with month
// headers. Filters live in a bottom sheet, not a chip strip.
import { charName, stageName, formatDuration } from '../../../app/frontend/src/shared/data/meleeNames'
import { cachedRank, fetchRanks, rankAsked } from './api'
import { emptyLibraryText } from './library-status'
import {
  el, esc, stockSrc, stockFallback, stageSrc, rankSrc, shortDate, monthLabel, num,
  sheet, sheetRow,
} from './ui'

const CHUNK = 60          // rows rendered per scroll step; keeps 20k games smooth

const FILTER_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round"><path d="M4 6h16M7 12h10M10 18h4"/></svg>`
const SORT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M11 8h8M11 12h6M11 16h4M6 5v14M6 19l-2.5-2.5M6 19l2.5-2.5"/></svg>`
const CHEV_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M6 9l6 6 6-6"/></svg>`
const GEAR_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="3"/>
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`

const SORTS = [
  ['newest', 'Newest first'],
  ['oldest', 'Oldest first'],
  ['longest', 'Longest first'],
  ['shortest', 'Shortest first'],
]

export const state = {
  filters: {
    myChar: '', oppChar: '', stage: '', result: '', teams: '',
    opponent: '', start: '', end: '',
  },
  sort: 'newest',
}

// Months arrive folded — all but the newest one in the current list. With
// years of games the open state is the exception, not the rule: you want the
// month you're in, and a table of contents for everything else. Only explicit
// taps land here, keyed "YYYY-MM"; module-level so a fold survives filter
// changes and tab switches, but deliberately NOT persisted — this is a
// browsing gesture for the session, not a preference to remember.
const monthOpen = new Map()

const playerName = (p) => p?.name || (p?.type === 1 ? 'CPU' : 'Player')

function me(g) {
  return g.user_port != null ? (g.players || []).find((p) => p.port === g.user_port) : null
}
function opps(g) {
  return g.user_port != null
    ? (g.players || []).filter((p) => p.port !== g.user_port)
    : (g.players || []).slice(1)
}

export function applyFilters(games, f, sort) {
  const out = games.filter((g) => {
    const m = me(g)
    const os = opps(g)
    if (f.myChar !== '' && (!m || String(m.character) !== f.myChar)) return false
    if (f.oppChar !== '' && !os.some((p) => String(p.character) === f.oppChar)) return false
    if (f.stage !== '' && String(g.stage) !== f.stage) return false
    if (f.result !== '' && g.result !== f.result) return false
    if (f.teams === 'singles' && g.is_teams) return false
    if (f.teams === 'doubles' && !g.is_teams) return false
    if (f.opponent) {
      const q = f.opponent.toUpperCase()
      const pool = g.user_port != null ? os : (g.players || [])
      if (!pool.some((p) => (p.code || '').toUpperCase().includes(q)
        || (p.name || '').toUpperCase().includes(q))) return false
    }
    if (f.start && (!g.start_at || g.start_at.slice(0, 10) < f.start)) return false
    if (f.end && (!g.start_at || g.start_at.slice(0, 10) > f.end)) return false
    return true
  })
  const t = (g) => g.start_at || ''
  if (sort === 'newest') out.sort((a, b) => t(b).localeCompare(t(a)))
  else if (sort === 'oldest') out.sort((a, b) => t(a).localeCompare(t(b)))
  else if (sort === 'longest') out.sort((a, b) => (b.duration_s || 0) - (a.duration_s || 0))
  else if (sort === 'shortest') out.sort((a, b) => (a.duration_s || 0) - (b.duration_s || 0))
  return out
}

function stockPips(p, count) {
  if (!count || count <= 0 || !p) return ''
  const src = stockSrc(p.character, p.costume)
  // Same costume fallback the character icon gets. Without it a costume with
  // no shipped icon drew four broken-image boxes right next to a portrait that
  // had quietly fallen back to costume 0 — the pips are the same file.
  return `<span class="pl-stocks">${
    Array.from({ length: Math.min(count, 4) })
      .map(() => `<img src="${src}" alt="" onerror="${stockFallback(p.character)}">`).join('')
  }</span>`
}

// The badge slot, mirrored around the "vs" like the desktop's PlayerSide:
//   left: [rank][name/tag][char]        right: [char][name/tag][rank]
// It is drawn empty and filled by paintRanks once the batch lands. Every
// player gets one whether or not they have a rank — an unranked or Pending
// side that collapsed to nothing would shove the row's centre off the "vs".
function rankSlot(p) {
  const code = p?.code ? String(p.code).toUpperCase() : ''
  return `<span class="pl-rank"${code ? ` data-code="${esc(code)}"` : ''}></span>`
}

/** Fill in every settled badge slot under `root`, in place. Called on freshly
 * drawn rows and again when a fetch lands, so the list never re-renders for a
 * rank (a re-render mid-scroll would teleport the reader). Dropping data-code
 * is what keeps a code out of every later request: asked once is asked. */
export function paintRanks(root) {
  for (const slot of root.querySelectorAll('.pl-rank[data-code]')) {
    const code = slot.dataset.code
    if (!rankAsked(code)) continue
    delete slot.dataset.code
    const rank = cachedRank(code)
    const src = rank && rank.ranked && rankSrc(rank.tier)
    if (src) {
      slot.innerHTML = `<img src="${src}" alt=""
        title="${esc(`${rank.tier} — ${rank.rating}`)}" onerror="this.remove()">`
    }
  }
}

function sideHtml(p, side, stocks) {
  if (!p) return `<div class="pl pl--${side}"></div>`
  const icon = `<img class="pl-char" src="${stockSrc(p.character, p.costume)}" alt=""
    onerror="${stockFallback(p.character)}" title="${esc(charName(p.character))}">`
  const id = `<span class="pl-id">
      <span class="pl-name">${esc(playerName(p))}</span>
      ${p.code ? `<span class="pl-tag">${esc(p.code)}</span>` : ''}
      ${stockPips(p, stocks)}
    </span>`
  const rank = rankSlot(p)
  return `<div class="pl pl--${side}">${
    side === 'left' ? rank + id + icon : icon + id + rank}</div>`
}

export function rowHtml(g, i, animate) {
  const m = me(g)
  const os = opps(g)
  const st = g.end_stocks || {}
  const res = g.result || 'unknown'
  const badge = res === 'win' ? 'W' : res === 'loss' ? 'L' : '–'

  let body
  if (m && os.length === 1) {
    body = `<div class="versus">
        ${sideHtml(m, 'left', st[String(m.port)])}
        <span class="vs-mid">vs</span>
        ${sideHtml(os[0], 'right', st[String(os[0].port)])}
      </div>`
  } else {
    const ps = g.players || []
    body = `<div class="multi">
        <span class="multi-chars">${ps.map((p, k) => `${k ? '<span class="vs-mid">vs</span>' : ''}
          <img class="pl-char" src="${stockSrc(p.character, p.costume)}" alt=""
               onerror="${stockFallback(p.character)}">${esc(charName(p.character))}`).join('')}</span>
        <span class="multi-opp">${esc(os.map((p) => p.name || p.code || 'Player').join(', '))}</span>
      </div>`
  }

  return `<button class="replay-row ${animate ? '' : 'no-anim'}" data-hash="${g.content_hash}"
      style="--row-i:${Math.min(i, 14)}">
    <span class="result result--${res}">${badge}</span>
    <span class="row-main">
      ${body}
      <span class="row-meta">
        <img class="stage-ico" src="${stageSrc(g.stage)}" alt=""
             onerror="this.style.display='none'">
        <span class="stg">${esc(stageName(g.stage))}</span>
        <span class="dot">·</span>
        <span>${shortDate(g.start_at)}</span>
        <span class="grow"></span>
        <span class="dur">${formatDuration(g.duration_s)}</span>
      </span>
    </span>
  </button>`
}

export function facetsOf(games) {
  const my = new Map(), opp = new Map(), stages = new Map()
  for (const g of games) {
    const m = me(g)
    if (m && m.character != null) my.set(m.character, (my.get(m.character) || 0) + 1)
    for (const p of opps(g)) {
      if (p.character != null) opp.set(p.character, (opp.get(p.character) || 0) + 1)
    }
    if (g.stage != null) stages.set(g.stage, (stages.get(g.stage) || 0) + 1)
  }
  const sorted = (m) => [...m.entries()].sort((a, b) => b[1] - a[1])
  return { my: sorted(my), opp: sorted(opp), stages: sorted(stages) }
}

const filterCount = (f) => ['myChar', 'oppChar', 'stage', 'result', 'teams', 'start', 'end']
  .filter((k) => f[k] !== '').length

// ── the filter sheet: grouped chip sections, applied live ─────────────────
function openFilterSheet(facets, onChange) {
  const sh = sheet('Filters')
  const f = state.filters

  const chipGroup = (label, entries, key, iconOf) => {
    sh.body.appendChild(el(`<div class="sheet-group">${esc(label)}</div>`))
    const row = el('<div class="sheet-chiprow"></div>')
    for (const [value, text, icon] of entries) {
      const on = f[key] === String(value)
      const chip = el(`<button class="sheet-chip ${on ? 'is-on' : ''}">
        ${iconOf && icon ? `<img src="${icon}" alt="" onerror="this.remove()">` : ''}${esc(text)}</button>`)
      chip.addEventListener('click', () => {
        f[key] = on && f[key] === String(value) ? '' : String(value)
        onChange()
        sh.close()
      })
      row.appendChild(chip)
    }
    sh.body.appendChild(row)
  }

  chipGroup('Result', [['win', 'Wins'], ['loss', 'Losses']], 'result')
  chipGroup('Mode', [['singles', 'Singles'], ['doubles', 'Doubles']], 'teams')
  // No top-N caps. A filter you cannot reach is not a filter: Corneria sat
  // outside the tenth-most-played stage and simply did not exist in this
  // sheet, and the same was true of every character past the twelfth. The
  // lists are a couple of dozen rows at most and the sheet already scrolls.
  chipGroup('My character',
    facets.my.map(([c, n]) => [c, `${charName(c)} (${n})`, stockSrc(c, 0)]),
    'myChar', true)
  chipGroup('Opponent character',
    facets.opp.map(([c, n]) => [c, `${charName(c)} (${n})`, stockSrc(c, 0)]),
    'oppChar', true)
  chipGroup('Stage',
    facets.stages.map(([s, n]) => [s, `${stageName(s)} (${n})`]),
    'stage')

  sh.body.appendChild(el('<div class="sheet-group">Date range</div>'))
  const dates = el(`<div class="sheet-chiprow" style="gap:8px">
    <input type="date" id="f-start" value="${f.start}" aria-label="From"
      style="flex:1;min-height:40px;background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:10px;color:var(--text-1);padding:6px 10px;font-family:var(--mono);font-size:13px">
    <input type="date" id="f-end" value="${f.end}" aria-label="To"
      style="flex:1;min-height:40px;background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:10px;color:var(--text-1);padding:6px 10px;font-family:var(--mono);font-size:13px">
  </div>`)
  sh.body.appendChild(dates)
  dates.querySelector('#f-start').addEventListener('change', (e) => { f.start = e.target.value; onChange() })
  dates.querySelector('#f-end').addEventListener('change', (e) => { f.end = e.target.value; onChange() })

  if (filterCount(f) > 0) {
    const clear = el('<button class="wide" style="margin-top:12px;color:var(--danger)">Clear all filters</button>')
    clear.addEventListener('click', () => {
      Object.assign(f, { myChar: '', oppChar: '', stage: '', result: '', teams: '', start: '', end: '' })
      onChange()
      sh.close()
    })
    sh.body.appendChild(clear)
  }
}

function openSortSheet(onChange) {
  const sh = sheet('Sort by')
  for (const [key, label] of SORTS) {
    const row = sheetRow({ label, checked: state.sort === key })
    row.addEventListener('click', () => { state.sort = key; onChange(); sh.close() })
    sh.body.appendChild(row)
  }
}

// pills for whatever's active — each removable in place
function pillsHtml(f) {
  const out = []
  const add = (key, label, value) => out.push(
    `<span class="pill" data-k="${key}"><b>${label}</b> ${esc(value)}<span class="x">×</span></span>`)
  if (f.result) add('result', '', f.result === 'win' ? 'Wins' : 'Losses')
  if (f.teams) add('teams', '', f.teams === 'singles' ? 'Singles' : 'Doubles')
  if (f.myChar !== '') add('myChar', 'Me:', charName(Number(f.myChar)))
  if (f.oppChar !== '') add('oppChar', 'Vs:', charName(Number(f.oppChar)))
  if (f.stage !== '') add('stage', '', stageName(Number(f.stage)))
  if (f.start || f.end) add('dates', '', `${f.start || '…'} → ${f.end || '…'}`)
  return out.join('')
}

// `status` explains an empty list: {synced, codes, loading} — see
// library-status.js (bug #64). Optional; callers without it get the old text.
export function renderGames(root, games, onOpen, onSettings, status = null) {
  root.innerHTML = ''
  const head = el(`<div class="head frosted">
    <div><h1>Games</h1><div class="sub">${num(games.length)} synced</div></div>
    <span class="grow"></span>
    <button class="headbtn" id="h-sort" aria-label="Sort">${SORT_ICON}</button>
    <button class="headbtn" id="h-filter" aria-label="Filter">${FILTER_ICON}</button>
    <button class="headbtn" id="h-gear" aria-label="Settings">${GEAR_ICON}</button>
  </div>`)
  root.appendChild(head)

  const body = el('<div class="pagebody"></div>')
  root.appendChild(body)

  const facets = facetsOf(games)

  const search = el(`<div class="searchrow">
    <input type="search" placeholder="Search opponent name or code"
           value="${esc(state.filters.opponent)}" autocomplete="off"></div>`)
  const searchInput = search.querySelector('input')
  let debounce = null
  searchInput.addEventListener('input', () => {
    clearTimeout(debounce)
    debounce = setTimeout(() => {
      state.filters.opponent = searchInput.value.trim()
      renderList()
    }, 250)
  })
  body.appendChild(search)

  const pills = el('<div class="pills"></div>')
  body.appendChild(pills)
  pills.addEventListener('click', (e) => {
    const pill = e.target.closest('.pill')
    if (!pill) return
    const k = pill.dataset.k
    if (k === 'dates') { state.filters.start = ''; state.filters.end = '' }
    else state.filters[k] = ''
    refresh()
  })

  const listHost = el('<div></div>')
  body.appendChild(listHost)

  const filterBtn = head.querySelector('#h-filter')
  const syncFilterDot = () => {
    filterBtn.querySelector('.dot')?.remove()
    if (filterCount(state.filters) > 0) filterBtn.appendChild(el('<span class="dot"></span>'))
  }
  const refresh = () => { syncFilterDot(); pills.innerHTML = pillsHtml(state.filters); renderList() }
  head.querySelector('#h-sort').addEventListener('click', () => openSortSheet(refresh))
  filterBtn.addEventListener('click', () => openFilterSheet(facets, refresh))
  head.querySelector('#h-gear').addEventListener('click', () => onSettings && onSettings())
  syncFilterDot()
  pills.innerHTML = pillsHtml(state.filters)

  let shown = 0
  let filtered = []
  let monthCounts = new Map()
  let sentinel = null
  let firstRender = true
  let rankTimer = null

  // Ranks are a network round-trip, so the list never waits on one: rows draw
  // with empty badge slots and get painted when the batch returns. Only slots
  // still carrying a data-code are unasked, so a re-render or a filter change
  // costs nothing — this fires only when codes new to the session appear on
  // screen. The debounce is long on purpose: scrolling appends chunks in
  // bursts, and one request per burst is the point (see api.js on why this
  // client is stingy about slippi.gg).
  function scheduleRanks() {
    clearTimeout(rankTimer)
    rankTimer = setTimeout(() => {
      const codes = [...listHost.querySelectorAll('.pl-rank[data-code]')]
        .map((s) => s.dataset.code)
      if (!codes.length) return
      fetchRanks(codes).then((grew) => { if (grew) paintRanks(listHost) })
    }, 400)
  }

  const ymOf = (g) => (g.start_at ? g.start_at.slice(0, 7) : 'unknown')
  // only the date sorts group into months; length sorts are one flat stream
  const grouped = () => state.sort === 'newest' || state.sort === 'oldest'
  let topYm = null      // the list's first month: open unless you shut it
  const isOpen = (ym) => (monthOpen.has(ym) ? monthOpen.get(ym) : ym === topYm)

  // A folded month renders as a header and NOTHING else — its rows are never
  // built. Hiding them instead would mean paying for thousands of DOM nodes
  // the moment you fold, which is the opposite of what folding is for. So a
  // chunk advances through the whole library but only counts the rows it
  // actually draws.
  function appendChunk() {
    const frag = document.createDocumentFragment()
    const animate = firstRender && shown === 0
    const fold = grouped()
    let lastYm = shown > 0 && filtered[shown - 1].start_at
      ? filtered[shown - 1].start_at.slice(0, 7) : null
    let drawn = 0
    let i = shown
    for (; i < filtered.length && drawn < CHUNK; i++) {
      const g = filtered[i]
      const ym = ymOf(g)
      if (fold && ym !== lastYm) {
        const on = isOpen(ym)
        frag.appendChild(el(`<button class="month-head ${on ? '' : 'is-collapsed'}"
          type="button" data-ym="${esc(ym)}" aria-expanded="${on ? 'true' : 'false'}">
          <span class="chev">${CHEV_ICON}</span>
          <span class="name">${ym === 'unknown' ? 'Unknown date' : monthLabel(ym)}</span>
          <span class="count">${num(monthCounts.get(ym) || 0)}</span>
        </button>`))
        lastYm = ym
      }
      if (fold && !isOpen(ym)) continue
      const row = el(rowHtml(g, drawn, animate))
      row.dataset.ym = ym
      frag.appendChild(row)
      drawn++
    }
    const list = el('<div class="list"></div>')
    list.appendChild(frag)
    listHost.insertBefore(list, sentinel)
    paintRanks(list)      // codes already answered this session cost nothing
    scheduleRanks()
    shown = i
    firstRender = false
    if (sentinel) sentinel.hidden = shown >= filtered.length
  }

  // Folding leaves a short page, which can park the sentinel back on screen
  // with nothing above it — and IntersectionObserver won't re-fire without a
  // fresh crossing. Top up by hand, bounded so it can never run away.
  function fillViewport() {
    for (let n = 0; n < 20 && shown < filtered.length; n++) {
      if (sentinel.getBoundingClientRect().top > window.innerHeight + 600) break
      appendChunk()
    }
  }

  // Opening a month has to materialise rows that were never built, so this
  // re-renders rather than unhiding — then pins the tapped header back under
  // the thumb, because a re-render from the top would otherwise teleport the
  // list out from under you.
  function toggleMonth(ym, headEl) {
    const anchor = headEl ? headEl.getBoundingClientRect().top : null
    monthOpen.set(ym, !isOpen(ym))
    renderList()
    // The re-render restarts at the top of the library, so a month far down
    // the list isn't on the page yet — keep pulling chunks until its header
    // comes back, then pin it exactly where the thumb left it. Skipping this
    // drops the reader at the top of a suddenly-short page.
    for (let n = 0; n < 200 && shown < filtered.length; n++) {
      if (listHost.querySelector(`.month-head[data-ym="${ym}"]`)) break
      appendChunk()
    }
    const again = listHost.querySelector(`.month-head[data-ym="${ym}"]`)
    if (again && anchor != null) {
      window.scrollBy(0, again.getBoundingClientRect().top - anchor)
    }
  }

  function renderList() {
    filtered = applyFilters(games, state.filters, state.sort)
    monthCounts = new Map()
    for (const g of filtered) {
      const ym = ymOf(g)
      monthCounts.set(ym, (monthCounts.get(ym) || 0) + 1)
    }
    topYm = filtered.length ? ymOf(filtered[0]) : null
    listHost.innerHTML = ''
    shown = 0
    sentinel = el('<button class="more-btn">Load more</button>')
    sentinel.addEventListener('click', appendChunk)
    listHost.appendChild(sentinel)
    if (!filtered.length) {
      const why = !games.length && status
        ? emptyLibraryText({ ...status, listed: games.length }) : null
      listHost.insertBefore(el(`<p class="empty">${esc(why || 'No games match these filters.')}</p>`), sentinel)
      sentinel.hidden = true
      return
    }
    appendChunk()
    if (typeof IntersectionObserver !== 'undefined') {
      const io = new IntersectionObserver((es) => {
        if (es.some((e) => e.isIntersecting) && shown < filtered.length) appendChunk()
      }, { rootMargin: '600px' })
      io.observe(sentinel)
    }
  }

  renderList()

  listHost.addEventListener('click', (e) => {
    // month heads and rows are siblings, so closest() can't confuse the two
    const month = e.target.closest('.month-head')
    if (month) { toggleMonth(month.dataset.ym, month); return }
    const row = e.target.closest('.replay-row')
    if (!row) return
    const g = filtered.find((x) => x.content_hash === row.dataset.hash)
    if (g) onOpen(g)
  })
}
