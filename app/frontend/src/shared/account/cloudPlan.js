// Where a linked Patreon stands for the CLOUD: share links, the phone app and
// whole-library sync. Not the same question as ai-entitlement's `active`, which
// answers "may this person use Randall": with AI free mode on, a $0 member is
// AI-entitled from the free pot (active, source 'free'), and with the AI kill
// switch on a paying patron reads active: false. Neither says anything about
// the phone. The vault decides paid access the way _shared/membership.ts
// hasPaidAccess does (a live pledge, or the rest of a paid period), and that
// is what ai-entitlement reports as source 'patreon'.
import { tierFor, tierByName } from './membershipLabel.js'

export const PHONE_PRICE = 5

/** Paid access to the phone app and whole-library sync (any paid tier). */
export function isCloudPaid(ent) {
  if (!ent?.linked) return false
  if (ent.active) {
    // grant and free-pot access are AI-only; older servers send no source
    if (ent.source) return ent.source === 'patreon'
    return ent.membership_class !== 'free'
  }
  // AI paused for everyone: the pledge is still there
  if (ent.paused) return ent.membership_class === 'paid'
  return false
}

/** Whether this answer says anything about the cloud pledge at all. A failed
 * check says nothing, and with AI paused ai-entitlement drops source and
 * grace, so only an explicit 'paid' membership is an answer then (a cancelled
 * patron in their paid month reads as 'none'). An unknown pledge must not be
 * mirrored to the backend or shown as a lapse. */
export function cloudPledgeKnown(ent) {
  if (!ent || ent.checkFailed) return false
  if (!ent.linked) return true
  return !ent.paused || ent.membership_class === 'paid'
}

/** The tier a paid answer is on: ai-entitlement's own tier name when it sends
 * one, else the budget ratio (which a grant can inflate). */
export function paidTier(ent) {
  return tierByName(ent?.tier_name) || tierFor(ent?.tier_multiplier)
}

// patron_status values Patreon gives someone whose paid membership stopped
const LAPSED_STATUSES = ['former_patron', 'declined_patron']

/**
 * One of:
 *   checking    the entitlement check has not answered yet
 *   unknown     it failed (offline, edge function down)
 *   signed_out  no Patreon linked on this machine
 *   non_member  linked, but not a member of sc00p's Patreon (a Follow is not membership)
 *   free        a $0 member: sharing works, the phone does not
 *   paid        any paid tier: everything
 *   lapsed      was paid, is not any more (Patreon says so, or a phone is still paired)
 *
 * `hasPairedPhone` comes from the vault's device list: a phone stays paired when
 * a pledge ends, and nothing else on a non-paying account can have paired one.
 */
export function cloudPlan(ent, { hasPairedPhone = false } = {}) {
  if (ent === undefined) return { state: 'checking' }
  if (ent?.checkFailed) return { state: 'unknown' }
  if (!ent?.linked) return { state: 'signed_out' }
  if (isCloudPaid(ent)) {
    return {
      state: 'paid',
      // A grace period's budget can be 0, which would read as the cheapest
      // tier; the card says when access ends instead of naming a tier.
      tier: ent.grace ? null : paidTier(ent),
      graceUntil: ent.grace ? ent.paid_through || null : null,
    }
  }
  if (LAPSED_STATUSES.includes(ent.patron_status) || hasPairedPhone) {
    return { state: 'lapsed', declined: ent.patron_status === 'declined_patron' }
  }
  if (ent.membership_class === 'none' || ent.reason === 'campaign_membership_required') {
    return { state: 'non_member' }
  }
  // 'free', a grant or the free pot, or an older server that sends no class:
  // linked is enough to share.
  return { state: 'free' }
}

/** The plan the DEV tier chip forces (usePremium's override). */
export function overriddenPlan(premium, ent) {
  if (premium) return { state: 'paid', tier: tierFor(1), graceUntil: null }
  return ent?.linked ? { state: 'free' } : { state: 'signed_out' }
}
