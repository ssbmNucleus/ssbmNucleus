/**
 * Which nucleus://patreon-link deep links the app accepts (security review 11-19, M3).
 *
 * Any web page can open a nucleus:// link. Without a check, a page could hand the app an attacker's Patreon token:
 * if that account is paid, cloud sync turns on and the victim's replays upload to the attacker's vault. So:
 *
 * - Linking starts here: `buildPatreonAuthorizeUrl` calls `startPatreonLink`, which records a fresh OAuth `state`
 *   nonce and the time (localStorage, so a restart mid-link keeps it).
 * - A deep link is accepted only within LINK_WINDOW_MS of a link started from this app. When the link carries
 *   `state` (the website echoes Patreon's state back), it must be one of those nonces. Today's website does not
 *   echo it yet, so the time window is the check until it does.
 * - Replacing an already linked account with a different one asks the person first (`decidePatreonLink`); a
 *   re-link of the same account (same Patreon name, as the website reports it for each token) goes through.
 *
 * Accepting a link spends every pending start: one start, one link.
 */
export const LINK_WINDOW_MS = 15 * 60 * 1000
export const PENDING_LINK_KEY = 'nucleus.patreon.pendingLinks'
/** The alert for a link that was ignored. Account is a card on the Files & setup tab (settings/Settings.jsx). */
export const IGNORED_LINK_MESSAGE = 'A Patreon link arrived that this app did not start, so it was ignored. To link '
  + 'Patreon, use Settings > Files & setup > Account.'
const MAX_PENDING = 5

function storageOrNull(storage) {
  if (storage) return storage
  try { return globalThis.localStorage || null } catch { return null }
}

function readPending(storage) {
  try {
    const rows = JSON.parse(storage?.getItem(PENDING_LINK_KEY) || '[]')
    return Array.isArray(rows)
      ? rows.filter(row => row && typeof row.state === 'string' && Number.isFinite(row.startedAt))
      : []
  } catch { return [] }
}

function writePending(storage, rows) {
  try {
    if (rows.length) storage?.setItem(PENDING_LINK_KEY, JSON.stringify(rows))
    else storage?.removeItem(PENDING_LINK_KEY)
  } catch { /* storage unavailable: no link is accepted, which is the safe side */ }
}

function freshState() {
  return globalThis.crypto?.randomUUID?.()
    || Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')
}

/** Record that this app is starting a Patreon link. -> the OAuth `state` nonce to send. */
export function startPatreonLink({ storage, now = Date.now, newState = freshState } = {}) {
  const store = storageOrNull(storage)
  const at = now()
  const state = newState()
  const rows = readPending(store).filter(row => at - row.startedAt <= LINK_WINDOW_MS)
  rows.push({ state, startedAt: at })
  writePending(store, rows.slice(-MAX_PENDING))
  return state
}

/** Whether a patreon-link payload may be taken: {ok, reason}. reason: 'not_started' | 'state_mismatch'. */
export function checkPatreonLink(payload, { storage, now = Date.now } = {}) {
  const at = now()
  const live = readPending(storageOrNull(storage))
    .filter(row => at - row.startedAt <= LINK_WINDOW_MS && row.startedAt <= at + 60_000)
  if (!live.length) return { ok: false, reason: 'not_started' }
  const state = typeof payload?.state === 'string' ? payload.state : ''
  if (state && !live.some(row => row.state === state)) return { ok: false, reason: 'state_mismatch' }
  return { ok: true, stateChecked: Boolean(state) }
}

/** Spend the pending starts (after a link was taken or turned down). */
export function finishPatreonLink({ storage } = {}) {
  writePending(storageOrNull(storage), [])
}

/**
 * Decide one patreon-link deep link. -> true to store its token.
 *
 * `currentToken` is the token already stored ('' when none). `lookupName(token)` resolves the Patreon name the
 * website reports for a token ('' when it cannot tell). `confirm({oldName, newName})` asks the person and
 * resolves true to replace. `refuse(reason)` is told when a link is ignored.
 */
export async function decidePatreonLink(payload, { storage, now = Date.now, currentToken = '', lookupName,
  confirm, refuse = () => {} } = {}) {
  if (!payload?.token) return false
  const verdict = checkPatreonLink(payload, { storage, now })
  if (!verdict.ok) {
    refuse(verdict.reason)
    return false
  }
  finishPatreonLink({ storage })
  if (!currentToken || currentToken === payload.token) return true
  const name = async (token) => {
    try { return String((await lookupName?.(token)) || '').trim() } catch { return '' }
  }
  const [oldName, newName] = await Promise.all([name(currentToken), name(payload.token)])
  if (oldName && newName && oldName === newName) return true
  try {
    return (await confirm?.({ oldName, newName: newName || String(payload.name || '').trim() })) === true
  } catch { return false }
}
