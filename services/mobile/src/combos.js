// Combos tab — the desktop CombosPage card, stacked for a phone: move
// sequence, damage + percent range, TRUE/KILL badges, both players, stage,
// date. Header + filter UX mirrors the Games tab: large title, quiet icon
// actions (sort, filter — filter wears an accent dot when active), active
// filters as removable pills, filters in a bottom sheet. "Play all" runs the
// current filtered order as a combo theater.
//
// Unlike the Games tab, this one does NOT browse a local corpus. Games are
// pulled whole (compact meta rows); combos are not — one measured vault holds
// 246,671 of them. So every filter change is a SERVER query and the list pages
// through the answer, exactly as the desktop does over its SQLite index. That
// is what makes the header count, the sort order and "Play all" mean the whole
// library instead of whatever slice happened to be cached.
import { charName, stageName, moveName } from '../../../app/frontend/src/shared/data/meleeNames'
import { el, esc, stockSrc, stockFallback, stageSrc, shortDate, num, toast, sheet, sheetRow } from './ui'
import { queryCombos, countCombos, cachedComboPage, saveComboPage, COMBO_PAGE } from './api'
import { openTheater } from './theater'

const FILTER_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round"><path d="M4 6h16M7 12h10M10 18h4"/></svg>`
const SORT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M11 8h8M11 12h6M11 16h4M6 5v14M6 19l-2.5-2.5M6 19l2.5-2.5"/></svg>`

// Same metrics as the desktop CombosPage sort row; the keys ARE the API's sort
// keys, and the server picks each metric's natural direction (start % ascending
// — a 0%-to-death outranks a 100% cleanup — the rest descending).
const SORTS = [
  ['damage', 'Biggest damage'],
  ['recent', 'Most recent'],
  ['moves', 'Most moves'],
  ['duration', 'Longest'],
  ['startpct', 'Lowest start %'],
]

// PostgREST offset paging is capped server-side at 10,000; asking past it would
// silently re-serve the last page forever, so the list stops there. Nobody
// scrolls 10k rows — they filter — and the header still shows the real total.
const MAX_ROWS = 10_000
// "Play all" is a marathon, not the whole library: it takes the first N of the
// CURRENT server-side order rather than whatever is in the DOM.
const PLAY_ALL = 100

// startPct mirrors the desktop encoding: '0' = from 0%, '<N' = starts under
// N%, 'N+' = starts at N%+. All values are strings; '' = filter off.
export const state = {
  filters: {
    kills: '', kind: '', myChar: '', oppChar: '', stage: '', opponent: '',
    // Desktop opens on its highlight set, not the raw library: 4+ moves and
    // 50%+ damage (CombosPage.jsx filter defaults). About a fifth of the
    // corpus is 3-hit filler, so an unthresholded first screen is mostly
    // noise and the two apps disagreed on what "Combos" even means. Both
    // show as removable pills, so the full library is one tap away.
    minDamage: '50', minMoves: '4', startPct: '',
    // 'mine' (default): combos YOU performed. 'received': you getting
    // comboed. The detector indexes both directions; without this the tab
    // mixed them (desktop separates them too). Resolved server-side through
    // the connect codes stored in the vault, like the desktop's query.
    direction: 'mine',
  },
  // desktop lands on recent-first (CombosPage.jsx useState('recent'))
  sort: 'recent',
}

const game = (c) => c.vault_games || {}

// Desktop draws each side's stock icon in that player's real costume
// (CombosPage.jsx ComboRow, `me?.costume ?? 0`); costume 0 painted every
// Falco red-team blue no matter what was actually played. The embedded game
// may not carry `players` at all, so match on port when we have one and fall
// back to the character (a ditto then picks the first match — still the right
// character, which is what shows).
function costumeOf(c, port, character) {
  const ps = game(c).players || []
  const p = (port != null && ps.find((x) => x.port === port))
    || ps.find((x) => x.character === character)
  return p?.costume ?? 0
}

// Desktop's PlayerName falls back name → code → P{port} (CombosPage.jsx).
// Falling back to the CHARACTER name labelled a code-less player "Falco" as
// if that were their tag.
const playerLabel = (name, code, port) =>
  name || code || (port != null ? `P${port}` : 'P?')

function seq(moves) {
  return (moves || [])
    .map((m) => moveName(m.move_id) + (m.hits > 1 ? ` ×${m.hits}` : ''))
    .join(' → ')
}

export function comboHtml(c, i, animate) {
  const durS = c.end_frame > c.start_frame
    ? `${((c.end_frame - c.start_frame) / 60).toFixed(1)}s` : ''
  const moves = (c.moves || []).length || c.hits || 0
  const sequence = seq(c.moves)
  return `<button class="combo-row ${animate ? '' : 'no-anim'}" data-i="${i}"
      style="--row-i:${Math.min(i, 14)}">
    <span class="combo-dmg">${Math.round(c.damage || 0)}%
      ${/* Badges live under the damage, not on the name line: a long tag
            pushed them off the right edge and clipped them in half.
            Strings wear no badge (unlike desktop) — only TRUE and KILL. */''}
      ${c.true_combo === true || c.did_kill ? `<span class="combo-badges">
        ${c.true_combo === true ? '<span class="true-badge">TRUE</span>' : ''}
        ${c.did_kill ? '<span class="kill-badge">KILL</span>' : ''}
      </span>` : ''}
    </span>
    <span class="combo-main">
      <span class="combo-line1">
        <img src="${stockSrc(c.character, costumeOf(c, c.port, c.character))}" alt=""
             onerror="${stockFallback(c.character)}">
        ${esc(playerLabel(c.name, c.code, c.port))}
        <span class="vs-mid">vs</span>
        <img src="${stockSrc(c.opp_character, costumeOf(c, c.opp_port, c.opp_character))}" alt=""
             onerror="${stockFallback(c.opp_character)}">
        ${esc(playerLabel(c.opp_name, c.opp_code, c.opp_port))}
      </span>
      ${sequence ? `<span class="combo-seq">${esc(sequence)}</span>` : ''}
      <span class="combo-line2">
        ${c.start_percent != null
          ? `<span class="combo-range">${Math.round(c.start_percent)}% → ${Math.round(c.end_percent)}%</span><span class="dot">·</span>`
          : ''}
        <span>${moves} moves</span>
        ${durS ? `<span class="dot">·</span><span>${durS}</span>` : ''}
        <span class="dot">·</span>
        <img class="stage-ico" src="${stageSrc(game(c).stage)}" alt=""
             onerror="this.style.display='none'">
        <span>${shortDate(game(c).start_at)}</span>
      </span>
    </span>
  </button>`
}

// ── the query ─────────────────────────────────────────────────────────────
// The sheet's string-encoded filters, translated to the vault-read `combos`
// contract. The my/vs character SWAP that "received" needs is deliberately NOT
// done here: the server owns it, because only the server knows which column is
// the attacker's (combos.py / CombosPage.jsx queryParams do the same).
export function queryOf(f, sort) {
  const n = (v) => (v === '' || v == null ? null : Number(v))
  const filters = {
    direction: f.direction,
    my_char: n(f.myChar),
    opp_char: n(f.oppChar),
    stage: n(f.stage),
    kills: f.kills !== '',
    kind: f.kind,
    min_damage: n(f.minDamage),
    min_moves: n(f.minMoves),
    // start_pct_max is INCLUSIVE server-side (`start_percent <= ?`), so 'From
    // 0%' is a max of 0 rather than a special case.
    start_pct_max: null,
    start_pct_min: null,
    opponent: f.opponent || null,
  }
  if (f.startPct === '0') filters.start_pct_max = 0
  else if (f.startPct.startsWith('<')) filters.start_pct_max = Number(f.startPct.slice(1))
  else if (f.startPct.endsWith('+')) filters.start_pct_min = Number(f.startPct.slice(0, -1))
  return { filters, sort }
}

// One page of results is not a description of the library, so the filter chips
// are built from the GAMES the phone already holds — every character you have
// ever played, every character you have played against, every stage — instead
// of from whatever combos happen to be on screen. That also means the options
// don't move as you scroll, and nothing has to be truncated to a top-12.
export function facetsOf(store) {
  const my = new Map(), opp = new Map(), stages = new Map()
  const bump = (m, k) => { if (k != null) m.set(k, (m.get(k) || 0) + 1) }
  for (const g of (store && store.games) || []) {
    const ps = g.players || []
    const me = g.user_port != null ? ps.find((p) => p.port === g.user_port) : null
    if (me) {
      bump(my, me.character)
      for (const p of ps) if (p !== me) bump(opp, p.character)
    } else {
      // No claimed identity in this game, so it can't say which side is
      // yours: offer both characters on both lists rather than neither.
      for (const p of ps) { bump(my, p.character); bump(opp, p.character) }
    }
    bump(stages, g.stage)
  }
  // Most-played first — the chip you want is nearly always near the front.
  const sorted = (m) => [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k)
  return { my: sorted(my), opp: sorted(opp), stages: sorted(stages) }
}

// direction defaults to 'mine' — that's the normal view, not an active filter
const filterCount = (f) => Object.keys(state.filters)
  .filter((k) => (k === 'direction' ? f[k] !== 'mine' : f[k] !== '')).length

// ── the filter sheet: grouped chip sections, tap applies + closes ─────────
function openFilterSheet(facets, onChange) {
  const sh = sheet('Filters')
  const f = state.filters

  const group = (label) => {
    sh.body.appendChild(el(`<div class="sheet-group">${esc(label)}</div>`))
    const row = el('<div class="sheet-chiprow"></div>')
    sh.body.appendChild(row)
    return row
  }
  const chip = (row, key, value, text, icon) => {
    const on = f[key] === String(value)
    const c = el(`<button class="sheet-chip ${on ? 'is-on' : ''}">
      ${icon ? `<img src="${icon}" alt="" onerror="this.remove()">` : ''}${esc(text)}</button>`)
    c.addEventListener('click', () => {
      f[key] = on ? '' : String(value)
      onChange()
      sh.close()
    })
    row.appendChild(c)
  }

  // A typed escape hatch under a preset row — desktop's FilterSelect pattern
  // ("At least [N] moves"): presets cover the common cuts, the input reaches
  // any exact value. Enter/blur applies.
  const custom = (before, after, apply, current) => {
    const wrap = el(`<div class="sheet-chiprow" style="gap:8px;align-items:center">
      <span style="font-size:12px;color:var(--text-3)">${esc(before)}</span>
      <input type="number" inputmode="numeric" min="0" max="999" value="${esc(current)}"
        style="width:74px;min-height:38px;background:var(--bg-elevated);border:1px solid var(--border-subtle);border-radius:10px;color:var(--text-1);padding:6px 10px;font-family:var(--mono);font-size:16px">
      <span style="font-size:12px;color:var(--text-3)">${esc(after)}</span>
    </div>`)
    const inp = wrap.querySelector('input')
    const commit = () => {
      const n = inp.value.trim()
      apply(n !== '' && Number.isFinite(Number(n)) ? Number(n) : null)
      onChange()
      sh.close()
    }
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') commit() })
    inp.addEventListener('blur', () => {
      const n = inp.value.trim()
      if (n !== '' && Number.isFinite(Number(n))) commit()
    })
    sh.body.appendChild(wrap)
    return wrap
  }

  let row = group('Show')
  chip(row, 'direction', 'mine', 'My combos')
  chip(row, 'direction', 'received', 'Me getting comboed')

  row = group('Combo type')
  chip(row, 'kills', '1', 'Kills only')
  chip(row, 'kind', 'true', 'True combos')
  chip(row, 'kind', 'string', 'Strings')

  // Desktop has an opponent name/code box next to the dropdowns
  // (CombosPage.jsx combos-opponent-search); mobile keeps its search in the
  // sheet with the rest of the filters. Enter or blur applies, like the
  // typed number rows above.
  sh.body.appendChild(el('<div class="sheet-group">Opponent</div>'))
  const oppSearch = el(`<div class="searchrow" style="padding:0 6px 8px">
    <input type="search" placeholder="Opponent name or code" autocomplete="off"
           value="${esc(f.opponent)}"></div>`)
  const oppInput = oppSearch.querySelector('input')
  const applyOpp = () => {
    const v = oppInput.value.trim()
    if (v === f.opponent) return false
    f.opponent = v
    onChange()
    return true
  }
  oppInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); applyOpp(); sh.close() }
  })
  oppInput.addEventListener('blur', () => { if (applyOpp()) sh.close() })
  sh.body.appendChild(oppSearch)

  // Every character/stage in the library, not a truncated top-N: the options
  // come from the games list, so the full set is known and cheap to draw.
  row = group('My character')
  for (const c of facets.my) chip(row, 'myChar', c, charName(c), stockSrc(c, 0))
  row = group('Vs character')
  for (const c of facets.opp) chip(row, 'oppChar', c, charName(c), stockSrc(c, 0))
  row = group('Stage')
  for (const s of facets.stages) chip(row, 'stage', s, stageName(s))

  row = group('Min damage')
  for (const v of [30, 50, 70, 100]) chip(row, 'minDamage', v, `${v}%+`)
  custom('At least', '% damage', (n) => { f.minDamage = n == null ? '' : String(n) },
    [30, 50, 70, 100].includes(Number(f.minDamage)) ? '' : f.minDamage)

  row = group('Min moves')
  for (const v of [4, 5, 6, 7]) chip(row, 'minMoves', v, `${v}+ moves`)
  custom('At least', 'moves', (n) => { f.minMoves = n == null ? '' : String(n) },
    [4, 5, 6, 7].includes(Number(f.minMoves)) ? '' : f.minMoves)

  row = group('Starts at')
  chip(row, 'startPct', '0', 'From 0%')
  chip(row, 'startPct', '<25', 'Under 25%')
  chip(row, 'startPct', '<50', 'Under 50%')
  chip(row, 'startPct', '50+', '50%+')
  custom('Starts under', '%', (n) => { f.startPct = n == null ? '' : `<${n}` },
    f.startPct.startsWith('<') && !['<25', '<50'].includes(f.startPct) ? f.startPct.slice(1) : '')
  custom('Starts at', '%+', (n) => { f.startPct = n == null ? '' : `${n}+` },
    f.startPct.endsWith('+') && f.startPct !== '50+' ? f.startPct.slice(0, -1) : '')

  if (filterCount(f) > 0) {
    const clear = el('<button class="wide" style="margin-top:12px;color:var(--danger)">Clear all filters</button>')
    clear.addEventListener('click', () => {
      for (const k of Object.keys(f)) f[k] = k === 'direction' ? 'mine' : ''
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
  if (f.direction !== 'mine') {
    add('direction', '', f.direction === 'received' ? 'Getting comboed' : 'Both directions')
  }
  if (f.kills !== '') add('kills', '', 'Kills')
  if (f.kind !== '') add('kind', '', f.kind === 'true' ? 'True combos' : 'Strings')
  if (f.myChar !== '') add('myChar', 'Me:', charName(Number(f.myChar)))
  if (f.oppChar !== '') add('oppChar', 'Vs:', charName(Number(f.oppChar)))
  if (f.opponent !== '') add('opponent', 'Opp:', f.opponent)
  if (f.stage !== '') add('stage', '', stageName(Number(f.stage)))
  if (f.minDamage !== '') add('minDamage', '', `${f.minDamage}%+ damage`)
  if (f.minMoves !== '') add('minMoves', '', `${f.minMoves}+ moves`)
  if (f.startPct !== '') {
    add('startPct', '', f.startPct === '0' ? 'From 0%'
      : f.startPct.startsWith('<') ? `Starts under ${f.startPct.slice(1)}%`
        : `Starts at ${f.startPct.slice(0, -1)}%+`)
  }
  return out.join('')
}

// The signature the first-page cache is keyed by: a cached page for a
// different filter+sort is the wrong answer, not a stale one.
// Bumped when the SERVER's idea of what a combo is changes, so a page cached
// under the old rules is discarded instead of being served as though it still
// matched. Without this the filter+sort key alone looks identical across such a
// change, and the tab happily paints rows the vault no longer returns.
const COMBO_RULES_V = 2      // v2 = server-side 4-move minimum
const sigOf = () => JSON.stringify([COMBO_RULES_V, state.filters, state.sort])
// Only the view the app OPENS on is cached. `state` is module-level, so this
// captures the declared defaults before anything mutates them — cache any
// other query and a reload (which resets state) would never find it again.
const DEFAULT_SIG = JSON.stringify([COMBO_RULES_V, { ...state.filters }, state.sort])

/**
 * @param root   host element
 * @param store  the app store (uses `store.games` for the filter chips). An
 *               array is accepted too — that was the old "here are the
 *               combos" call shape, and it degrades to empty chip lists
 *               rather than throwing.
 * @param onOpen combo -> void
 */
export function renderCombos(root, store, onOpen) {
  const lib = store && !Array.isArray(store) ? store : { games: [] }

  root.innerHTML = ''
  const head = el(`<div class="head frosted">
    <div><h1>Combos</h1><div class="sub" id="c-count">Loading…</div></div>
    <span class="grow"></span>
    <button class="playall" id="c-playall">▶ Play all</button>
    <button class="headbtn" id="c-sort" aria-label="Sort">${SORT_ICON}</button>
    <button class="headbtn" id="c-filter" aria-label="Filter">${FILTER_ICON}</button>
  </div>`)
  root.appendChild(head)

  const body = el('<div class="pagebody"></div>')
  root.appendChild(body)

  const pills = el('<div class="pills"></div>')
  body.appendChild(pills)
  pills.addEventListener('click', (e) => {
    const pill = e.target.closest('.pill')
    if (!pill) return
    const k = pill.dataset.k
    state.filters[k] = k === 'direction' ? 'mine' : ''
    refresh()
  })

  const listHost = el('<div class="list"></div>')
  body.appendChild(listHost)
  const empty = el('<p class="empty" hidden>No combos match these filters.</p>')
  // First-load placeholder: card-shaped shimmer where the rows will land. The
  // old state — a lone elevated "Loading…" bar floating on an empty page —
  // read as broken chrome.
  const skel = el(`<div class="sk" hidden aria-hidden="true">${
    Array.from({ length: 6 }, (_, i) => `<div class="sk-row" style="--row-i:${i}">
      <i class="sk-a"></i>
      <span class="sk-main"><i class="sk-b"></i><i class="sk-c"></i></span>
    </div>`).join('')}</div>`)
  const sentinel = el('<button class="more-btn" hidden>Load more</button>')
  listHost.append(empty, skel, sentinel)

  // rows is the loaded prefix of the SERVER's ordering — never re-sorted here,
  // or "Play all" and the visible list would disagree about what comes next.
  let rows = []
  let total = null
  let done = false
  let loading = false
  let epoch = 0        // bumped per query; late replies from an abandoned
                       // filter must not paint over the current one
  let animate = true
  let fills = 0        // runaway guard on the viewport top-up below

  const countEl = head.querySelector('#c-count')
  function paintCount() {
    if (total != null) countEl.textContent = `${num(total)} combo${total === 1 ? '' : 's'}`
    else countEl.textContent = loading ? 'Loading…' : `${num(rows.length)} loaded`
  }
  function paintTail() {
    empty.hidden = !(done && !loading && rows.length === 0)
    skel.hidden = !(loading && rows.length === 0)
    // with no rows the skeleton carries the loading state; with rows the
    // sentinel stays but goes quiet (is-loading) instead of a big button
    sentinel.hidden = (done && !loading) || (loading && rows.length === 0)
    sentinel.disabled = loading
    sentinel.classList.toggle('is-loading', loading)
    sentinel.textContent = loading ? 'Loading…' : 'Load more'
  }
  function clearRows() {
    for (const n of [...listHost.querySelectorAll('.combo-row')]) n.remove()
  }
  function appendRows(page) {
    const from = rows.length - page.length
    sentinel.insertAdjacentHTML('beforebegin',
      page.map((c, i) => comboHtml(c, from + i, animate)).join(''))
    animate = false
  }

  // A page that doesn't fill the screen leaves the sentinel visible, and
  // IntersectionObserver won't re-fire without a fresh crossing — so top up by
  // hand after every load, bounded so it can never run away.
  function maybeFill() {
    if (done || loading || fills > 30) return
    if (sentinel.getBoundingClientRect().top > window.innerHeight + 600) return
    fills++
    load(false)
  }

  async function load(reset, { keepRows = false, retried = false } = {}) {
    if (loading && !reset) return
    const mine = ++epoch
    const sig = sigOf()
    const q = queryOf(state.filters, state.sort)
    const offset = reset ? 0 : rows.length
    loading = true
    if (reset) fills = 0
    if (reset && !keepRows) { rows = []; total = null; done = false; clearRows() }
    paintCount()
    paintTail()
    try {
      // The count is a separate, slower request that the list never waits on:
      // it lands in the header a moment later, or not at all.
      if (reset || total == null) {
        countCombos(q).then((n) => {
          if (mine !== epoch || n == null) return
          total = n
          paintCount()
        }).catch(() => {})
      }
      const out = await queryCombos({ ...q, limit: COMBO_PAGE, offset })
      if (mine !== epoch) return
      if (reset) {
        rows = out.combos
        clearRows()
        animate = true
      } else {
        rows = rows.concat(out.combos)
      }
      appendRows(out.combos)
      done = out.combos.length < COMBO_PAGE
        || (total != null && rows.length >= total)
        || rows.length >= MAX_ROWS
      // Only the opening view is worth caching: it is the one the tab has to
      // paint before the network answers.
      if (reset && sig === DEFAULT_SIG) saveComboPage(sig, rows, total)
    } catch (e) {
      if (mine !== epoch) return
      // One retry before giving up. The vault times a query out when it is
      // busy absorbing a sync, and the page that failed is usually fine a
      // second later — ending the list on a transient error strands the
      // reader mid-scroll with no way back except changing a filter.
      if (!retried) {
        loading = false
        setTimeout(() => { if (mine === epoch) load(reset, { keepRows: true, retried: true }) }, 1200)
        return
      }
      done = true
      if (!rows.length) {
        empty.textContent = `Could not reach your library. ${e.message}`
      } else {
        // rows can only be non-empty here on a reset if they came from the
        // cache, so say which of the two situations this is.
        toast(reset ? 'Offline — showing this phone\'s cached combos.'
          : 'Could not load more combos.')
      }
    } finally {
      if (mine === epoch) {
        loading = false
        paintCount()
        paintTail()
        maybeFill()
      }
    }
  }

  const filterBtn = head.querySelector('#c-filter')
  const syncFilterDot = () => {
    filterBtn.querySelector('.dot')?.remove()
    if (filterCount(state.filters) > 0) filterBtn.appendChild(el('<span class="dot"></span>'))
  }
  function refresh() {
    syncFilterDot()
    pills.innerHTML = pillsHtml(state.filters)
    empty.textContent = 'No combos match these filters.'
    load(true)
  }
  head.querySelector('#c-sort').addEventListener('click', () => openSortSheet(refresh))
  // Chips come from the games library, so the sheet can be built without
  // waiting on (or depending on) whatever combo page is loaded.
  filterBtn.addEventListener('click', () => openFilterSheet(facetsOf(lib), refresh))
  syncFilterDot()
  pills.innerHTML = pillsHtml(state.filters)

  sentinel.addEventListener('click', () => { if (!done) load(false) })
  if (typeof IntersectionObserver !== 'undefined') {
    const io = new IntersectionObserver((es) => {
      if (es.some((x) => x.isIntersecting) && !done && !loading) load(false)
    }, { rootMargin: '600px' })
    io.observe(sentinel)
  }

  // Paint the cached opening page first so the tab is instant (and readable on
  // a train with no signal), then let the live query replace it. keepRows on
  // that first load means the cached rows stay up while the request is in
  // flight instead of blinking out.
  ;(async () => {
    const hit = await cachedComboPage(sigOf())
    if (hit && !rows.length && epoch === 0) {
      rows = hit.combos || []
      total = hit.total ?? null
      appendRows(rows)
      paintCount()
    }
    load(true, { keepRows: rows.length > 0 })
  })()

  head.querySelector('#c-playall').addEventListener('click', async () => {
    // The server's filtered order, not the DOM's: "Play all" on a 12,000-combo
    // filter should start at that filter's real first combo.
    try {
      const { combos } = await queryCombos({
        ...queryOf(state.filters, state.sort), limit: PLAY_ALL, offset: 0,
      })
      if (combos.length) openTheater(combos, 0)
      else toast('No combos match these filters.')
    } catch {
      if (rows.length) openTheater(rows.slice(0, PLAY_ALL), 0)
      else toast('Could not reach your library.')
    }
  })

  listHost.addEventListener('click', (e) => {
    const row = e.target.closest('.combo-row')
    if (!row) return
    const c = rows[Number(row.dataset.i)]
    if (c) onOpen(c)
  })
}
