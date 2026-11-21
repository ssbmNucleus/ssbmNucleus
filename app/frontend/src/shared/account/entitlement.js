/**
 * Coach entitlement — asks the website's Supabase edge function whether the
 * linked Patreon account has an active "Friend of Randall" membership and,
 * if so, returns the per-patron OpenRouter key + what is left of this month's
 * budget (it resets on the 1st, UTC).
 *
 * The identity is a Patreon app token minted by the patreon-link edge fn and
 * handed to the app via the nucleus://patreon-link deep link. No Nucleus
 * account is involved anywhere — the token IS the Patreon identity.
 *
 * Response shape (from ai-entitlement):
 *   { linked, active, paused?, patron_status, patreon_name, api_key?,
 *     period_budget?, remaining?, usage?, resets_at?, ... }
 * The budget fields are USD. The UI never shows them as money: only the share
 * used and the reset date (randall/assistant/access.js, monthlyUsage).
 */
import { api } from '../transport/api'
import { clearSignOutPending, markSignOutPending } from './signOutPending'
import { startPatreonLink } from './patreonLinkGuard'

const TTL_MS = 5 * 60 * 1000
const TOKEN_KEY = 'nucleus.patreon.token'

let cached = null
let fetchedAt = 0
// One request per token at a time: a re-check fans out to every listener of
// the event (Settings, the Cloud card, the launch mirror), and they can share
// it. Never across tokens: a re-link mid-request must not hand the new
// account the old account's answer (a paid pledge would unlock an upload).
let inflight = null
let inflightToken = ''

export const ENTITLEMENT_EVENT = 'nucleus:entitlement-changed'

export function getPatreonToken() {
  try { return localStorage.getItem(TOKEN_KEY) || '' } catch { return '' }
}

/** Store the token from the OAuth handoff; every consumer re-checks via the event. */
export function setPatreonToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token) } catch { /* storage unavailable */ }
  // the new token replaces whatever the backend holds; no clear is owed
  clearSignOutPending()
  clearEntitlement()
  window.dispatchEvent(new Event(ENTITLEMENT_EVENT))
}

/** "Sign out" of Patreon on this machine: forget the app token (re-link any time). */
export function clearPatreonToken() {
  try { localStorage.removeItem(TOKEN_KEY) } catch { /* storage unavailable */ }
  // The backend holds a copy in its kv (the launch autorun needs it before a
  // window exists — VaultSection posts it there on mount). Signing out only
  // here left the Cloud vault card configured and the autorun still syncing
  // with the stored credential. Clear both; fire-and-forget because a gated
  // build 404s the route and a dead backend must not break sign-out. Until the
  // clear lands it stays owed, and the launch mirror sends it again (F-E-5).
  markSignOutPending()
  api.post('/api/nucleome/vault/token', { token: null })
    .then(() => { if (!getPatreonToken()) clearSignOutPending() })
    .catch(() => {})
  clearEntitlement()
  window.dispatchEvent(new Event(ENTITLEMENT_EVENT))
}

/** Cached entitlement for the linked Patreon account. Pass {force:true} after a
 * coach turn (usage moved) or when the user just linked/subscribed. */
export async function getEntitlement({ force = false } = {}) {
  const token = getPatreonToken()
  if (!token) return { linked: false, active: false }
  if (!force && cached && Date.now() - fetchedAt < TTL_MS) return cached
  if (inflight && inflightToken === token) return inflight
  const request = (async () => {
    const { invokeEdgeFunction } = await import('./account')
    const data = await invokeEdgeFunction('ai-entitlement', { token })
    if (data?.invalid_token) {
      // Token rotated by a re-link on another machine (or wiped server-side).
      // Only if it is still the stored one: a newer link owns the slot now.
      if (getPatreonToken() === token) clearPatreonToken()
      return { linked: false, active: false }
    }
    // A sign-out or re-link while this was in flight owns the cache now.
    if (getPatreonToken() === token) {
      cached = data
      fetchedAt = Date.now()
    }
    return data
  })()
  inflight = request
  inflightToken = token
  try {
    return await request
  } finally {
    if (inflight === request) { inflight = null; inflightToken = '' }
  }
}

/** Drop the cache — the next getEntitlement refetches. */
export function clearEntitlement() {
  cached = null
  fetchedAt = 0
}

/** Ask Patreon again, everywhere: after the user went to pledge or join in the
 * browser, every entitlement consumer re-reads on the same event a link uses. */
export function recheckEntitlement() {
  clearEntitlement()
  window.dispatchEvent(new Event(ENTITLEMENT_EVENT))
}

export const PATREON_CAMPAIGN_URL = 'https://www.patreon.com/cw/ssbmSc00p/membership'

/** Open a link in the system browser (a plain tab outside Electron). */
export function openExternal(url) {
  if (window.electron?.openExternal) window.electron.openExternal(url)
  else window.open(url, '_blank', 'noopener')
}

const PATREON_CLIENT_ID = 'aA2lY1JoTMyZgK9byVuh30vAO-j_Ww1ucl50dIStF9PFkUx4W8zPwWntFuBfZ9V3'

/** Direct Patreon OAuth from the app — lands on ssbmnucleus.net/patreon/callback
 * in the browser, which mints the app token and deep-links it back to us.
 * Call it only when the user starts a link: it records the start (and the
 * `state` nonce) that the deep link must answer (patreonLinkGuard.js). */
export function buildPatreonAuthorizeUrl() {
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: PATREON_CLIENT_ID,
    redirect_uri: 'https://ssbmnucleus.net/patreon/callback',
    scope: 'identity identity.memberships',
    state: startPatreonLink(),
  })
  return `https://www.patreon.com/oauth2/authorize?${params}`
}
