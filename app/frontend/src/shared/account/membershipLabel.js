// The one-line Patreon status under the name in Settings > Files & setup > Account.
// ai-entitlement reports membership_class ('paid' | 'free' | 'none') and, when
// AI is off, a reason; older servers send neither, so fall back to the old
// "Free account" wording rather than guess.

// The paid tiers, cheapest first. Prices are the Patreon pledge (USD/month);
// `multiplier` is where ai-entitlement's tier_multiplier lands for each one
// (monthly budget / the cheapest tier's: 2.50, 6, 13, 20 -> 1, 2.4, 5.2, 8).
// Every paid tier unlocks the same cloud features; the price is shown so a
// tier name is never a mystery.
export const TIERS = [
  { name: 'Nucleon', price: 5, multiplier: 1 },
  { name: 'Nucleotide', price: 10, multiplier: 2 },
  { name: 'Nucleosome', price: 20, multiplier: 5 },
  { name: 'Nucleolus', price: 30, multiplier: 8 },
]

/** The tier a tier_multiplier belongs to (the highest one it reaches). */
export const tierFor = m => [...TIERS].reverse().find(t => (m || 0) >= t.multiplier) || TIERS[0]

/** The tier an ai_tiers name belongs to ("Nucleotide ($10)"), or null. */
export const tierByName = name => (name && TIERS.find(t => String(name).startsWith(t.name))) || null

/** "Nucleotide ($10/month)" */
export const tierWithPrice = m => `${tierFor(m).name} ($${tierFor(m).price}/month)`

export function patreonMembershipLabel(ent) {
  const cls = ent?.membership_class
  if (ent?.active) {
    // Free-pot access reports tier_multiplier 1, which is not a tier.
    if (ent.source === 'free' || (!ent.source && cls === 'free')) return 'Free member'
    const named = tierByName(ent.tier_name)
    if (named) return `${named.name} ($${named.price}/month)`
    return ent.tier_multiplier ? `${tierWithPrice(ent.tier_multiplier)}` : 'Active pledge'
  }
  if (cls === 'free') return 'Free member'
  if (cls === 'paid') return 'Paid member'
  if (cls === 'none' || ent?.reason === 'campaign_membership_required') return "Not a member of sc00p's Patreon"
  return 'Free account'
}

/** Linked, but Patreon does not list this account in sc00p's campaign. */
export function isPatreonNonMember(ent) {
  return Boolean(ent?.linked && !ent?.active
    && (ent?.reason === 'campaign_membership_required' || ent?.membership_class === 'none'))
}
