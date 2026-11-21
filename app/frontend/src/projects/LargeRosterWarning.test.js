import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as risk from './rosterRisk.js'

const realRequire = createRequire(import.meta.url)
const module = { exports: {} }
const code = transformSync(readFileSync(new URL('./LargeRosterWarning.jsx', import.meta.url), 'utf8'), { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
new Function('require', 'module', 'exports', code)(name => name.endsWith('.css') ? {} : name === './rosterRisk' ? risk : realRequire(name), module, module.exports)
const Warning = module.exports.default
const roster = size => Array.from({ length: size }, (_, internalId) => ({ internalId }))
const render = props => renderToStaticMarkup(React.createElement(Warning, props))

test('only oversized rosters render a nonblocking risk note with qualified details', () => {
  assert.equal(render({ fighters: roster(63) }), '')
  const html = render({ fighters: roster(64) })
  assert.match(html, /This project has 64 fighter entries/)
  assert.match(html, /intermittent grab and command-grab desyncs/)
  assert.match(html, /even when the game builds and launches successfully/)
  assert.match(html, /partners, hidden fighters and reserved slots/)
  assert.match(html, /not a proven limit or a guarantee that smaller rosters are safe/)
  assert.doesNotMatch(html, /disabled|role="alert"|role="dialog"/)
})

test('batch selection uses the projected total and distinguishes it from installed count', () => {
  const html = render({ fighters: roster(62), additions: 2 })
  assert.match(html, /Adding 2 selected characters could bring this project from 62 to 64 fighter entries/)
  assert.equal(render({ fighters: roster(62), additions: 1 }), '')
})

test('loading and failed counts remain explicit at add/export checkpoints, without stale warning', () => {
  assert.equal(render({ fighters: roster(64), status: 'loading' }), '')
  assert.match(render({ fighters: roster(64), status: 'loading', showUnknown: true }), /Checking roster size/)
  const html = render({ fighters: roster(64), status: 'error', showUnknown: true, onRetry: () => {} })
  assert.match(html, /Roster size unavailable/)
  assert.match(html, /Retry roster check/)
  assert.doesNotMatch(html, /This project has 64/)
})
