/**
 * A Patreon sign-out whose clear never reached the backend (it was down or
 * restarting). Kept in localStorage so the next launch's token mirror sends the
 * clear again: without it the backend kept the old token across a restart and
 * went on uploading for the signed-out account (F-E-5). Only the window that
 * signed out holds it, so a window that never had the token still cannot sign
 * the backend out.
 */
const KEY = 'nucleus.patreon.signOutPending'

export function markSignOutPending(storage = globalThis.localStorage) {
  try { storage.setItem(KEY, '1') } catch { /* storage unavailable */ }
}

export function clearSignOutPending(storage = globalThis.localStorage) {
  try { storage.removeItem(KEY) } catch { /* storage unavailable */ }
}

export function signOutPending(storage = globalThis.localStorage) {
  try { return storage.getItem(KEY) === '1' } catch { return false }
}
