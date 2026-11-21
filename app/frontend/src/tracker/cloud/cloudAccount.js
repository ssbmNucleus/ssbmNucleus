/**
 * cloudAccount.js — which account the Cloud card's phones and pairing code
 * belong to. Pure, so `node --test` covers it.
 */

/** The card's account after a token was sent to the backend. Linking a second
 * Patreon keeps `configured` true, so that flag alone left the first account's
 * phones and pairing code on screen (F-E-4); a new epoch drops them. */
export function nextAccount(account, token) {
  const id = token || null
  return account.token === id ? account : { token: id, epoch: account.epoch + 1 }
}

/** What the phone list says about the pairing code on screen: 'listed' once
 * its phone is in the list, 'revoked' when a phone seen there has left it,
 * else 'waiting' (the list from before the pair is still loading). A revoked
 * phone's code no longer works and must not stay up (F-E-11). */
export function pairedPhoneState(deviceId, devices, seen) {
  if (deviceId == null) return 'waiting'
  if (devices.some((device) => device.id === deviceId)) return 'listed'
  return seen ? 'revoked' : 'waiting'
}
