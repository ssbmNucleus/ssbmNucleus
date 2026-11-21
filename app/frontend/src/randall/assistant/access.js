// Whether Randall can be asked anything, and the one sentence that says why not.
//
// The billing contract, as the product actually works: a Patreon member signs
// in, Nucleus mints a provider key for THAT member, and every AI request is
// billed to that key against a monthly budget. There is no shared pot and no
// allowance included with the app, so this file never says "your included
// allowance" or names Tracker. `remaining` is whatever the entitlement service
// reports is left this month; when it reports nothing, nothing is claimed.
//
// What the user sees (owner's rule): never dollars, "credit" or the provider's
// name. The budget stays in USD behind the scenes (`period_budget`,
// `remaining`, `usage`, `resets_at`, `monthly_budget`); the UI shows only how
// much of it is used, as a bar, when it resets, and a warning when low.
//
// Keys are never persisted here -- the key rides one request, as Tracker does.
// Budgets reset on the 1st of each month (UTC). The entitlement carries the
// exact moment as resets_at; older servers don't, so fall back to "the 1st".
function resetDate(entitlement) {
  const at = entitlement?.resets_at ? new Date(entitlement.resets_at) : null
  if (!at || Number.isNaN(at.getTime())) return null
  return at.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' })
}

export function budgetResetLabel(entitlement) {
  return resetDate(entitlement) || 'on the 1st'
}

// A USD field as a number; NaN when it is missing (Number(null) and Number('') are 0, which is not "missing").
const usd = value => value === null || value === undefined || value === '' ? NaN : Number(value)

// Everyone also has a small free pot that refills to full every 3 days; patrons spend it first, then their
// monthly budget. So a free-only person (`monthly_budget` 0) gets usage back at the next free refill
// (`free_refills_at`), anyone with a monthly budget at the monthly reset. Both fields are newer than the rest:
// without them, the monthly reset as before. -> the free refill's moment, or null.
function freeRefillAt(entitlement) {
  if (usd(entitlement?.monthly_budget) !== 0 || !entitlement?.free_refills_at) return null
  const at = new Date(entitlement.free_refills_at)
  return Number.isNaN(at.getTime()) ? null : at
}

// "in 2 days", "in 5 hours", or "soon" when it is already due (the next check refills it).
function refillsIn(at, now) {
  const hours = (at.getTime() - now) / 3_600_000
  if (!(hours > 0)) return 'soon'
  if (hours < 23.5) {
    const count = Math.max(1, Math.round(hours))
    return `in ${count} hour${count === 1 ? '' : 's'}`
  }
  const days = Math.round(hours / 24)
  return `in ${days} day${days === 1 ? '' : 's'}`
}

/**
 * When this person's usage comes back, worded to follow "resets"/"refills": `{free, when}`. A free-only person
 * waits for the free refill ("in 2 days"), anyone else for the monthly reset ("Nov 1", or "on the 1st").
 */
export function refillLabel(entitlement, now = Date.now()) {
  const at = freeRefillAt(entitlement)
  return at ? { free: true, when: refillsIn(at, now) } : { free: false, when: budgetResetLabel(entitlement) }
}

/**
 * This month's Randall usage as the UI may show it: the share used (0..1), whether the limit is reached, when it
 * resets and the bar's words. Never an amount. Null when the entitlement reports nothing to measure: no `remaining`,
 * or something left but no budget to measure it against (a share there would be a guess). `free`: a free-only
 * person, whose usage refills every 3 days rather than monthly (refillLabel).
 */
export function monthlyUsage(entitlement, now = Date.now()) {
  if (!entitlement?.active || entitlement.remaining == null) return null
  const remaining = Number(entitlement.remaining)
  if (!Number.isFinite(remaining)) return null
  // The limit is reached exactly when assistantAccess stops Randall, so the bar never says so while he still answers.
  const limitReached = remaining <= 0
  // Older entitlement responses named the budget weekly_allowance or limit.
  const budget = Number(entitlement.period_budget) || Number(entitlement.weekly_allowance) || Number(entitlement.limit) || 0
  if (!limitReached && !(budget > 0)) return null
  const used = limitReached ? 1 : Math.max(0, Math.min(1, (budget - remaining) / budget))
  const { free, when: resets } = refillLabel(entitlement, now)
  const text = free ? limitReached ? `Free usage used up - refills ${resets}` : 'Free usage'
    : limitReached ? `Monthly limit reached - resets ${resets}` : 'Monthly usage'
  return { used, limitReached, free, resets, text }
}

// The low-usage warning (owner's rule: it only warns; the person can always still send, and a job that runs out
// partway is accepted). Under these `remaining` amounts (USD, internal, never shown) the chat's next job may not
// finish: a costume or stage retexture, a model import, any other chat turn.
export const LOW_USAGE_UNDER = { retexture: 0.04, import: 0.01, chat: 0.005 }
// From status.tasks ids (backend recipes.LAUNCHABLE), the empty chat's picker (startPick.pickerFor) and the
// kind of its starting pick (CostumePicker's 'vault'/'stock'/'fighter', StagePicker's 'stage').
const TASK_JOBS = new Map([['recolor_part', 'retexture'], ['recolor_stage', 'retexture'], ['model_import', 'import']])
const PICKER_JOBS = new Map([['costume', 'retexture'], ['stage', 'retexture'], ['fighter', 'import']])
const PICK_JOBS = new Map([['vault', 'retexture'], ['stock', 'retexture'], ['stage', 'retexture'], ['fighter', 'import']])

/**
 * The composer's notice when the person is low for what this chat's next message runs, else null:
 * `{job, text, refill}` with `job` 'retexture' | 'import' | 'chat'. Words and a date, never an amount. The chat is
 * described by the panel's `task`, `picker` and start `pick`, and `importing` (a model import already under way in
 * a chat started without a task). Nothing at zero: assistantAccess locks the composer then and says when it resets.
 */
export function lowUsageWarning(entitlement, { task = null, picker = null, pick = null, importing = false } = {}, now = Date.now()) {
  if (!entitlement?.active) return null
  const job = TASK_JOBS.get(task) || PICKER_JOBS.get(picker) || PICK_JOBS.get(pick?.kind) || (importing ? 'import' : 'chat')
  const remaining = usd(entitlement.remaining)
  if (!(remaining > 0) || remaining >= LOW_USAGE_UNDER[job]) return null
  const at = freeRefillAt(entitlement)
  return { job, text: "You're low on Randall usage, so this may stop partway.",
    refill: at ? `Free usage refills ${refillsIn(at, now)}.` : `Refills on ${resetDate(entitlement) || 'the 1st'}.` }
}

export function assistantAccess(status, entitlement, now = Date.now()) {
  if (!status || entitlement === null) return { ready: false, source: 'checking', label: 'Checking AI access…' }
  if (entitlement?.active) {
    if (entitlement.remaining != null && Number(entitlement.remaining) <= 0) {
      const { free, when } = refillLabel(entitlement, now)
      return { ready: false, source: 'patreon', usedUp: true, label: free
        ? `You've used up your free Randall usage. It refills ${when}. Setup and browsing still work.`
        : `You've reached this month's Randall limit. It resets ${when}. Setup and browsing still work.` }
    }
    if (!entitlement.api_key) return { ready: false, source: 'patreon', label: 'Your Randall access is not ready yet. Check again.' }
    return { ready: true, source: 'patreon', key: entitlement.api_key, label: 'Connected through Patreon' }
  }
  if (entitlement?.paused) return { ready: false, source: 'paused', paused: true,
    label: 'Randall is paused right now. Setup and browsing still work. Check back soon.' }
  // Linked, but Patreon does not list them as a member of sc00p's campaign
  // (often: they followed instead of joining, or joined after linking). The
  // composer offers "Join free" and "Check again"; the server re-reads their
  // membership on that check, so no re-link is needed.
  if (entitlement?.reason === 'campaign_membership_required') return { ready: false, source: 'none', joinFree: true,
    label: 'Join sc00p on Patreon for free (not just Follow), then press Check again.' }
  if (entitlement?.checkFailed) return { ready: false, source: 'error', label: 'Could not check your Patreon link. Please try again.' }
  return { ready: false, source: 'none', label: entitlement?.linked
    ? 'This Patreon account does not have Randall access right now.'
    : 'Connect Patreon to chat with Randall. Setup and browsing work without it.' }
}
