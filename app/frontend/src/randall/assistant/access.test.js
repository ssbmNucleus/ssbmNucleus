import { test } from 'node:test'
import assert from 'node:assert/strict'
import { assistantAccess, budgetResetLabel, LOW_USAGE_UNDER, lowUsageWarning, monthlyUsage, refillLabel } from './access.js'

// The reset date as this machine's locale writes it ("Nov 1" in en-US).
const NOV_1 = budgetResetLabel({ resets_at: '2026-11-01T00:00:00Z' })
// A fixed "now", and the next free refill two days after it.
const NOW = Date.parse('2026-10-09T12:00:00Z')
const HOUR = 3_600_000
const IN_2_DAYS = new Date(NOW + 48 * HOUR).toISOString()
// What a user may never see: an amount, "credit" or the provider.
const MONEY = /\$|\d\.\d|credit|OpenRouter|cents?\b|USD/i

test('Provisioned Patreon key works without a personal key', () => {
  const access = assistantAccess({ ready: false }, { active: true, api_key: 'request-only', remaining: 1.25 })
  assert.equal(access.ready, true)
  assert.equal(access.key, 'request-only')
  assert.equal(access.source, 'patreon')
  assert.equal(access.label, 'Connected through Patreon')
})
test('access sentences never show money, credit or the provider', () => {
  const words = /\$|1\.25|credit|OpenRouter|budget/i
  const states = [{ active: true, api_key: 'k', remaining: 1.25, period_budget: 5 }, { active: true, remaining: 3 },
    { active: true, api_key: 'k', remaining: 0, resets_at: '2026-11-01T00:00:00Z' }]
  for (const entitlement of states) assert.doesNotMatch(assistantAccess({}, entitlement).label, words)
  const usedUp = assistantAccess({}, states[2])
  assert.equal(usedUp.usedUp, true)
  assert.equal(usedUp.label, `You've reached this month's Randall limit. It resets ${NOV_1}. Setup and browsing still work.`)
})
test('Patreon key takes priority and exhausted budget does not silently bill a personal key', () => {
  assert.equal(assistantAccess({ ready: true }, { active: true, api_key: 'patron' }).key, 'patron')
  assert.equal(assistantAccess({ ready: true }, { active: true, api_key: 'patron', remaining: 0 }).ready, false)
})
test('Revoked access and missing keys cannot unlock the assistant', () => {
  for (const entitlement of [{ active: false, api_key: 'stale' }, { active: true }, { checkFailed: true }, null]) {
    assert.equal(assistantAccess({ ready: false }, entitlement).ready, false)
  }
})
test('Local key readiness cannot unlock Randall without Patreon', () => {
  const access = assistantAccess({ ready: true }, { linked: false, active: false })
  assert.equal(access.ready, false)
  assert.equal(access.source, 'none')
  assert.equal(access.key, undefined)
})

test('monthly usage is a share and a reset date, from period_budget and remaining', () => {
  const at = { active: true, period_budget: 10, remaining: 7.5, usage: 2.5, resets_at: '2026-11-01T00:00:00Z' }
  assert.deepEqual(monthlyUsage(at), { used: 0.25, limitReached: false, free: false, resets: NOV_1, text: 'Monthly usage' })
  assert.deepEqual(monthlyUsage({ ...at, remaining: 0 }),
    { used: 1, limitReached: true, free: false, resets: NOV_1, text: `Monthly limit reached - resets ${NOV_1}` })
  // Spent past the budget: a full bar, never more. Nothing left is the limit even without a named budget.
  assert.equal(monthlyUsage({ ...at, remaining: -0.4 }).used, 1)
  assert.equal(monthlyUsage({ active: true, remaining: 0 }).limitReached, true)
  // Almost used up is not the limit: Randall still answers (assistantAccess), so the bar must not say otherwise.
  const almost = monthlyUsage({ ...at, remaining: 0.01 })
  assert.equal(almost.limitReached, false)
  assert.equal(almost.text, 'Monthly usage')
  assert.equal(assistantAccess({}, { ...at, api_key: 'k', remaining: 0.01 }).ready, true)
  assert.equal(monthlyUsage({ active: true, remaining: 3, period_budget: 5 }).resets, 'on the 1st')
  // Nothing to measure, or something left with no budget to measure it against: no bar, not a guessed 0%.
  for (const entitlement of [null, { active: false, remaining: 3 }, { active: true }, { active: true, remaining: 'n/a' },
    { active: true, remaining: 3 }]) {
    assert.equal(monthlyUsage(entitlement), null)
  }
})

test('a free-only person sees the free refill; anyone with a monthly budget, or an older server, the monthly reset', () => {
  const month = { active: true, api_key: 'k', resets_at: '2026-11-01T00:00:00Z', free_refills_at: IN_2_DAYS }
  assert.deepEqual(refillLabel({ ...month, monthly_budget: 0 }, NOW), { free: true, when: 'in 2 days' })
  assert.deepEqual(refillLabel({ ...month, monthly_budget: 5 }, NOW), { free: false, when: NOV_1 })
  // The new fields missing or unreadable: today's behaviour.
  assert.deepEqual(refillLabel(month, NOW), { free: false, when: NOV_1 })
  assert.deepEqual(refillLabel({ ...month, monthly_budget: null }, NOW), { free: false, when: NOV_1 })
  assert.deepEqual(refillLabel({ ...month, monthly_budget: 0, free_refills_at: 'soonish' }, NOW), { free: false, when: NOV_1 })
  assert.deepEqual(refillLabel({ active: true, monthly_budget: 0 }, NOW), { free: false, when: 'on the 1st' })
  // How far off, in words.
  const when = hours => refillLabel({ monthly_budget: 0, free_refills_at: new Date(NOW + hours * HOUR).toISOString() }, NOW).when
  assert.equal(when(71), 'in 3 days')
  assert.equal(when(30), 'in 1 day')
  assert.equal(when(5), 'in 5 hours')
  assert.equal(when(0.2), 'in 1 hour')
  assert.equal(when(-1), 'soon')

  // Used up: the bar and the locked composer name the same refill.
  const free = { ...month, monthly_budget: 0, period_budget: 0.05, remaining: 0 }
  assert.deepEqual(monthlyUsage(free, NOW), { used: 1, limitReached: true, free: true, resets: 'in 2 days',
    text: 'Free usage used up - refills in 2 days' })
  assert.equal(monthlyUsage({ ...free, remaining: 0.02 }, NOW).text, 'Free usage')
  assert.equal(assistantAccess({}, free, NOW).label,
    "You've used up your free Randall usage. It refills in 2 days. Setup and browsing still work.")
  assert.equal(assistantAccess({}, { ...free, monthly_budget: 5 }, NOW).label,
    `You've reached this month's Randall limit. It resets ${NOV_1}. Setup and browsing still work.`)
  assert.equal(monthlyUsage({ ...free, monthly_budget: 5 }, NOW).text, `Monthly limit reached - resets ${NOV_1}`)
  assert.doesNotMatch(assistantAccess({}, free, NOW).label, MONEY)
})

test('the low-usage warning: by job, under its threshold, above zero, with when it refills', () => {
  const patron = { active: true, api_key: 'k', monthly_budget: 5, resets_at: '2026-11-01T00:00:00Z', free_refills_at: IN_2_DAYS }
  const warn = (remaining, chat, entitlement = patron) => lowUsageWarning({ ...entitlement, remaining }, chat, NOW)
  const TEXT = "You're low on Randall usage, so this may stop partway."
  assert.deepEqual(warn(0.03, { task: 'recolor_part' }), { job: 'retexture', text: TEXT, refill: `Refills on ${NOV_1}.` })
  assert.deepEqual(warn(0.03, { task: 'recolor_part' }, { ...patron, monthly_budget: 0 }),
    { job: 'retexture', text: TEXT, refill: 'Free usage refills in 2 days.' })

  // The job, from the chat's task, the empty chat's picker or its pick, or an import already under way.
  const job = chat => warn(0.001, chat)?.job
  assert.equal(job({ task: 'recolor_part' }), 'retexture')
  assert.equal(job({ task: 'recolor_stage' }), 'retexture')
  assert.equal(job({ task: 'model_import' }), 'import')
  assert.equal(job({ picker: 'costume' }), 'retexture')
  assert.equal(job({ picker: 'stage' }), 'retexture')
  assert.equal(job({ picker: 'fighter', pick: { kind: 'fighter', character: 'Fox' } }), 'import')
  assert.equal(job({ pick: { kind: 'stock', character: 'Fox' } }), 'retexture')
  assert.equal(job({ importing: true }), 'import')
  assert.equal(job({}), 'chat')
  assert.equal(job(undefined), 'chat')
  assert.equal(job({ task: 'find_mod' }), 'chat', 'a retired task id is a plain chat')
  assert.equal(job({ task: 'constructor' }), 'chat')

  // Each job's threshold: strictly under it warns, at it does not.
  for (const [chat, under] of [[{ task: 'recolor_stage' }, 0.04], [{ task: 'model_import' }, 0.01], [{}, 0.005]]) {
    assert.equal(LOW_USAGE_UNDER[job(chat)], under)
    assert.ok(warn(under - 0.0001, chat), `${under}: just under warns`)
    assert.equal(warn(under, chat), null, `${under}: at the threshold is fine`)
  }
  assert.equal(warn(0.02, { task: 'model_import' }), null, 'enough for an import is not low for it')
  assert.ok(warn(0.02, { task: 'recolor_part' }), 'but is low for a retexture')

  // Nothing at zero (the composer is locked and says when it resets), nor without a reported amount.
  for (const remaining of [0, -0.2, null, undefined, '', 'n/a']) assert.equal(warn(remaining, { task: 'recolor_part' }), null)
  assert.equal(lowUsageWarning({ active: false, remaining: 0.001 }, {}, NOW), null)
  assert.equal(lowUsageWarning(null, {}, NOW), null)

  // Older servers: the monthly reset, or the 1st.
  assert.equal(warn(0.001, {}, { active: true }).refill, 'Refills on the 1st.')
  assert.equal(warn(0.001, {}, { active: true, resets_at: '2026-11-01T00:00:00Z', free_refills_at: IN_2_DAYS }).refill,
    `Refills on ${NOV_1}.`)
  for (const shown of [warn(0.001, {}), warn(0.001, {}, { ...patron, monthly_budget: 0 })]) {
    assert.doesNotMatch(shown.text, MONEY)
    assert.doesNotMatch(shown.refill.replace(NOV_1, ''), MONEY)
  }
})

test('A linked non-member is told to join free and check again, not to re-link', () => {
  const access = assistantAccess({ ready: true }, { linked: true, active: false, membership_class: 'none', reason: 'campaign_membership_required' })
  assert.equal(access.ready, false)
  assert.equal(access.joinFree, true)
  assert.match(access.label, /for free/)
  assert.match(access.label, /Check again/)
  assert.doesNotMatch(access.label, /refresh your Patreon link/)
  assert.equal(assistantAccess({ ready: true }, { linked: true, active: false, membership_class: 'free', reason: 'ai_access_required' }).joinFree, undefined)
})
