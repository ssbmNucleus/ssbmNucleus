import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'


// The card now renders real results through the shared task cards, so those
// modules are loaded for real instead of stubbed away.
const loadModule = (file, resolve) => {
  const built = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', built)(
    name => resolve(name) || createRequire(import.meta.url)(name), mod, mod.exports)
  return mod.exports
}
const activityModule = loadModule('./activity.js', () => null)
const envelopeModule = loadModule('./taskEnvelope.js', () => null)
const taskCardsModule = loadModule('./TaskCards.jsx', name => name === './activity' ? activityModule
  : name === './taskEnvelope' ? envelopeModule : null)
const sharedModule = name => name === './activity' ? activityModule
  : name === './taskEnvelope' ? envelopeModule
    : name === './TaskCards' ? taskCardsModule : null

const code = transformSync(readFileSync(new URL('./GameTestCard.jsx', import.meta.url), 'utf8'),
  { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }, realRequire = createRequire(import.meta.url)
let running, workbench
const require = name => {
  if (name === '../../shared/viewer/InGameTestPanel') return { InGameTestRunning: props => {
    running = props
    return React.createElement('button', { disabled: props.test.stoppingTest }, 'Stop')
  } }
  if (name === './WorkbenchGameTest') return { __esModule: true, default: props => {
    workbench = props
    return React.createElement('section', { className: 'workbench-game-test' })
  } }
  return sharedModule(name) || (name.startsWith('.') ? {} : realRequire(name))
}
new Function('require', 'module', 'exports', code)(require, module, module.exports)
const tool = { result: { game_test: { session_id: 'one', label: 'Blue Fox' } } }
const render = (state, extra = {}) => renderToStaticMarkup(React.createElement(module.exports.GameTestView,
  { tool, state, live: true, visible: true, onStop: () => {}, ...extra }))

test('card keeps Stop while reconnecting and shows the exact target', () => {
  const html = render({ snapshot: null })
  assert.match(html, /Blue Fox/); assert.match(html, />Stop<\/button>/)
  assert.match(html, /Connecting/)
})

test('live card forwards exact capture identity and hides video when chat is hidden', () => {
  const state = { snapshot: { running: true, capture_session_id: 'owned-window', status: { stage: 'playing' } }, stopping: true }
  render(state); assert.equal(running.captureSessionId, 'owned-window')
  assert.equal(running.previewActive, true); assert.equal(running.test.stoppingTest, true)
  render(state, { visible: false }); assert.equal(running.previewActive, false)
})

test('an ended manual session is never labelled a gameplay pass', () => {
  const html = render({ snapshot: { running: false, lastEvent: { event: 'test_complete', payload: { success: true, reason: 'Stopped.' } } } })
  assert.match(html, /Play session ended/); assert.doesNotMatch(html, /PASS|>Stop<\/button>/)
})

test('start and running failures remain visible; duplicate receipts mount no live view', () => {
  assert.match(render({}, { tool: { result: { error: 'Close the open Dolphin first.' } } }), /role="alert"/)
  assert.match(render({ snapshot: { running: false, lastEvent: { event: 'test_error', payload: { error: 'Build failed.' } } } }), /Build failed/)
  assert.doesNotMatch(render({}, { live: false }), />Stop<\/button>|Connecting/)
})

test('the workbench gets its own presentation of the same session, with the same capture identity', () => {
  const stop = () => {}
  const state = { snapshot: { running: true, capture_session_id: 'owned-window', status: { stage: 'playing' } } }
  running = null
  const html = render(state, { layout: 'workbench', onStop: stop })
  assert.match(html, /workbench-game-test/); assert.equal(running, null)
  assert.equal(workbench.label, 'Blue Fox'); assert.equal(workbench.captureSessionId, 'owned-window')
  assert.equal(workbench.previewActive, true); assert.equal(workbench.onStop, stop); assert.equal(workbench.state, state)
  render(state, { layout: 'workbench', visible: false }); assert.equal(workbench.previewActive, false)
  // Old receipts and start failures read the same in both places.
  assert.doesNotMatch(render({}, { layout: 'workbench', live: false }), /workbench-game-test/)
})
