import { useEffect, useState } from 'react'
import { getEntitlement, getPatreonToken, ENTITLEMENT_EVENT } from './entitlement'
import { isCloudPaid, cloudPledgeKnown } from './cloudPlan'

// Premium = paid access to the cloud's paid half (the phone app and
// whole-library sync): any paid Patreon tier, keyed by the stored Patreon app
// token, completely independent of the Nucleus account. NOT ai-entitlement's
// `active`, which also covers AI-only access (grants, the free pot) and drops
// to false for payers while AI is paused (see cloudPlan.js). The free surfaces
// (Replays, Combos, start.gg) never call this. Re-checks on window focus +
// entitlement events so linking or pledging in the browser unlocks the app as
// soon as the user returns.

// ── dev-only tier override ──
// The header's debug chip (DEV builds only) can force premium on/off so both
// tiers are previewable without touching a real Patreon pledge. Production
// builds ignore the key entirely.
const DEBUG_KEY = 'nucleus.debug.premium'
export const DEBUG_PREMIUM_EVENT = 'nucleus:debug-premium'

export function getPremiumOverride() {
  if (!import.meta.env.DEV) return null
  try {
    const v = localStorage.getItem(DEBUG_KEY)
    return v === 'on' ? true : v === 'off' ? false : null
  } catch {
    return null
  }
}

export function setPremiumOverride(value) { // true | false | null (= real tier)
  try {
    if (value == null) localStorage.removeItem(DEBUG_KEY)
    else localStorage.setItem(DEBUG_KEY, value ? 'on' : 'off')
  } catch { /* storage unavailable */ }
  window.dispatchEvent(new Event(DEBUG_PREMIUM_EVENT))
}

// `failed`: the answer says nothing about the pledge (the check errored, or AI
// is paused and the answer dropped it), so `premium` is a guess, not an
// answer. Anything that persists the pledge (the Cloud card's mirror to the
// backend autorun) must not store that guess.
// `ent` is the raw ai-entitlement answer (undefined until it lands) for callers
// that need more than yes/no (cloudPlan).
export function usePremium() {
  const [state, setState] = useState({ premium: false, loading: true, failed: false, ent: undefined })
  const [override, setOverride] = useState(getPremiumOverride)

  useEffect(() => {
    let live = true
    const check = async () => {
      const token = getPatreonToken()
      let ent
      try {
        ent = await getEntitlement()
      } catch {
        ent = { checkFailed: true } // offline -> treat as not premium, but say so
      }
      // A re-link while this ran started a newer check; its answer wins.
      if (!live || getPatreonToken() !== token) return
      setState({ premium: isCloudPaid(ent), loading: false, failed: !cloudPledgeKnown(ent), ent })
    }
    check()
    const onFocus = () => check()
    const onDebug = () => setOverride(getPremiumOverride())
    window.addEventListener('focus', onFocus)
    window.addEventListener(DEBUG_PREMIUM_EVENT, onDebug)
    window.addEventListener(ENTITLEMENT_EVENT, onFocus) // Patreon link/log-out
    return () => {
      live = false
      window.removeEventListener('focus', onFocus)
      window.removeEventListener(DEBUG_PREMIUM_EVENT, onDebug)
      window.removeEventListener(ENTITLEMENT_EVENT, onFocus)
    }
  }, [])

  if (override != null) return { ...state, premium: override, loading: false, failed: false, overridden: override }
  return state
}
