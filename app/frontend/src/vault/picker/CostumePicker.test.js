// The shared fighter/costume picker, server-rendered in both modes. Effects do
// not run in a server render, so the stock list is handed in as state.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as picks from './costumePicks.js'

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
const CostumePicker = load(new URL('./CostumePicker.jsx', import.meta.url), name => ({
  '../../shared/ui/GalleryGrid': GalleryGrid,
  '../../shared/transport/api': { api: { get: () => new Promise(noop) } },
  '../../shared/config/config': { backendMediaUrl: path => `http://backend${path}` },
  '../../shared/audio/sounds': sounds,
  './costumePicks': picks,
})[name]).default

const METADATA = { characters: { Fox: { skins: [
  { id: 'fox-blue', color: 'Blue Hoodie' }, { id: 'fox-red', color: 'Red Scarf' },
] } } }
const STOCK = { character: 'Fox', state: 'ready', rows: [
  { code: 'PlFxNr', colorCode: 'Nr', colorName: 'Default', hasCsp: true },
  { code: 'PlFxOr', colorCode: 'Or', colorName: 'Orange', hasCsp: true },
] }
const render = (props, states = []) => {
  queue = [...states]
  try { return renderToStaticMarkup(React.createElement(CostumePicker, { onChange: noop, ...props })) }
  finally { queue = [] }
}
const cells = html => [...html.matchAll(/<button type="button" class="gallery-cell[^"]*" title="([^"]*)"/g)].map(m => m[1].replaceAll('&amp;', '&'))

test('fighter mode: one grid of the fighters it is given, no counts', () => {
  const fighters = picks.rosterOf({ exclude: ['Ice Climbers'] })
  const html = render({ mode: 'fighter', metadata: METADATA, fighters })
  assert.match(html, /<strong>Which fighter does it go on\?<\/strong>/)
  assert.match(html, /class="gallery-grid gallery-grid--icon gallery-grid--navigable" role="listbox" aria-label="Fighters"/)
  assert.deepEqual(cells(html), ['AI Choice', ...fighters])
  assert.ok(!cells(html).includes('Ice Climbers'))
  assert.match(html, /src="http:\/\/backend\/vanilla\/Fox\/css_icon.png" alt="" loading="lazy"/)
  assert.doesNotMatch(html, /gallery-badge/)
  assert.match(html, /aria-label="Search fighters"/)
})

test('fighter mode marks the picked fighter and makes it the tab stop', () => {
  const html = render({ mode: 'fighter', fighters: ['Fox', 'Marth'], value: { kind: 'fighter', character: 'Marth' } })
  assert.match(html, /title="Marth" role="option" aria-selected="true" tabindex="0"/)
  assert.match(html, /title="Fox" role="option" aria-selected="false" tabindex="-1"/)
})

test('costume mode starts at the fighters, with each fighter’s vault count', () => {
  const html = render({ mode: 'costume', metadata: METADATA })
  assert.match(html, /<strong>Pick a fighter<\/strong>/)
  assert.equal(cells(html).length, 26)
  assert.match(html, /title="Fox"[^>]*>.*?<span class="gallery-badge">2<\/span>/)
})

test('costume mode, a fighter chosen: the vault costumes, then the stock slots', () => {
  const pick = { kind: 'vault', character: 'Fox', id: 'fox-red', name: 'Red Scarf' }
  // useState: fighter (from the value), query, stock.
  const html = render({ mode: 'costume', metadata: METADATA, value: pick }, [SKIP, SKIP, STOCK])
  assert.match(html, /aria-label="Back to fighters"/)
  assert.match(html, /<strong>Fox<\/strong>/)
  assert.deepEqual(cells(html), ['Blue Hoodie', 'Red Scarf', 'Default', 'Orange'])
  assert.match(html, /title="Red Scarf" role="option" aria-selected="true" tabindex="0"/)
  assert.equal(html.match(/<span class="gallery-badge">Stock<\/span>/g).length, 2)
  assert.match(html, /src="http:\/\/backend\/storage\/Fox\/fox-blue_csp.png"/)
  assert.match(html, /src="http:\/\/backend\/vanilla\/Fox\/PlFxOr\/csp.png"/)
  assert.doesNotMatch(html, /in your vault yet/)
})

test('an empty vault offers the stock costumes and says so', () => {
  const html = render({ mode: 'costume', metadata: { characters: {} } }, ['Marth', SKIP,
    { character: 'Marth', state: 'ready', rows: [{ code: 'PlMsNr', colorCode: 'Nr', colorName: 'Default', hasCsp: true }] }])
  assert.match(html, /No Marth costumes in your vault yet\. Start from a stock one\./)
  assert.deepEqual(cells(html), ['Default'])
})

test('no stock list either: nothing to pick, and words still work', () => {
  const html = render({ mode: 'costume', metadata: {} }, ['Marth', SKIP, { character: 'Marth', state: 'missing', rows: [] }])
  assert.doesNotMatch(html, /gallery-grid/)
  assert.match(html, /No Marth costumes in your vault, and the stock ones are not available: refresh the vanilla assets in Settings\. You can still describe the costume in words\./)
  const loading = render({ mode: 'costume', metadata: METADATA }, ['Fox', SKIP, { character: 'Fox', state: 'loading', rows: [] }])
  assert.match(loading, /Loading the stock costumes…/)
  assert.deepEqual(cells(loading), ['Blue Hoodie', 'Red Scarf'])
})

test('a search with no match says so', () => {
  const html = render({ mode: 'fighter', fighters: ['Fox'] }, [SKIP, 'zz'])
  assert.match(html, /Nothing matches “zz”/)
  assert.doesNotMatch(html, /gallery-grid/)
})

test('AI Choice: the first tile in fighter mode, absent in costume mode, found by its words', () => {
  const html = render({ mode: 'fighter', fighters: ['Fox', 'Marth'] })
  assert.deepEqual(cells(html), ['AI Choice', 'Fox', 'Marth'])
  assert.match(html, /title="AI Choice"[^>]*>.*?<span class="gallery-thumb--glyph" aria-hidden="true">\?<\/span>.*?<span class="gallery-name">AI Choice<\/span>/)
  assert.deepEqual(cells(render({ mode: 'costume', metadata: METADATA })).includes('AI Choice'), false)
  for (const q of ['ai', 'random', 'auto', 'choice']) assert.equal(cells(render({ mode: 'fighter', fighters: ['Fox'] }, [SKIP, q]))[0], 'AI Choice', q)
  assert.deepEqual(cells(render({ mode: 'fighter', fighters: ['Fox'] }, [SKIP, 'fox'])), ['Fox'])
  const picked = render({ mode: 'fighter', fighters: ['Fox'], value: picks.aiPick() })
  assert.match(picked, /title="AI Choice" role="option" aria-selected="true" tabindex="0"/)
})
