// The findings ASTRA-REVIEW-BB reproduced with in-memory probes, each pinned.
//
//   * the delivery envelope was not recognised at all, so a partial delivery
//     rendered as "Put into the game you play · Done";
//   * a structured error object threw inside settledLines;
//   * a failed project import counted as a success;
//   * a success carrying a blocking check still drew green.
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
const { ResultCard } = module.exports
const render = props => renderToStaticMarkup(React.createElement(ResultCard, props))

// deliver_to_game returns TaskResult.to_dict() as the tool result itself.
const partialDelivery = {
  task_id: 'task_1', revision: 1, workflow: 'deliver_to_game', workflow_version: 1,
  state: 'completed', outcome: 'partial', contracts_version: 1,
  achieved: { prepared: true, exported: true, installed: false, previewed: false },
  facts: { requested_outcome: 'install', change: 'add a costume slot',
    summary: 'Blue Fox is in the My Melee project, but your game copy was not rebuilt.',
    what_changed: 'Blue Fox was added at slot 5.', where: 'the My Melee project files',
    limitation_that_matters: 'Your playable copy was not rebuilt.',
    how_to_undo: 'Ask me to undo this (receipt r1) and I will take the slot back out.' },
  checks: [{ check_id: 'costume_in_iso', status: 'unknown', required: true,
    implementation_version: 'deliver-1', reason: 'the rebuilt image was not read back' }],
  limitations: ['The costume is in the project, but your playable copy was not rebuilt.'],
  artifacts: [], receipts: ['r1'], next: null, error: null, wish_ids: [],
}

test('a delivery envelope arriving as the tool result is recognised', () => {
  const envelope = taskEnvelope.envelopeOf({ name: 'deliver_to_game', status: 'done', result: partialDelivery })
  assert.ok(envelope, 'the envelope IS the result; a nested-only reader misses every real delivery')
  assert.equal(envelope.outcome, 'partial')
  assert.equal(envelope.achieved.installed, false)
  assert.equal(envelope.blocking.length, 1)
  // ...and the engine's sibling task card is read too.
  assert.ok(taskEnvelope.envelopeOf({ name: 'x', status: 'done', result: {}, task: partialDelivery }))
  // A plain tool result is not an envelope.
  assert.equal(taskEnvelope.envelopeOf({ name: 'search_vault', status: 'done', result: { total: 3 } }), null)
})

test('a partial delivery never renders as "Done"', () => {
  const html = render(taskEnvelope.deliveryResult(taskEnvelope.envelopeOf(
    { name: 'deliver_to_game', status: 'done', result: partialDelivery })))
  assert.match(html, /Partly done/)
  assert.doesNotMatch(html, />Done</)
  // The producer already wrote these sentences; the card relays them rather
  // than composing a second account of the same event.
  assert.match(html, /Blue Fox is in the My Melee project, but your game copy was not rebuilt/)
  assert.match(html, /Blue Fox was added at slot 5/)
  assert.match(html, /Where: the My Melee project files/)
  assert.match(html, /Your playable copy was not rebuilt/)
  assert.match(html, /Not in your playable game yet/)
  // `exported` is set before anything is promoted, so it may not say "saved
  // where you asked".
  assert.match(html, /A file was written/)
  assert.doesNotMatch(html, /Saved where you asked/)
})

test('a finished delivery says where it went, and only when it was verified', () => {
  const done = { ...partialDelivery, outcome: 'success',
    achieved: { prepared: true, exported: true, installed: true, previewed: false },
    checks: [{ check_id: 'costume_in_iso', status: 'pass', required: true, implementation_version: 'deliver-1' }],
    facts: { ...partialDelivery.facts,
      summary: 'Blue Fox is in your Slippi setup. Your updated game is saved at My Melee.iso.',
      where: 'your Slippi setup', limitation_that_matters: '' },
    limitations: [] }
  const props = taskEnvelope.deliveryResult(taskEnvelope.envelopeOf(
    { name: 'deliver_to_game', status: 'done', result: done }))
  const html = render(props)
  assert.match(html, /Blue Fox is in your Slippi setup/)
  assert.match(html, /In your playable game, and checked/)
  assert.match(html, /Done/)
  // An undo control only where the producer says one exists, and it names the
  // receipt it would reverse.
  assert.equal(props.undoable, true)
  assert.equal(props.receiptId, 'r1')
  const nothing = taskEnvelope.deliveryResult(taskEnvelope.envelopeOf({ name: 'deliver_to_game', status: 'done',
    result: { ...done, facts: { ...done.facts, how_to_undo: 'There is nothing to undo.' } } }))
  assert.equal(nothing.undoable, false)
})

test('a decision from the delivery workflow becomes readable choices', () => {
  const options = taskEnvelope.decisionOptions({ allowed_responses: [
    { action: 'install_project_mods' },
    { action: 'open_build_screen', where: 'Nucleus \u2192 Export \u2192 Build ISO' }] })
  assert.deepEqual(options.map(option => option.id), ['install_project_mods', 'open_build_screen'])
  assert.equal(options[0].label, 'Add it to a build instead')
  assert.equal(options[1].description, 'Nucleus \u2192 Export \u2192 Build ISO')
  // An action nobody has named yet still reads as words, never as `some_action`.
  assert.equal(taskEnvelope.decisionOptions({ allowed_responses: [{ action: 'some_new_action' }] })[0].label,
    'some new action')
  assert.equal(options[0].say, 'Yes: install project mods.')
})

test('a delivery with no game copy offers its finishing calls by their own words', () => {
  // deliver_replies._delivered, not playable: two answers share deliver_to_game.
  const options = taskEnvelope.decisionOptions({ allowed_responses: [
    { action: 'deliver_to_game', set_as_my_game: 'slippi', project_id: 'p1', label: 'Make it my Slippi game' },
    { action: 'deliver_to_game', set_as_my_game: 'offline', project_id: 'p1', label: 'Make it my offline game' },
    { action: 'test_in_game', kind: 'costume', character: 'Young Link', skin_id: 's1',
      label: 'Just let me play it now' }] })
  assert.equal(new Set(options.map(option => option.id)).size, 3, 'ids stay unique')
  assert.deepEqual(options.map(option => option.label),
    ['Make it my Slippi game', 'Make it my offline game', 'Just let me play it now'])
  assert.deepEqual(options.map(option => option.say),
    ['Make it my Slippi game.', 'Make it my offline game.', 'Just let me play it now.'])
})

test('a structured error renders instead of throwing', () => {
  const error = { code: 'build_failed', message: 'MexCLI could not rebuild the disc image.',
    retryable: true, recovery: 'Open the build screen and try the build there.' }
  // The reproduced exception: settledLines called .trim() on the object.
  const lines = activity.settledLines({ name: 'deliver_to_game', status: 'error', result: { error } })
  assert.equal(lines.sentence, 'MexCLI could not rebuild the disc image.')
  assert.match(lines.alternative, /Open the build screen/)
  const html = render({ title: 'Your game', outcome: 'failed', error })
  assert.match(html, /MexCLI could not rebuild the disc image/)
  assert.match(html, /Open the build screen/)
  // An error with no readable text still says something true.
  assert.match(render({ title: 'x', outcome: 'failed', error: { code: 'weird' } }), /weird|did not work/)
})

test('a failed import is not a success, however the backend counted it', () => {
  const failed = taskEnvelope.projectInstallResult({ project_action: 'installed', installed_count: 2,
    failed_count: 1, project: { name: 'My Melee' } })
  assert.equal(failed.outcome, 'partial')
  const html = render(failed)
  assert.match(html, /1 could not be added/)
  assert.doesNotMatch(html, />Done</)
  assert.equal(taskEnvelope.projectInstallResult({ project_action: 'installed', installed_count: 2,
    project: { name: 'My Melee' } }).outcome, 'success')
})

test('a success carrying a blocking check is drawn as qualified, not green', () => {
  const html = render({ title: 'x', outcome: 'success',
    checks: [{ check_id: 'game_verification', status: 'unknown', required: true }] })
  assert.match(html, /is-partial/)
  assert.doesNotMatch(html, /is-clear/)
  assert.match(html, /Partly done/)
})

test('files are named without their ids', () => {
  assert.equal(taskEnvelope.artifactLabel({ name: 'PlPeNr_6f1c2a9b4e5d7a8c9012.dat' }), 'PlPeNr.dat')
  assert.equal(taskEnvelope.artifactLabel({ label: 'Your costume' }), 'Your costume')
})

// The chat's task record rides on every call (tool.task). A delivery waiting on the user's yes must show its approval
// card, and one that failed before it ran must show its own error, not the chat's still-running task as a result.
const chatTask = { task_id: 'task_1', revision: 1, state: 'running', outcome: null, contracts_version: 1,
  achieved: { prepared: false, exported: false, installed: false, previewed: false }, facts: {}, receipts: [] }

test('a delivery waiting for approval has no result envelope yet: its approval card shows', () => {
  assert.equal(taskEnvelope.settledEnvelope({ name: 'deliver_to_game', status: 'awaiting_approval', task: chatTask,
    approval: { id: 'a1', status: 'pending' } }), null)
})

test('a delivery that failed before it ran is not drawn from the chat task record', () => {
  assert.equal(taskEnvelope.settledEnvelope({ name: 'deliver_to_game', status: 'error', task: chatTask,
    result: { error: 'There is no game copy to put this in yet.' } }), null)
})

test('a settled delivery result is still its envelope', () => {
  const envelope = taskEnvelope.settledEnvelope({ name: 'deliver_to_game', status: 'done',
    result: { task_result: { ...chatTask, state: 'done', outcome: 'success', achieved: { installed: true } } } })
  assert.equal(envelope?.outcome, 'success')
  assert.equal(taskEnvelope.settledEnvelope({ name: 'deliver_to_game', status: 'running', task: chatTask }), null)
})
