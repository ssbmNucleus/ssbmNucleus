// main — auth gate, tab shell, and the library lifecycle: render instantly
// from the IndexedDB cache, refresh from the vault in the background.
// Everything that opens a game goes through the detail overlay (player +
// summary + the game's combos + share).
import {
  getToken, setToken, cachedLibrary, fetchLibrary, cachedCombos, fetchCombos,
} from './api'
import { claimTokenFromHash } from './account-generation'
import { el, esc, toast, num, sheet, sheetRow } from './ui'
import { renderGames } from './games'
import { renderCombos } from './combos'
import { renderStats } from './stats'
import { renderTournaments } from './tournaments'
import { renderRandall } from './randall'
import { openDetail, closeDetail } from './detail'
import { applyIdentity, syncCodes, openCodesSheet, getCodes } from './identity'
import { openScanner } from './scan'

const app = document.getElementById('app')
const tabbar = document.getElementById('tabbar')

const ICONS = {
  games: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round">
    <rect x="3" y="5" width="18" height="4.5" rx="1.5"/>
    <rect x="3" y="12" width="18" height="4.5" rx="1.5" opacity=".55"/>
    <path d="M3 20.5h18" opacity=".3"/></svg>`,
  combos: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round">
    <path d="M13 2 4.5 13.5H11L9.5 22 19 9.5h-6.5L13 2z"/></svg>`,
  stats: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round">
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>`,
  tourney: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round">
    <path d="M8 4h8v5a4 4 0 0 1-8 0V4zM8 5H5a1 1 0 0 0-1 1v1a3 3 0 0 0 3 3M16 5h3a1 1 0 0 1 1 1v1a3 3 0 0 1-3 3"/>
    <path d="M12 13v4M8.5 21h7M12 17c-1.5 0-2.5 1-3.5 4M12 17c1.5 0 2.5 1 3.5 4"/></svg>`,
  // Randall is a cloud (the Yoshi's Story one) — so the icon is a cloud.
  randall: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round">
    <path d="M6.8 18.5a4.3 4.3 0 0 1-.55-8.57 5.8 5.8 0 0 1 11.24-1.2A4.15 4.15 0 0 1 16.9 18.5H6.8z"/></svg>`,
}

// Randall is hidden until his release — same gate as the desktop's
// RANDALL_ENABLED (frontend/src/shared/config/features.js). The tab, its renderer, and
// the combo corpus it feeds on all stay in the bundle; only the entry point
// goes away. Flip this back to true to re-surface him.
const RANDALL_ENABLED = false

const TABS = [
  ['games', 'Games'],
  ['combos', 'Combos'],
  ['stats', 'Stats'],
  ['tourney', 'Tourney'],
  ...(RANDALL_ENABLED ? [['randall', 'Randall']] : []),
]

// raw* hold the vault's rows as synced; games/combos are what the tabs see,
// after the player's own connect codes are applied on top (identity.js) and
// the unsurfaceable rows are filtered out. Keeping both means changing your
// codes re-scores the library instantly, with no refetch.
const store = {
  games: [], combos: [], rawGames: [], rawCombos: [],
  tab: 'games', loaded: false, fetchedAt: null,
  crawling: false,   // a library crawl is still paging in (see boot)
}

function applyLibrary() {
  const games = applyIdentity(store.rawGames)
  store.games = surfaceable(games)
  // Combos are scoped to the games that survived: a game not worth listing
  // (CPU practice, modded characters) has no combos worth showing either.
  store.combos = surfaceableCombos(store.rawCombos, store.games)
}

// Desktop parity (indexer.VANILLA_STAGE_IDS / VANILLA_CHAR_IDS): games on
// modded stages or featuring modded characters ("Char 26") are synced but
// never surfaced — no names, no icons, and the renderer can't dress them.
const VANILLA_STAGES = new Set([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
  15, 16, 17, 18, 19, 20, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32])
const vanillaChar = (c) => c != null && c >= 0 && c <= 25

// The desktop's list is a JOIN on your connect codes (indexer._build_filter:
// `me.code IN (...)`), so a game you are not in — CPU practice, offline VS,
// anything pre-rollback with no codes at all — is indexed but never listed.
// The phone synced all of them and showed them as unattributed rows with a
// blank result. Matching the rule rather than blacklisting CPUs catches the
// whole class, and it is why the desktop never needed a `type` check here.
//
// The exception is a phone with no codes claimed yet: filtering on an empty
// set would show an empty app, so it falls back to showing everything.
function surfaceable(games) {
  const claimed = getCodes().length > 0
  return games.filter((g) => VANILLA_STAGES.has(g.stage)
    // solo training-mode replays (one port) aren't watchable games — the
    // corpus has hundreds and they rendered as weird one-player rows
    && (g.players || []).length >= 2
    && (!claimed || g.user_port != null)
    // the desktop's month buckets require a date (`g.start_at IS NOT NULL`),
    // so an undated replay is unreachable there — no "Unknown date" section
    && !!g.start_at
    && (g.players || []).every((p) => vanillaChar(p.character)))
}
function surfaceableCombos(combos, games) {
  // Tag each combo with whose it is: the detector indexes BOTH directions, so
  // "my combos" vs "me getting comboed" is an attribution, not a query.
  //
  // Port against the game's user_port is the precise answer, but it depends on
  // two fields either of which can be missing — and when the port was absent
  // the Combos tab silently emptied instead of degrading. So the connect code
  // on the combo itself is the fallback, and an unattributable combo stays
  // null rather than being claimed.
  const portByGame = new Map(games.map((g) => [g.id, g.user_port]))
  const codes = new Set(getCodes())
  return combos
    .filter((c) => portByGame.has(c.game_id)
      && vanillaChar(c.character) && vanillaChar(c.opp_character))
    .map((c) => {
      const up = portByGame.get(c.game_id)
      let mine = null
      if (up != null && c.port != null) mine = c.port === up
      else if (codes.size && c.code) mine = codes.has(String(c.code).toUpperCase())
      return { ...c, mine }
    })
}

const byHash = (hash) => store.games.find((g) => g.content_hash === hash)

function openGame(g) {
  openDetail(g)
}

function openCombo(c) {
  const vg = c.vault_games || {}
  const g = byHash(vg.content_hash)
  if (!g) { toast('Game not in the library yet — pull to refresh.'); return }
  openDetail(g, {
    focusStartFrame: c.start_frame,
    focusEndFrame: c.end_frame,
    focusDamage: c.damage,
    focusPort: c.port,
  })
}

// ── settings sheet: vault info + the disconnect that can't be fat-fingered ──
function openSettings() {
  const sh = sheet('Vault')
  const synced = num(store.games.length)
  const when = store.fetchedAt
    ? new Date(store.fetchedAt).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : '—'
  sh.body.appendChild(sheetRow({
    label: `${synced} games synced`,
    sub: `Library refreshed ${when} · sync more from desktop`,
  }))
  const refresh = sheetRow({ label: 'Refresh library', sub: 'Pull the latest games from your cloud library' })
  refresh.addEventListener('click', () => { sh.close(); boot(true) })
  sh.body.appendChild(refresh)

  const mine = getCodes()
  const codesRow = sheetRow({
    label: 'My connect codes',
    sub: mine.length
      ? mine.join(', ')
      : 'Tell the app which player is you — scores wins and combo direction',
  })
  codesRow.addEventListener('click', () => {
    sh.close()
    openCodesSheet(store.rawGames, () => { applyLibrary(); renderTab() })
  })
  sh.body.appendChild(codesRow)

  const out = sheetRow({
    label: 'Disconnect this device', danger: true,
    sub: 'Removes the token and cached library from this phone',
  })
  out.addEventListener('click', () => {
    sh.close()
    // second look before a destructive action — the old header button got
    // fat-fingered, which is exactly how we ended up here
    const confirm = sheet('Disconnect?')
    confirm.body.appendChild(el(`<p class="lede" style="margin:6px 6px 12px">
      This removes the device token and the cached library from this phone.
      You'll need to scan the pairing code again.</p>`))
    const yes = sheetRow({ label: 'Yes, disconnect', danger: true })
    yes.addEventListener('click', () => {
      setToken('')
      indexedDB.deleteDatabase('nucleus-vault')
      location.reload()
    })
    confirm.body.appendChild(yes)
  })
  sh.body.appendChild(out)
}

// direction: 'left' | 'right' | null. Tab taps pass the side the new page
// should slide in from (vAMP's tab-slide); data refreshes pass nothing and
// repaint in place with no animation.
function renderTab(direction = null) {
  closeDetail(false)
  const slide = direction === 'right' ? ' slide-r' : direction === 'left' ? ' slide-l' : ''
  const view = el(`<div class="wrap${slide}"></div>`)
  app.innerHTML = ''
  app.appendChild(view)
  if (!getToken() && store.tab !== 'tourney') {
    renderConnect(view, store.tab)
    return
  }
  if (store.tab === 'games') {
    renderGames(view, store.games, openGame, openSettings, {
      synced: store.rawGames.length, codes: getCodes(), loading: store.crawling,
    })
  } else if (store.tab === 'combos') {
    // the whole store, not store.combos: the tab queries the vault per filter
    // now (the library is far too large to hold on a phone) and draws its
    // character/stage options from the games list instead of a loaded page
    renderCombos(view, store, openCombo)
  } else if (store.tab === 'stats') {
    renderStats(view, store.games)
  } else if (store.tab === 'tourney') {
    renderTournaments(view, store.games, openGame)
  } else if (store.tab === 'randall') {
    renderRandall(view, store)
  }
}

const tabIndex = (key) => TABS.findIndex(([k]) => k === key)

// Built once; tab switches only move the indicator pill and toggle
// aria-selected. Rebuilding the bar per switch would kill the pill's
// transition (a fresh node has nothing to animate from).
function renderTabbar() {
  tabbar.hidden = false
  tabbar.innerHTML = ''
  const ind = el('<span class="tab-ind" aria-hidden="true"><i></i></span>')
  ind.style.width = `${100 / TABS.length}%`
  // set before insertion so the first paint doesn't animate from slot 0
  ind.style.transform = `translateX(${tabIndex(store.tab) * 100}%)`
  tabbar.appendChild(ind)
  for (const [key, label] of TABS) {
    const b = el(`<button role="tab" data-tab="${key}" aria-selected="${store.tab === key}">
      ${ICONS[key]}<span>${esc(label)}</span></button>`)
    b.addEventListener('click', () => selectTab(key))
    tabbar.appendChild(b)
  }
}

// the bounce animation lives on the svg; clean the class off the button.
// Delegated once — renderTabbar reruns on every boot() and would stack copies.
tabbar.addEventListener('animationend', (e) => {
  if (e.target instanceof Element) e.target.closest('button')?.classList.remove('is-bouncing')
})

function selectTab(key) {
  if (store.tab === key) { window.scrollTo({ top: 0, behavior: 'smooth' }); return }
  const from = tabIndex(store.tab)
  const to = tabIndex(key)
  store.tab = key
  tabbar.querySelector('.tab-ind').style.transform = `translateX(${to * 100}%)`
  for (const b of tabbar.querySelectorAll('button[role="tab"]')) {
    const on = b.dataset.tab === key
    b.setAttribute('aria-selected', String(on))
    b.classList.remove('is-bouncing')
    if (on) { void b.offsetWidth; b.classList.add('is-bouncing') } // restart idiom
  }
  renderTab(to > from ? 'right' : 'left')
  window.scrollTo(0, 0)
}

// ── signed-out shell ──────────────────────────────────────────────────────
// No token doesn't hide the app any more: the tabbar renders and every
// vault-backed tab shows this pairing card in its own frame. Tournaments is
// the exception and renders for real — start.gg identity is public data and
// its proxy takes no vault token, so it works for people without Nucleus.
const TAB_TITLES = {
  games: 'Games', combos: 'Combos', stats: 'Stats', randall: 'Randall',
}

// The tiers page, not the campaign front page: that is where a tier is picked.
const PATREON_URL = 'https://www.patreon.com/cw/ssbmSc00p/membership'
const PHONE_PRICE = 5

// Sell before asking: what the phone app is, what it costs, then the two ways
// in (pledge, or pair if you already have). Desktop Nucleus does the pairing.
function paywallCard() {
  return `<div class="paywall">
      <p class="paywall-eyebrow">Nucleus on your phone</p>
      <h2 class="paywall-title">Your whole replay library, in your pocket</h2>
      <ul class="paywall-perks">
        <li>Every game you play, synced from desktop Nucleus</li>
        <li>Your combos, ready to rewatch</li>
        <li>Your stats by matchup and stage</li>
      </ul>
      <p class="paywall-price"><strong>$${PHONE_PRICE}/month</strong> on Patreon, or any higher tier</p>
    </div>`
}

function renderConnect(view, tab) {
  view.appendChild(el(`<div class="head frosted"><div><h1>${esc(TAB_TITLES[tab] || '')}</h1></div></div>`))
  const body = el(`<div class="pagebody"><div class="connect-hero">
    ${paywallCard()}
    <a class="patreon-cta" href="${PATREON_URL}" target="_blank" rel="noopener">Join on Patreon — $${PHONE_PRICE}/month</a>
    <div class="auth-or">already a member? On desktop: Settings → Cloud → Pair your phone</div>
    <button class="cta" id="scan">Scan pairing code</button>
    <div class="auth-or">or paste the device token</div>
    <input id="token" type="password" placeholder="device token"
           autocomplete="off" autocapitalize="off" spellcheck="false">
    <button class="cta cta--quiet" id="connect">Connect</button>
  </div></div>`)
  body.querySelector('#scan').addEventListener('click', () => {
    openScanner((t) => {
      setToken(t)
      location.reload()
    })
  })
  body.querySelector('#connect').addEventListener('click', () => {
    const t = body.querySelector('#token').value.trim()
    if (!t) return
    setToken(t)
    location.reload()
  })
  view.appendChild(body)
}

// A paired phone whose pledge ended: the vault answers `inactive`. The token
// stays (the pairing is kept on the desktop's side too), so renewing is the
// whole fix; nothing has to be re-paired.
const LAPSED_TEXT = 'Your membership ended. Renew on Patreon and this phone picks up where it left off.'

function renderLapsed() {
  app.innerHTML = ''
  const body = el(`<div class="wrap"><div class="connect-hero">
    <div class="paywall paywall--lapsed">
      <p class="paywall-eyebrow">Still paired</p>
      <h2 class="paywall-title">Your membership ended</h2>
      <p class="paywall-text">Renew on Patreon and this phone syncs again. Nothing to re-pair.</p>
    </div>
    <a class="patreon-cta" href="${PATREON_URL}" target="_blank" rel="noopener">Renew on Patreon — $${PHONE_PRICE}/month</a>
    <button class="cta cta--quiet" id="recheck">Renewed? Check again</button>
  </div></div>`)
  body.querySelector('#recheck').addEventListener('click', () => boot(true))
  app.appendChild(body)
}

// A scanned pairing QR opens this page with the token in the fragment. The
// fragment is used, not a query string, because it never leaves the browser:
// it isn't sent to Pages, doesn't reach a log, and isn't in the Referer of
// anything the page loads. It's stripped from the URL immediately either way,
// so a screenshot or a shared link can't carry the token onward.
function claimTokenFromUrl() {
  if (!claimTokenFromHash(location.hash || '')) return
  history.replaceState(null, '', location.pathname + location.search)
}

async function boot(force = false) {
  claimTokenFromUrl()
  renderTabbar()
  if (!getToken()) { renderTab(); return }

  // cache first: the vault opens instantly on a train with no signal
  if (!force) {
    // the combo corpus exists solely for Randall's local tools — while he is
    // gated off, don't spend a request (or IDB read) on it
    const [lib, combos] = await Promise.all([
      cachedLibrary(), RANDALL_ENABLED ? cachedCombos() : null])
    if (lib?.games?.length) {
      store.rawGames = lib.games
      store.rawCombos = combos?.combos || []
      applyLibrary()
      store.fetchedAt = lib.fetched_at
      store.loaded = true
      renderTab()
    } else {
      app.innerHTML = '<div class="wrap"><p class="spin">Loading your library…</p></div>'
    }
  } else {
    app.innerHTML = '<div class="wrap"><p class="spin">Refreshing your library…</p></div>'
    store.loaded = false
  }

  // then refresh from the vault
  try {
    // Codes first: they decide what gets listed, and the list now paints
    // before the crawl ends — scoring the first page with stale (or, on a
    // fresh phone, no) codes would flash the wrong games. One small request.
    await syncCodes()
    store.crawling = true
    const fresh = await fetchLibrary((n, soFar) => {
      if (store.loaded) return
      // Bug #64: list games as soon as a page brings any listable ones,
      // instead of holding a big vault (44k games = 44 pages) behind a
      // spinner until the very last page lands. Paints ONCE — later pages
      // wait for the final re-render, so a reader's scroll isn't yanked
      // every second.
      store.rawGames = soFar.slice()
      applyLibrary()
      if (store.games.length) {
        store.loaded = true
        renderTab()
      } else {
        app.innerHTML = `<div class="wrap"><p class="spin">Loading your library… ${n.toLocaleString()} games</p></div>`
      }
    }).finally(() => { store.crawling = false })
    const freshCombos = RANDALL_ENABLED
      ? await fetchCombos().catch(() => null) : null
    const before = { games: store.games.length, combos: store.combos.length }
    store.rawGames = fresh.games
    if (freshCombos) store.rawCombos = freshCombos.combos
    store.fetchedAt = fresh.fetched_at
    // codes were pulled before the crawl (a code added on the desktop still
    // lands on the phone in the same pass)
    applyLibrary()
    const changed = store.games.length !== before.games
      || store.combos.length !== before.combos
      // an empty list's explanation depends on the raw count too
      || (!store.games.length && store.tab === 'games')
    if (!store.loaded || changed) {
      store.loaded = true
      renderTab()
    }
  } catch (e) {
    if (String(e.message).includes('invalid_token')) {
      setToken('')
      boot()
      toast('This device token is no longer valid — pair again from desktop.')
      return
    }
    if (String(e.message) === 'inactive') {
      // What is already on the phone stays readable (a forced refresh blanked
      // the screen first, so bring it back); say why it stopped updating.
      if (store.rawGames?.length) {
        if (!store.loaded) { store.loaded = true; renderTab() }
        toast(LAPSED_TEXT, 8000)
      } else renderLapsed()
      return
    }
    if (!store.loaded) {
      app.innerHTML = `<div class="wrap"><p class="empty">Could not reach your library.<br>${esc(e.message)}</p></div>`
    }
  }
}

boot()
