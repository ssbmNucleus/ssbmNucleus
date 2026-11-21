import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cloudPlan, cloudPledgeKnown, isCloudPaid } from './cloudPlan.js'

// Shapes as ai-entitlement sends them (meleeWebsite supabase/functions/ai-entitlement).
const paid = { linked: true, active: true, source: 'patreon', membership_class: 'paid', tier_multiplier: 1, patron_status: 'active_patron' }
const freeMember = { linked: true, active: false, membership_class: 'free', reason: 'ai_access_required', patron_status: null }
const freePot = { linked: true, active: true, source: 'free', membership_class: 'free', tier_multiplier: 1 }
const grant = { linked: true, active: true, source: 'grant', membership_class: 'free', tier_multiplier: 2.4 }
const follower = { linked: true, active: false, membership_class: 'none', reason: 'campaign_membership_required', patron_status: null }
const formerPatron = { linked: true, active: false, membership_class: 'none', reason: 'campaign_membership_required', patron_status: 'former_patron' }

test('the five states a person can be in', () => {
  assert.equal(cloudPlan({ linked: false, active: false }).state, 'signed_out')
  assert.equal(cloudPlan(follower).state, 'non_member')
  assert.equal(cloudPlan(freeMember).state, 'free')
  assert.equal(cloudPlan(paid).state, 'paid')
  assert.equal(cloudPlan(formerPatron).state, 'lapsed')
})

test('before and without an answer', () => {
  assert.equal(cloudPlan(undefined).state, 'checking')
  assert.equal(cloudPlan({ checkFailed: true }).state, 'unknown')
})

test('AI access is not the phone: the free pot and grants stay unpaid', () => {
  assert.equal(isCloudPaid(freePot), false)
  assert.equal(cloudPlan(freePot).state, 'free')
  assert.equal(isCloudPaid(grant), false)
})

test('AI paused does not take the phone from a paying patron', () => {
  const paused = { linked: true, active: false, paused: true, reason: 'paused', membership_class: 'paid' }
  assert.equal(isCloudPaid(paused), true)
  assert.equal(isCloudPaid({ ...paused, membership_class: 'free' }), false)
})

test('AI paused says nothing about a pledge it does not name', () => {
  const pausedGrace = { linked: true, active: false, paused: true, membership_class: 'none', patron_status: 'former_patron' }
  assert.equal(cloudPledgeKnown(pausedGrace), false)
  assert.equal(cloudPledgeKnown({ ...pausedGrace, membership_class: 'paid' }), true)
  assert.equal(cloudPledgeKnown({ checkFailed: true }), false)
  assert.equal(cloudPledgeKnown({ linked: false, active: false }), true)
  assert.equal(cloudPledgeKnown(paid), true)
})

test('the server-named tier beats the budget ratio a grant can inflate', () => {
  const withGrant = { ...paid, tier_multiplier: 5.2, tier_name: 'Nucleon ($5)' }
  assert.equal(cloudPlan(withGrant).tier.name, 'Nucleon')
})

test('the tier and its price come with a paid plan', () => {
  assert.deepEqual(cloudPlan({ ...paid, tier_multiplier: 2.4 }).tier, { name: 'Nucleotide', price: 10, multiplier: 2 })
  assert.equal(cloudPlan(paid).tier.price, 5)
})

test('a cancelled patron inside the paid month is paid, with an end date instead of a tier', () => {
  const grace = { ...paid, membership_class: 'none', patron_status: 'former_patron', grace: true, paid_through: '2026-11-03T00:00:00Z', tier_multiplier: 1 }
  const plan = cloudPlan(grace)
  assert.equal(plan.state, 'paid')
  assert.equal(plan.tier, null)
  assert.equal(plan.graceUntil, '2026-11-03T00:00:00Z')
})

test('a phone still paired on an unpaid account means the pledge lapsed', () => {
  assert.equal(cloudPlan(freeMember, { hasPairedPhone: true }).state, 'lapsed')
  assert.equal(cloudPlan(follower, { hasPairedPhone: true }).state, 'lapsed')
  assert.equal(cloudPlan({ ...formerPatron, patron_status: 'declined_patron' }).declined, true)
})

test('older servers: active alone still means paid, linked alone means free', () => {
  assert.equal(cloudPlan({ linked: true, active: true, tier_multiplier: 1 }).state, 'paid')
  assert.equal(cloudPlan({ linked: true, active: false }).state, 'free')
})
