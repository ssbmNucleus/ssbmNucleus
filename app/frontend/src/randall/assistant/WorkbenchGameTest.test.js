import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

const realRequire = createRequire(import.meta.url)
const load = (file, resolve = () => null) => {
  const built = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', built)(name => resolve(name) || realRequire(name), mod, mod.exports)
  return mod.exports
}

// The capture itself is Electron's; the test drives what it reports.
let capture = { supported: true, state: { status: 'live', message: '' } }
let hookArgs, embedProps
const viewer = {
  __esModule: true,
  default: props => { embedProps = props; return React.createElement('div', { className: 'legacy-embed' }) },
  canCaptureDolphin: () => capture.supported,
  useDolphinCapture: args => { hookArgs = args; return { videoRef: { current: null }, state: capture.state, popout: () => {} } },
}
const crop = load('../../shared/viewer/captureCrop.js')
const view = load('./gameTestView.js')
const { default: WorkbenchGameTest } = load('./WorkbenchGameTest.jsx', name =>
  name === '../../shared/viewer/DolphinEmbedPanel' ? viewer
    : name === '../../shared/viewer/captureCrop' ? crop
      : name === './gameTestView' ? view : null)

const label = 'Young Link — Tung Tung Sahur'
const render = (state, extra = {}) => renderToStaticMarkup(React.createElement(WorkbenchGameTest,
  { label, state, previewActive: true, captureSessionId: 'owned', onStop: () => {}, ...extra }))
const playing = { snapshot: { running: true, status: { stage: 'playing', controllerPort: 1 } }, stopping: false }
const client = { x: 1, y: 31, width: 640, height: 480, frameWidth: 642, frameHeight: 512 }

test('live: a quiet title, a Live pill, small actions, the cropped game and the port hint', () => {
  capture = { supported: true, state: { status: 'live', message: '', client } }
  const html = render(playing)
  assert.match(html, /Tung Tung Sahur · Young Link/)
  assert.match(html, /is-live/); assert.match(html, /<i aria-hidden="true"><\/i>Live/)
  assert.match(html, />Open in Dolphin<\/button>/); assert.match(html, />Stop<\/button>/)
  assert.match(html, /<video[^>]*class="is-cropped"[^>]*top:-6.46%/)
  assert.match(html, /Playing on controller port 1/)
  assert.doesNotMatch(html, /Port 1 — play|Open Dolphin window/)
  assert.deepEqual(hookArgs, { active: true, expectedSessionId: 'owned' })
})

test('before the first frame the video stays hidden behind one quiet line; unknown geometry shows the whole frame', () => {
  capture = { supported: true, state: { status: 'starting', message: 'The game appears here once Dolphin boots…' } }
  const html = render(playing)
  assert.match(html, /visibility:hidden/); assert.match(html, /once Dolphin boots/)
  capture = { supported: true, state: { status: 'live', message: '' } }
  assert.doesNotMatch(render(playing), /is-cropped/)
})

test('building: the stage holds a calm bar, one plain line and a small percentage; no capture is started', () => {
  capture = { supported: true, state: { status: 'starting', message: '' } }
  const html = render({ snapshot: { running: true, status: { stage: 'building', percentage: 6,
    message: 'Importing the Young Link costume...' } } })
  assert.match(html, /Starting…/); assert.match(html, /role="progressbar"[^>]*aria-valuenow="6"/)
  assert.match(html, /Importing the Young Link costume…/); assert.match(html, /workbench-game-percent">6%/)
  assert.doesNotMatch(html, /<video|Open in Dolphin/); assert.match(html, />Stop<\/button>/)
  assert.equal(hookArgs.active, false)
})

test('ended: one muted line, no stage, no actions; a failure says why', () => {
  const ended = render({ snapshot: { running: false, lastEvent: { event: 'test_complete', payload: { success: true, reason: 'Playable preview stopped.' } } } })
  assert.match(ended, /workbench-game-ended">Play session ended\.</); assert.match(ended, />Ended</)
  assert.doesNotMatch(ended, /<button|workbench-game-stage|PASS/)
  const failed = render({ snapshot: { running: false, lastEvent: { event: 'test_error', payload: { error: 'Build failed.' } } } })
  assert.match(failed, /role="alert">Build failed\./); assert.match(failed, /is-failed/)
})

test('stopping disables Stop; without the Electron capture the shared embed fallback is used', () => {
  capture = { supported: true, state: { status: 'live', message: '', client } }
  assert.match(render({ ...playing, stopping: true }), /disabled="">Stopping…<\/button>/)
  capture = { supported: false, state: { status: 'starting', message: '' } }
  const html = render(playing)
  assert.match(html, /legacy-embed/); assert.doesNotMatch(html, /<video|Open in Dolphin/)
  assert.equal(embedProps.expectedSessionId, 'owned')
})
