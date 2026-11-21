// Randall settings' usage row (UsageRow.jsx), server-rendered: the chat sidebar's bar and the reset date, and
// never a dollar amount, "credit" or the provider's name.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as access from './access.js'
import * as chatList from '../chat/chatList.js'

const realRequire = createRequire(import.meta.url)
const load = (file, modules) => {
  const code = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'), { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => modules[name]
    ?? (name.endsWith('.css') ? {} : realRequire(name)), module, module.exports)
  return module.exports
}
const chatUI = load('../chat/ChatUI.jsx', { './chatList': chatList, '../assistant/access': access,
  '../../shared/ui/Sprites': { Randall: () => null }, '../../shared/audio/sounds': { playSound() {}, playHoverSound() {} } })
const UsageRow = load('./UsageRow.jsx', { '../chat/ChatUI': chatUI, './access': access }).default
const render = entitlement => renderToStaticMarkup(React.createElement(UsageRow, { entitlement }))

const MONTH = { active: true, api_key: 'sk-or-v1-x', period_budget: 10, remaining: 7.5, usage: 2.5,
  resets_at: '2026-11-01T00:00:00Z' }
const RESETS = access.budgetResetLabel(MONTH)
// The fixtures' amounts, spelled out: a reset date can contain "1.11" in some locales.
const MONEY = /\$|7\.5|2\.5|credit|OpenRouter|key/i

test('the row is the chat bar, "Monthly usage", and when it resets', () => {
  const html = render(MONTH)
  assert.ok(html.startsWith('<div class="assistant-settings-row"><span class="assistant-sidebar-label">Usage</span>'))
  assert.match(html, /<div class="coach-usage assistant-settings-usage" title="Randall usage this month - resets [^"]+"><div class="coach-usage-bar" role="meter" aria-label="Monthly AI usage"[^>]*aria-valuenow="25"><div class="coach-usage-fill" style="width:25%"><\/div><\/div><span class="coach-usage-text">Monthly usage<\/span><\/div>/)
  assert.ok(html.includes(`<p class="assistant-settings-reset">Resets ${RESETS}.</p>`))
  assert.doesNotMatch(html, MONEY)
})

test('at the limit the bar says so and when it resets, once', () => {
  const html = render({ ...MONTH, remaining: 0, usage: 10 })
  assert.match(html, /aria-valuenow="100"/)
  assert.ok(html.includes(`<span class="coach-usage-text">Monthly limit reached - resets ${RESETS}</span>`))
  assert.equal(html.split(RESETS).length - 1, 2, 'the bar\'s words and its tooltip; no second "Resets" line')
  assert.doesNotMatch(html, MONEY)
})

test('a free-only person\'s row is their free usage and its 3-day refill, not the 1st', () => {
  const free = { ...MONTH, period_budget: 0.05, remaining: 0.02, usage: 0.03, monthly_budget: 0,
    free_refills_at: new Date(Date.now() + 48 * 3_600_000).toISOString() }
  let html = render(free)
  assert.match(html, /title="Free Randall usage - refills in 2 days"><div class="coach-usage-bar" role="meter" aria-label="Free AI usage"[^>]*aria-valuenow="60"/)
  assert.ok(html.includes('<span class="coach-usage-text">Free usage</span>'))
  assert.ok(html.includes('<p class="assistant-settings-reset">Free usage refills in 2 days.</p>'))
  html = render({ ...free, remaining: 0 })
  assert.ok(html.includes('<span class="coach-usage-text">Free usage used up - refills in 2 days</span>'))
  assert.doesNotMatch(html, new RegExp(`Monthly|${RESETS}`))
  assert.doesNotMatch(html, /\$|0\.0\d|credit|OpenRouter|key/i)
})

test('with no budget reported the row says so without a bar or an amount', () => {
  for (const entitlement of [null, { linked: false, active: false }, { active: true, usage: 2.5 }, { active: true, remaining: 7.5 },
    { checkFailed: true }]) {
    const html = render(entitlement)
    assert.doesNotMatch(html, /coach-usage/)
    assert.match(html, /<strong>Not reported<\/strong>/)
    assert.doesNotMatch(html, MONEY)
  }
})
