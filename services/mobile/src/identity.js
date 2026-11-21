// identity — which connect codes are the player's own.
//
// The desktop knows this from its settings and stamps `user_port` (and the
// W/L that depends on it) into every synced game. But games synced before a
// code was added, games from a second code, and anything the desktop got wrong
// stay unattributed, and the phone has no way to say "that one's me" — so this
// is the phone's copy of that setting.
//
// The list lives in vault_prefs.user_codes, so setting it here shows up on
// every paired device (and the desktop's next sync can true it up). Locally it
// is applied on top of the synced rows: a game whose player matches one of the
// codes gets user_port, and its result is re-derived if the desktop never
// decided one. That derivation is deliberately weaker than the desktop's —
// the phone has end stocks but not placements or end-of-game percents — so it
// only claims a winner when the stocks are unambiguous.
import { prefsGet, prefsSet } from './api'
import { el, esc, toast, sheet, num } from './ui'

const CODES_KEY = 'nucleus.vault.codes'

let codes = []          // uppercase, in the order the user picked them
let loadedLocal = false

function loadLocal() {
  if (loadedLocal) return
  loadedLocal = true
  try {
    const raw = localStorage.getItem(CODES_KEY)
    if (raw) codes = (JSON.parse(raw) || []).map((c) => String(c).toUpperCase())
  } catch { /* private mode — the vault copy will refill it */ }
}

function saveLocal() {
  try { localStorage.setItem(CODES_KEY, JSON.stringify(codes)) } catch { /* quota */ }
}

export function getCodes() {
  loadLocal()
  return codes
}

/** Pull the vault's copy. The device that last set it wins, because the list
 * is a setting the player edits deliberately rather than something each device
 * derives — silently unioning would make removing a code impossible. */
export async function syncCodes() {
  loadLocal()
  try {
    const p = await prefsGet()
    if (Array.isArray(p.user_codes)) {
      const remote = p.user_codes.map((c) => String(c).toUpperCase())
      const changed = remote.length !== codes.length
        || remote.some((c, i) => c !== codes[i])
      if (changed) {
        codes = remote
        saveLocal()
        return true
      }
    }
  } catch { /* offline: whatever this phone has is what it uses */ }
  return false
}

export function setCodes(list) {
  loadLocal()
  codes = [...new Set(list.map((c) => String(c).trim().toUpperCase()).filter(Boolean))]
  saveLocal()
  // fire-and-forget: the codes are already in effect locally, and a failed
  // write must not block the UI or lose the local change
  prefsSet({ user_codes: codes }).catch(() => {})
}

const upper = (s) => String(s || '').toUpperCase()

/** Stocks-only W/L. Anything but a clean stock difference stays undecided —
 * a tie on stocks needs end-of-game percents, which the phone doesn't have. */
function resultFromStocks(g, port) {
  const players = g.players || []
  if (players.length !== 2) return null
  const opp = players.find((p) => p.port !== port)
  if (!opp) return null
  const st = g.end_stocks || {}
  const mine = st[String(port)]
  const theirs = st[String(opp.port)]
  if (mine == null || theirs == null || mine === theirs) return null
  return mine > theirs ? 'win' : 'loss'
}

/** Re-attribute a library to the player's codes. Games the desktop already
 * got right pass through untouched. */
export function applyIdentity(games) {
  loadLocal()
  if (!codes.length) return games
  const set = new Set(codes)
  return games.map((g) => {
    const mine = (g.players || []).find((p) => set.has(upper(p.code)))
    if (!mine || mine.port === g.user_port) return g
    // The desktop's verdict came from placements, which are stronger than
    // stocks — so when it decided a 1v1 and we're only changing WHO the
    // player is, flip its answer instead of re-deriving a weaker one.
    const flipped = (g.players || []).length === 2 && g.result && g.user_port != null
      ? (g.result === 'win' ? 'loss' : 'win')
      : resultFromStocks(g, mine.port)
    return { ...g, user_port: mine.port, result: flipped }
  })
}

/** Every code in the library, most-played first — the candidate list. */
export function codeStats(games) {
  const seen = new Map()
  for (const g of games) {
    for (const p of g.players || []) {
      const code = upper(p.code)
      if (!code) continue
      let row = seen.get(code)
      if (!row) { row = { code, games: 0, names: new Map() }; seen.set(code, row) }
      row.games++
      if (p.name) row.names.set(p.name, (row.names.get(p.name) || 0) + 1)
    }
  }
  return [...seen.values()]
    .map((r) => ({
      code: r.code,
      games: r.games,
      name: [...r.names.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || null,
    }))
    .sort((a, b) => b.games - a.games)
}

const CHECK = '<span class="sheet-row-check">✓</span>'

/** "My connect codes" — tick the codes you play under. The top of the list is
 * whatever appears most in the library, which is almost always the answer. */
export function openCodesSheet(games, onChange) {
  loadLocal()
  const sh = sheet('My connect codes')
  const chosen = new Set(codes)
  const stats = codeStats(games)
  // a code the player picked on another device may not appear in the games
  // this phone has pulled — keep it visible so it can still be unticked
  for (const c of codes) {
    if (!stats.some((s) => s.code === c)) stats.unshift({ code: c, games: 0, name: null })
  }

  sh.body.appendChild(el(`<p class="lede" style="margin:2px 6px 10px">
    Tick the codes that are you. Games you play under them get scored as
    yours — wins, losses, and which combos are yours rather than done to you.
  </p>`))

  const list = el('<div></div>')
  sh.body.appendChild(list)

  const draw = () => {
    list.innerHTML = ''
    for (const s of stats.slice(0, 40)) {
      const on = chosen.has(s.code)
      const row = el(`<button class="sheet-row ${on ? 'is-on' : ''}">
        <span class="sheet-row-text">
          <span class="sheet-row-label">${esc(s.code)}${s.name ? ` · ${esc(s.name)}` : ''}</span>
          <span class="sheet-row-sub">${s.games ? `${num(s.games)} games` : 'from another device'}</span>
        </span>
        ${on ? CHECK : ''}
      </button>`)
      row.addEventListener('click', () => {
        if (chosen.has(s.code)) chosen.delete(s.code)
        else chosen.add(s.code)
        draw()
      })
      list.appendChild(row)
    }
  }
  draw()

  const save = el('<button class="cta" style="margin:12px 6px 4px">Save</button>')
  save.addEventListener('click', () => {
    setCodes([...chosen])
    sh.close()
    toast(chosen.size
      ? `${chosen.size} code${chosen.size > 1 ? 's' : ''} saved — re-scoring your games.`
      : 'Codes cleared — games fall back to what the desktop synced.')
    onChange?.()
  })
  sh.body.appendChild(save)
}
