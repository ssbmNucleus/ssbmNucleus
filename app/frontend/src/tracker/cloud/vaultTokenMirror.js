import { isCloudPaid, cloudPledgeKnown } from '../../shared/account/cloudPlan.js'

/**
 * Keep the backend's copy of the Patreon app token current, from anywhere in
 * the app.
 *
 * The automatic upload (backend tracker/cloud/vault_jobs.py) reads the token
 * from the backend's kv, because localStorage is out of its reach. Until
 * 0.8.12 only the Settings → Cloud card sent it, and only on mount. A sign-out
 * (or the automatic one when ai-entitlement answers invalid_token) clears the
 * backend copy at once, so after a re-link the backend stayed tokenless until
 * someone opened that card: from 2026-10-04 to 10-15, games played behind an
 * open Nucleus were indexed and none were uploaded.
 *
 * This runs at launch and on every entitlement change instead. It only ever
 * sends a token that exists. Clearing the backend copy stays with
 * clearPatreonToken() (an explicit sign-out) and the Cloud card, so a window
 * whose localStorage simply lacks the token (another Electron profile, a dev
 * build pointed at the same backend) cannot sign the backend out. The one
 * exception is this window's own sign-out whose clear never landed
 * (signOutPending): that clear is sent again here (F-E-5).
 *
 * `active` (the pledge) rides along only when the entitlement check answered.
 * An offline check reads as "not premium", and mirroring that would switch the
 * backend's auto-sync off until the next online visit to the Cloud card. It is
 * the CLOUD pledge (isCloudPaid), not ai-entitlement's `active`: AI free mode
 * makes a $0 member AI-active, and that must not unlock a library upload.
 */
export function createVaultTokenMirror({ getToken, checkEntitlement, post,
                                        signOutPending = () => false, clearSignOutPending = () => {} }) {
  return async function mirror() {
    const token = getToken()
    if (!token) {
      if (!signOutPending()) return
      try {
        await post({ token: null })
        clearSignOutPending()
      } catch { /* still unreachable: the next launch or event tries again */ }
      return
    }
    let active
    try {
      const ent = await checkEntitlement()
      if (typeof ent?.active === 'boolean' && cloudPledgeKnown(ent)) active = isCloudPaid(ent)
    } catch { /* offline or edge function down: leave the stored pledge alone */ }
    // The check itself signs out on invalid_token, and a re-link can land
    // while it runs; either way this token is no longer the one to send.
    if (getToken() !== token) return
    try {
      await post(active === undefined ? { token } : { token, active })
    } catch { /* gated build (404), backend down, or a token the vault refused */ }
  }
}
