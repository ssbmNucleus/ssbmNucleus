import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isPatreonNonMember, patreonMembershipLabel } from './membershipLabel.js'

test('Non-members are not called a free account', () => {
  const ent = { linked: true, active: false, membership_class: 'none', reason: 'campaign_membership_required' }
  assert.equal(patreonMembershipLabel(ent), "Not a member of sc00p's Patreon")
  assert.equal(isPatreonNonMember(ent), true)
  // reason alone (membership_class missing) still reads as a non-member
  assert.equal(patreonMembershipLabel({ linked: true, active: false, reason: 'campaign_membership_required' }), "Not a member of sc00p's Patreon")
})
test('Free members read as free members, with or without AI on', () => {
  assert.equal(patreonMembershipLabel({ linked: true, active: false, membership_class: 'free', reason: 'ai_access_required' }), 'Free member')
  // free-pot access reports tier_multiplier 1; that is not the Nucleon tier
  assert.equal(patreonMembershipLabel({ linked: true, active: true, membership_class: 'free', source: 'free', tier_multiplier: 1 }), 'Free member')
  assert.equal(isPatreonNonMember({ linked: true, active: false, membership_class: 'free' }), false)
})
test('Paid tiers keep their tier name, with the price beside it', () => {
  assert.equal(patreonMembershipLabel({ linked: true, active: true, membership_class: 'paid', source: 'patreon', tier_multiplier: 2.4 }), 'Nucleotide ($10/month)')
  assert.equal(patreonMembershipLabel({ linked: true, active: true, membership_class: 'paid', tier_multiplier: 8 }), 'Nucleolus ($30/month)')
  assert.equal(patreonMembershipLabel({ linked: true, active: true, membership_class: 'paid', tier_multiplier: 5.2 }), 'Nucleosome ($20/month)')
  assert.equal(patreonMembershipLabel({ linked: true, active: true, membership_class: 'paid', tier_multiplier: 1 }), 'Nucleon ($5/month)')
  // the server's own tier name wins over the budget ratio
  assert.equal(patreonMembershipLabel({ linked: true, active: true, membership_class: 'paid', tier_multiplier: 8, tier_name: 'Nucleotide ($10)' }), 'Nucleotide ($10/month)')
  assert.equal(patreonMembershipLabel({ linked: true, active: true }), 'Active pledge')
})
test('Older servers without membership_class keep the old wording', () => {
  assert.equal(patreonMembershipLabel({ linked: true, active: false }), 'Free account')
  assert.equal(isPatreonNonMember({ linked: true, active: false }), false)
})
