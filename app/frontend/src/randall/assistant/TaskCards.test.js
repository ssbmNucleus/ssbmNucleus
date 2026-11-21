import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as activity from './activity.js'
import * as taskEnvelope from './taskEnvelope.js'

const compiled = transformSync(readFileSync(new URL('./TaskCards.jsx', import.meta.url), 'utf8'),
  { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
const realRequire = createRequire(import.meta.url)
new Function('require', 'module', 'exports', compiled)(
  name => name === './activity' ? activity : name === './taskEnvelope' ? taskEnvelope : realRequire(name),
  module, module.exports)
const { ResultCard, DecisionCard, WishCard, SafetyLabel, FailureNotice } = module.exports
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props))

test('a partial result never reads as a plain success', () => {
  const html = render(ResultCard, {
    title: 'The costume file', outcome: 'partial',
    summary: 'Exported with your override. This file did not pass its checks.',
    checks: [{ check_id: 'game_verification', status: 'unknown', reason: 'no game run' }],
    limitations: ['This file carries an override, not a pass.'],
    achieved: { prepared: false, exported: true, installed: false, previewed: false },
  })
  assert.match(html, /Partly done/)
  assert.doesNotMatch(html, /Done<\/span>/)
  assert.match(html, /is-qualified/)
  // The consequential check is visible immediately, not folded into details.
  assert.match(html, /Checked while the game was running: Could not check/)
  // `exported` is written before anything is promoted anywhere, so it may not
  // claim the file reached the place the user asked for.
  assert.match(html, /A file was written/)
  assert.match(html, /Not in your playable game yet/)
})

test('a required check that could not be measured is never rendered as a pass', () => {
  const html = render(ResultCard, { title: 'x', outcome: 'success',
    checks: [{ check_id: 'posture', status: 'unknown' }] })
  assert.match(html, /is-qualified/)
  assert.match(html, /Could not check/)
})

test('a check the work never runs is listed under what was checked, not as the headline', () => {
  // 2026-10-06: a delivery's card led with "A check on the costume: Could not check — Not run. Rebuilding the
  // game does not move the character; ...", an optional check no delivery performs.
  const html = render(ResultCard, { title: 'Your game', outcome: 'success', summary: 'Saved.',
    checks: [{ check_id: 'costume_in_disc_image', status: 'pass' },
      { check_id: 'automated_movement_checks', status: 'unknown', required: false, reason: 'Not run.' }] })
  assert.doesNotMatch(html, /assistant-task-worst/)
  assert.match(html, /What was checked/)
  assert.match(html, /Tested in a match/)
  assert.doesNotMatch(html, /A check on the costume/)
})

test('the automated game checks become a result instead of "no session"', () => {
  const props = taskEnvelope.verificationResult({ game_verification: {
    character: 'Fox', outcome: 'unknown', costume_slot: 2, frames_captured: 8, frames_requested: 12,
    checks: [{ check_id: 'costume_slot_loaded', status: 'pass', reason: '' }],
    appearance_checks: [{ move: 'AttackAirF', frame: 5, status: 'unknown', reason: 'no capture' }],
    limitations: ['Checked one costume, not the whole build.'], reasons: [], timing: { seconds: 96 },
  } })
  const html = render(ResultCard, props)
  assert.match(html, /could not finish checking Fox/)
  assert.match(html, /Costume checks only, on slot 2/)
  assert.match(html, /does not check your stages or the rest of your build/)
  assert.match(html, /8 of 12 moments captured/)
  assert.doesNotMatch(html, /Done<\/span>/)
})

test('costumes added to a build do not claim the playable game changed', () => {
  const props = taskEnvelope.projectInstallResult({ project_action: 'installed', installed_count: 3,
    project: { name: 'My Melee' } })
  const html = render(ResultCard, props)
  assert.match(html, /Added 3 costumes to My Melee/)
  assert.match(html, /playable game does not change until the build is made/)
  assert.doesNotMatch(html, /installed/i)
  assert.match(html, /Ready to save or install/)
  assert.doesNotMatch(html, /In your playable game, and checked/)
})

test('a decision is a question with bounded answers, not a spinner', () => {
  const html = render(DecisionCard, { request: { id: 'next_1', prompt: 'Which Fox?',
    options: [{ id: 'a', label: 'Recolor the hair and fur together' }, { id: 'b', label: 'Stop' }] } })
  assert.match(html, /Recolor the hair and fur together/)
  assert.doesNotMatch(html, /assistant-work-pulse/)
})

test('a safety label needs an explicit passing verdict with provenance', () => {
  const { safetyKind, safetyProvenance } = module.exports
  // The vault writes slippi_safe=False when NO validator ran (import_unified/
  // characters.py), so a bare false is not a failed check.
  assert.equal(safetyKind({ slippi_safe: false }), 'not_marked_safe')
  assert.match(render(SafetyLabel, { item: { slippi_safe: false } }), /Not marked safe/)
  assert.match(render(SafetyLabel, { item: { slippi_safe: false } }), /the vault does not record which/)
  // Only a recorded check plus a passing verdict reads as a check that passed.
  assert.equal(safetyKind({ slippi_safe: true, slippi_tested: true }), 'costume_check_passed')
  assert.equal(safetyKind({ slippi_tested: true }), 'unchecked')
  assert.equal(safetyKind({ slippi_evidence: 'validator' }), 'unchecked',
    'a validator-labelled item with no verdict is not a pass')
  // A hand-typed label is never a check, either way round.
  assert.equal(safetyKind({ slippi_safe: true, slippi_tested: true, slippi_manual_override: true }), 'manual_safe')
  assert.equal(safetyKind({ slippi_safe: false, slippi_manual_override: true }), 'manual_unsafe')
  assert.equal(safetyKind({}), 'unchecked')
  // A real failing verdict still reads as a failure.
  assert.equal(safetyKind({ slippi_safe: false, slippi_verdict: 'costume_check_failed' }), 'costume_check_failed')
  // Provenance: the bytes and the date, never invented.
  assert.equal(safetyProvenance({}), '')
  assert.match(safetyProvenance({ slippi_test_date: '2026-09-01T10:00:00', dat_hash: 'abcdef1234567890' }),
    /2026-09-01 · on file abcdef12/)
  // Scope is part of every one of them.
  for (const item of [{ slippi_safe: true, slippi_tested: true }, {}, { slippi_safe: false }]) {
    assert.match(render(SafetyLabel, { item }), /stages|build/)
  }
})

test('a wish separates the missing capability from a failure', () => {
  const html = render(WishCard, { wish: { capability: 'Nucleus cannot preview a finished menu yet.',
    blocked_operation: 'showing you the menu', available_alternative: 'Your menu files are prepared.',
    record_status: 'queued' } })
  assert.match(html, /Saved on this computer/)
  assert.match(html, /Your menu files are prepared/)
})

test('the failure notice keeps all three parts', () => {
  const html = render(FailureNotice, { tool: { name: 'deliver_to_game', status: 'cancelled' } })
  assert.match(html, /You stopped putting it into the game you play/)
  assert.match(html, /Everything finished before this is kept/)
  assert.match(html, /picks up from here/)
})
