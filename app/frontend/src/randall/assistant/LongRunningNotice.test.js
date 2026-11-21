import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as transcript from './transcript.js'
import * as activity from './activity.js'
import * as taskEnvelope from './taskEnvelope.js'
import * as clock from './clock.js'
import { importTimeText } from './studio.js'
import { tungRunning } from './__fixtures__/tungImportFixture.js'

const load = (file, resolve) => {
  const compiled = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const module = { exports: {} }
  const realRequire = createRequire(import.meta.url)
  new Function('require', 'module', 'exports', compiled)(
    name => resolve(name) || realRequire(name), module, module.exports)
  return module.exports
}

// Developer details (the settings switch): off unless a test turns it on.
let devDetails = false
const cards = load('./TaskCards.jsx', name => name === './activity' ? activity
  : name === './taskEnvelope' ? taskEnvelope : name === './devDetails' ? { useDevDetails: () => devDetails } : null)
const notice = load('./LongRunningNotice.jsx', name => name === './transcript' ? transcript
  : name === './taskEnvelope' ? taskEnvelope : name === './activity' ? activity
    : name === './TaskCards' ? cards : name === './clock' ? clock : null)
const render = (message, props = {}) =>
  renderToStaticMarkup(React.createElement(notice.default, { message, onStop: () => {}, ...props }))

const running = extra => ({ id: 'reply', role: 'assistant', status: 'running', model_rounds: 25,
  started_at: Date.now() / 1000 - 140, ...extra })

test('a long task says the stage, the time it has taken and the limit it stops at', () => {
  const html = render(running({ tools: [{ id: 't1', name: 'model_fit', status: 'running' }] }))
  assert.match(html, /role="status" aria-live="polite"/)
  assert.match(html, /Fitting the model to a fighter/)
  assert.match(html, /2 min \d+ sec so far/)
  // No boundary at all was the old failure; a known limit is stated exactly.
  assert.match(html, /stops on his own/)
  assert.match(html, /<button[^>]*>Stop<\/button>/)
  // ...and the sentence that gave no stage, no number and no bound is gone.
  assert.doesNotMatch(html, /keep working and using AI credit/)
})

test('it renders the task envelope when a tool carries one, and degrades when none does', () => {
  const withEnvelope = render(running({
    tools: [{ id: 't1', name: 'model_fit', status: 'running',
      result: { task: { task_id: 'task_1', revision: 1, state: 'waiting_decision',
        achieved: { prepared: false, exported: false, installed: false, previewed: false },
        facts: { stage_label: 'Checking movement', waiting_reason: 'Waiting for your answer' },
        next: { id: 'next_1', kind: 'decision', task_revision: 1, allowed_responses: ['a', 'b'] } } } }],
  }))
  assert.match(withEnvelope, /Checking movement/)
  assert.match(withEnvelope, /Waiting for your answer/)
  // A waiting task must not also be showing a working animation.
  assert.doesNotMatch(withEnvelope, /assistant-work-pulse/)
  assert.doesNotMatch(render(running({ tools: [] })), /undefined|\[object/)
})

test('users never see the cost; with developer details it is reported as measured', () => {
  const html = render(running({ cost_usd: 0.0234, committed_usd: 0.05 }))
  assert.doesNotMatch(html, /\$|cost|charge|credit|spending/i)
  assert.match(html, /stops on his own if this runs too long or reaches its usage\s+limit/)
  devDetails = true
  try {
    assert.match(render(running({ cost_usd: 0.0234 })), /AI cost so far: \$0\.02/)
    assert.match(render(running({ cost_usd: 0.02, committed_usd: 0.05 })), /final charge pending/)
    // Nothing is shown when nothing was reported -- never $0.00.
    assert.doesNotMatch(render(running({})), /AI cost so far/)
  } finally { devDetails = false }
})

test('an estimate appears only when the backend supplies one', () => {
  assert.doesNotMatch(render(running({})), /expected/)
  assert.match(render(running({ estimate_seconds: 180 })), /about 3 min expected/)
})

test('short, finished and approval-blocked replies do not show a long-task notice', () => {
  const message = { id: 'reply', role: 'assistant', status: 'running', model_rounds: 1, started_at: Date.now() / 1000 }
  assert.equal(render(message), '')
  assert.equal(render({ ...message, status: 'done', model_rounds: 25 }), '')
  assert.equal(render({ ...message, model_rounds: 25, tools: [{ approval: { status: 'pending' } }] }), '')
})

test('the status bar and the import card read one clock in one format', () => {
  // The Tung Tung Tung Sahur import, 175 s into the turn (the card used to say "2.5 min" here, from a progress event).
  const now = Date.now()
  const { tool, reply, turnStart } = tungRunning({ now })
  const bar = render({ ...reply, model_rounds: 2, tools: [{ ...tool, result: { ...tool.result,
    progress_label: 'Importing your model' } }] })
  assert.match(bar, /Importing your model/)
  assert.match(bar, /2 min 55 sec so far/)
  assert.equal(importTimeText(tool, { startedAt: turnStart, now }), '2 min 55 sec', 'the card says the same')
})
