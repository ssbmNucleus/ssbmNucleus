// The chat sidebar in the Claude layout (ChatSidebar, ChatAccount in ChatUI.jsx),
// server-rendered: one-line rows under date headings, the status dot, the task
// in the tooltip, "Show N more", the starting-point rows and the account footer.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as chatList from './chatList.js'
import * as access from '../assistant/access.js'

const realRequire = createRequire(import.meta.url)
const noop = () => {}
const code = transformSync(readFileSync(new URL('./ChatUI.jsx', import.meta.url), 'utf8'), { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
new Function('require', 'module', 'exports', code)(name => ({
  './chatList': chatList,
  '../assistant/access': access,
  '../../shared/ui/Sprites': { Randall: () => null },
  '../../shared/audio/sounds': { playSound: noop, playHoverSound: noop },
})[name] ?? (name.endsWith('.css') ? {} : realRequire(name)), module, module.exports)
const { ChatSidebar, ChatAccount, planLabel } = module.exports

const now = Date.now() / 1000
const DAY = 86400
const CHATS = [
  { id: 'a', title: 'Lava Bowser', updated: now - 60, task: 'recolor_part' },
  { id: 'b', title: 'Old find', updated: now - 120, task: 'find_mod' },
  { id: 'c', title: 'Goku import', updated: now - 40 * DAY, task: 'model_import' },
]
const LABELS = { recolor_part: 'Retexture a costume', model_import: 'Import a model' }
const render = props => renderToStaticMarkup(React.createElement(ChatSidebar, {
  id: 'hist', sidebarOpen: true, onToggleSidebar: noop, chats: CHATS, onSelect: noop, onNew: noop, onDelete: noop,
  badgeFor: chat => LABELS[chat.task] || null, ...props }))

test('top row, search, "+ New" and the starting-point rows, in that order', () => {
  const html = render({ nav: [
    { id: 'recolor_part', label: 'Retexture a costume', title: 'Pick a costume', icon: React.createElement('svg', { 'data-icon': 'brush' }), onSelect: noop },
    { id: 'model_import', label: 'Import a model', icon: null, onSelect: noop },
  ] })
  const order = ['chat-sidebar-top', 'aria-label="Collapse sidebar"', 'chat-sidebar-search', 'placeholder="Search"',
    'chat-nav-row chat-nav-row--primary', '<span>New</span>', 'data-icon="brush"', '<span>Retexture a costume</span>',
    '<span>Import a model</span>', 'chat-sidebar-list']
  let from = 0
  for (const piece of order) {
    const at = html.indexOf(piece, from)
    assert.ok(at >= 0, `${piece} after position ${from}`)
    from = at
  }
  assert.match(html, /title="Pick a costume"/)
})

test('chats are one-line rows under date headings, the task only in the tooltip', () => {
  const html = render({ activeId: 'a' })
  assert.deepEqual([...html.matchAll(/<h3 class="chat-group-label">([^<]*)<\/h3>/g)].map(m => m[1]), ['Today', 'Older'])
  assert.match(html, /<div class="chat-row is-active"><button type="button" class="chat-row-open" aria-current="page" title="Retexture a costume · Lava Bowser"><span class="chat-row-dot" aria-hidden="true"><\/span><span class="chat-row-title">Lava Bowser<\/span><span class="sr-only">, Retexture a costume<\/span><\/button>/)
  // A chat stored under a retired task reads as a plain chat: no badge anywhere.
  assert.match(html, /<button type="button" class="chat-row-open" title="Old find"><span class="chat-row-dot" aria-hidden="true"><\/span><span class="chat-row-title">Old find<\/span><\/button>/)
  assert.doesNotMatch(html, /Find a mod|randall-task-badge/)
  assert.match(html, /aria-label="Delete Goku import"/)
  assert.doesNotMatch(html, /chat-show-more/)
})

test('the dot shows a running reply and a failed one', () => {
  const html = render({ activeId: 'a', statusFor: chat => ({ a: 'running', c: 'error' })[chat.id] || null })
  assert.match(html, /<span class="chat-row-dot is-running" aria-hidden="true"><\/span><span class="chat-row-title">Lava Bowser<\/span><span class="sr-only">, Retexture a costume, Working<\/span>/)
  assert.match(html, /<span class="chat-row-dot is-error" aria-hidden="true"><svg[^>]*>.*?<\/svg><\/span><span class="chat-row-title">Goku import<\/span><span class="sr-only">, Import a model, Last reply failed<\/span>/)
})

test('"Show N more" pages the list, and the open chat is never paged away', () => {
  const many = Array.from({ length: 7 }, (_, index) => ({ id: `c${index}`, title: `Chat ${index}`, updated: now - index }))
  let html = render({ chats: many, pageSize: 3 })
  assert.equal(html.match(/class="chat-row-title"/g).length, 3)
  assert.match(html, /<button type="button" class="chat-show-more">Show 3 more<\/button>/)
  html = render({ chats: many, pageSize: 3, activeId: 'c5' })
  assert.equal(html.match(/class="chat-row-title"/g).length, 6)
  assert.match(html, />Show 1 more</)
})

test('the footer: avatar, name · plan, and the settings button at the right', () => {
  const html = renderToStaticMarkup(React.createElement(ChatAccount, { entitlement: { active: true, patreon_name: 'alex' }, onSettings: noop }))
  assert.match(html, /<span class="coach-sidebar-avatar" aria-hidden="true">A<\/span><span class="coach-sidebar-user"><span class="coach-sidebar-name">alex<\/span><span class="coach-sidebar-plan"> · Patreon<\/span><\/span><button type="button" class="coach-brain" aria-label="Randall settings"/)
  assert.equal(planLabel({ active: true }), 'Patreon')
  assert.equal(planLabel({ paused: true }), 'Paused')
  assert.equal(planLabel({ linked: true }), 'No AI access')
  assert.equal(planLabel({ linked: false }), 'Not linked')
  assert.equal(planLabel(null), null)
  assert.equal(planLabel({ checkFailed: true }), null)
})

test('the footer bar shows this month\'s share used and the reset, never an amount', () => {
  const footer = entitlement => renderToStaticMarkup(React.createElement(ChatAccount, { entitlement, onSettings: noop }))
  const month = { active: true, patreon_name: 'alex', period_budget: 10, remaining: 7.5, usage: 2.5,
    resets_at: '2026-11-01T00:00:00Z' }
  const resets = access.budgetResetLabel(month)
  let html = footer(month)
  assert.match(html, /<div class="coach-usage" title="Randall usage this month - resets [^"]+"><div class="coach-usage-bar" role="meter" aria-label="Monthly AI usage" aria-valuemin="0" aria-valuemax="100" aria-valuenow="25"><div class="coach-usage-fill" style="width:25%"><\/div><\/div><span class="coach-usage-text">Monthly usage<\/span><\/div>/)
  assert.doesNotMatch(html, /\$|7\.5|2\.5|credit|OpenRouter/i)
  html = footer({ ...month, remaining: 0 })
  assert.match(html, /aria-valuenow="100"/)
  assert.ok(html.includes(`Monthly limit reached - resets ${resets}`))
  // No budget reported: no bar. The Tracker coach without one shows its session's share instead.
  assert.doesNotMatch(footer({ active: true, patreon_name: 'alex' }), /coach-usage/)
  html = renderToStaticMarkup(React.createElement(ChatAccount, { entitlement: { active: false }, usage: { spent: 0.5, cap: 2 }, onSettings: noop }))
  assert.match(html, /aria-label="Session AI usage"[^>]*aria-valuenow="25"/)
  assert.match(html, /Session usage/)
})
