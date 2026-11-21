// The stage picker ("Retexture a stage"), server-rendered in both steps. Effects do
// not run in a server render, so the variant list is handed in as state.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as costumePicks from './costumePicks.js'
import * as stagePicks from './stagePicks.js'

const realRequire = createRequire(import.meta.url)
const SKIP = Symbol('skip')
let queue = []
const hooked = { ...React, useState: (initial) => {
  if (queue.length) { const next = queue.shift(); if (next !== SKIP) return [next, () => {}] }
  return React.useState(initial)
} }
const noop = () => {}
function load(url, resolve) {
  const code = transformSync(readFileSync(url, 'utf8'), { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => {
    if (name === 'react') return hooked
    if (name.endsWith('.css')) return {}
    const stub = resolve(name)
    return stub === undefined ? realRequire(name) : stub
  }, module, module.exports)
  return module.exports
}
const sounds = { playSound: noop, playHoverSound: noop }
const GalleryGrid = load(new URL('../../shared/ui/GalleryGrid.jsx', import.meta.url), name => name === '../audio/sounds' ? sounds : undefined)
const StagePicker = load(new URL('./StagePicker.jsx', import.meta.url), name => ({
  '../../shared/ui/GalleryGrid': GalleryGrid,
  '../../shared/transport/api': { api: { get: () => new Promise(noop) } },
  '../../shared/config/config': { backendMediaUrl: path => `http://backend${path}` },
  '../../shared/audio/sounds': sounds,
  './costumePicks': costumePicks,
  './stagePicks': stagePicks,
})[name]).default

const STAGES = [
  { code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', legal: true, art: '/vanilla/stages/battlefield.png' },
  { code: 'GrNLa', name: 'Final Destination', folder: 'final_destination', legal: true, art: '/vanilla/stages/final destination.png' },
  { code: 'GrCn', name: 'Corneria', folder: 'corneria', legal: false, art: '/api/mex/stages/GrCn/art/icon' },
]
const READY = { state: 'ready', rows: [
  { stageCode: 'GrNBa', id: 'night-sky-1a2b', name: 'Night Sky', hasScreenshot: true,
    screenshotUrl: '/storage/das/battlefield/night-sky-1a2b_screenshot.png' },
  { type: 'folder', stageCode: 'GrNBa', id: 'folder_1', name: 'A folder' },
  { stageCode: 'GrNBa', id: 'plain', name: 'Plain', hasScreenshot: false },
] }
// useState order in StagePicker: stage, query, variants.
const render = (props, states = []) => {
  queue = [...states]
  try { return renderToStaticMarkup(React.createElement(StagePicker, { stages: STAGES, onChange: noop, ...props })) }
  finally { queue = [] }
}
const cells = html => [...html.matchAll(/<button type="button" class="gallery-cell[^"]*" title="([^"]*)"/g)].map(m => m[1])

test('first step: the stages status serves, as pictures, with their vault variant counts', () => {
  const html = render({}, [SKIP, SKIP, READY])
  assert.match(html, /<strong>Pick a stage<\/strong>/)
  assert.match(html, /class="gallery-grid gallery-grid--landscape gallery-grid--fit gallery-grid--navigable" role="listbox" aria-label="Stages"/)
  assert.deepEqual(cells(html), ['Battlefield', 'Final Destination', 'Corneria'])
  assert.match(html, /title="Battlefield"[^>]*>.*?<span class="gallery-badge">2<\/span>/)
  assert.match(html, /src="http:\/\/backend\/api\/mex\/stages\/GrCn\/art\/icon"/)
  assert.match(html, /aria-label="Search stages"/)
})

test('second step: the stage’s vault variants, then the stock stage, the pick marked', () => {
  const value = { kind: 'stage', stage: 'GrNBa', stageName: 'Battlefield', id: 'plain', name: 'Plain' }
  const html = render({ value }, [SKIP, SKIP, READY])
  assert.match(html, /aria-label="Back to stages"/)
  assert.match(html, /<strong>Battlefield<\/strong>/)
  assert.deepEqual(cells(html), ['Night Sky', 'Plain', 'Battlefield'])
  assert.match(html, /title="Plain" role="option" aria-selected="true" tabindex="0"/)
  assert.equal(html.match(/<span class="gallery-badge">Stock<\/span>/g).length, 1)
  assert.match(html, /src="http:\/\/backend\/storage\/das\/battlefield\/night-sky-1a2b_screenshot.png"/)
  assert.match(html, /class="gallery-grid gallery-grid--landscape gallery-grid--navigable" role="listbox" aria-label="Battlefield variants"/)
  assert.doesNotMatch(html, /in your vault yet/)
})

test('a stage with no vault variants offers the stock one and says so', () => {
  const html = render({}, ['GrCn', SKIP, READY])
  assert.match(html, /No Corneria variants in your vault yet\. Start from the stock stage\./)
  assert.deepEqual(cells(html), ['Corneria'])
})

test('while variants load, or when they cannot, the stock stage is still offered', () => {
  const loading = render({}, ['GrNLa', SKIP, { state: 'loading', rows: [] }])
  assert.match(loading, /Loading your stage variants…/)
  assert.deepEqual(cells(loading), ['Final Destination'])
  const missing = render({}, ['GrNLa', SKIP, { state: 'missing', rows: [] }])
  assert.match(missing, /could not be loaded\. You can start from the stock stage\./)
  assert.deepEqual(cells(missing), ['Final Destination'])
})

test('no stage list (an older backend) says words still work', () => {
  const html = render({ stages: undefined }, [SKIP, SKIP, READY])
  assert.doesNotMatch(html, /gallery-grid/)
  assert.match(html, /No stages to pick from in this build\. You can still name the stage in words\./)
})
