// GallerySelect (the Tracker's watch-with-mods skin and stage picker) after its
// grid moved into GalleryGrid.jsx: the markup must be exactly what it was. The
// fixture is the pre-move component's server render, captured 2026-10-03 for
// the same props, closed and open (the open panel is a portal and a layout
// effect, so the test hands the component its open state and position).
// Also GalleryGrid's own keyboard mode, which only the inline picker turns on.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

const realRequire = createRequire(import.meta.url)
const BEFORE = JSON.parse(readFileSync(new URL('./__fixtures__/gallerySelectMarkup.fixture.json', import.meta.url), 'utf8'))

// useState answers the queued values first (SKIP = the component's own default).
const SKIP = Symbol('skip')
let queue = []
const hooked = { ...React, useState: (initial) => {
  if (queue.length) { const next = queue.shift(); if (next !== SKIP) return [next, () => {}] }
  return React.useState(initial)
} }
const noop = () => {}
function load(file) {
  const code = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'), { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => {
    if (name === 'react') return hooked
    if (name === 'react-dom') return { createPortal: node => node }
    if (name === '../audio/sounds') return { playSound: noop, playHoverSound: noop }
    if (name === './GalleryGrid') return grid
    if (name.endsWith('.css')) return {}
    return realRequire(name)
  }, module, module.exports)
  return module.exports
}
const grid = load('./GalleryGrid.jsx')
const GallerySelect = load('./GallerySelect.jsx').default
const GalleryGrid = grid.default

function render(props, states = []) {
  queue = [...states]
  const hadDocument = 'document' in globalThis
  if (!hadDocument) globalThis.document = { body: {} }
  try { return renderToStaticMarkup(React.createElement(GallerySelect, { onChange: noop, options: OPTIONS, placeholder: 'Vanilla', ...props })) }
  finally { queue = []; if (!hadDocument) delete globalThis.document }
}
const OPTIONS = [
  { value: 'a1', label: 'Blue hoodie', icon: 'http://backend/storage/Fox/a1_csp.png' },
  { value: 42, label: 'No picture' },
  { value: 'c3', label: 'plmswh-ghirihim-white-plmsre-ghirihim-red', icon: 'http://backend/storage/Fox/c3_csp.png' },
]
const POS = { left: 12, width: 380, top: 60, bottom: undefined, maxH: 400 }

test('the Tracker picker renders exactly the markup it had before the grid moved out', () => {
  const now = {
    'closed-empty': render({ value: '' }),
    'closed-picked': render({ value: 'a1', searchPlaceholder: 'Search skins…' }),
    'closed-picked-noicon': render({ value: 42 }),
    'open-portrait-plain': render({ value: '', searchPlaceholder: 'Search skins…' }, [true, SKIP, POS]),
    'open-portrait-picked': render({ value: 'c3', panelClassName: 'extra' }, [true, SKIP, POS]),
    'open-landscape': render({ value: 42, aspect: 'landscape', searchPlaceholder: 'Search stage mods…' }, [true, SKIP, { ...POS, top: undefined, bottom: 30 }]),
    'open-query-nomatch': render({ value: '' }, [true, 'zzz', POS]),
    'open-query-match': render({ value: '' }, [true, 'HOOD', POS]),
    'open-no-options': render({ value: '', options: [] }, [true, SKIP, POS]),
  }
  assert.deepEqual(Object.keys(now), Object.keys(BEFORE))
  for (const key of Object.keys(BEFORE)) assert.equal(now[key], BEFORE[key], key)
  // None of the inline grid's keyboard markup leaks into the popup.
  assert.doesNotMatch(Object.values(now).join(''), /tabindex|role="listbox"|aria-selected|gallery-grid--|gallery-badge/)
})

test('the inline grid has one tab stop, listbox roles and badges', () => {
  const html = renderToStaticMarkup(React.createElement(GalleryGrid, { navigable: true, label: 'Fox costumes',
    className: 'gallery-grid--portrait', value: 'c3', onPick: noop,
    options: [...OPTIONS, { value: 's:PlFxOr', label: 'Orange', icon: '/vanilla/Fox/PlFxOr/csp.png', badge: 'Stock' }] }))
  assert.match(html, /^<div class="gallery-grid gallery-grid--portrait gallery-grid--navigable" role="listbox" aria-label="Fox costumes">/)
  assert.equal(html.match(/tabindex="0"/g).length, 1)
  assert.equal(html.match(/tabindex="-1"/g).length, 3)
  // The tab stop is the picked cell.
  assert.match(html, /<button type="button" class="gallery-cell is-selected" title="plmswh[^"]*" role="option" aria-selected="true" tabindex="0">/)
  assert.match(html, /<span class="gallery-badge">Stock<\/span>/)
  assert.match(html, /loading="lazy"/)
  // Nothing picked: the first cell is the stop.
  const none = renderToStaticMarkup(React.createElement(GalleryGrid, { navigable: true, value: '', onPick: noop, options: OPTIONS }))
  assert.match(none, /^<div[^>]*><button type="button" class="gallery-cell " title="Blue hoodie" role="option" aria-selected="false" tabindex="0">/)
})

test('arrow keys move by reading order and by laid-out rows', () => {
  const { galleryMove } = grid
  // Three per row, a short last row: 0 1 2 / 3 4 5 / 6
  const boxes = [0, 1, 2, 3, 4, 5, 6].map(index => ({ top: Math.floor(index / 3) * 150, left: (index % 3) * 90 }))
  assert.equal(galleryMove('ArrowRight', boxes, 2), 3)
  assert.equal(galleryMove('ArrowLeft', boxes, 0), 0)
  assert.equal(galleryMove('ArrowDown', boxes, 1), 4)
  assert.equal(galleryMove('ArrowDown', boxes, 5), 6, 'the nearest cell of a shorter row')
  assert.equal(galleryMove('ArrowDown', boxes, 6), 6, 'the last row stays')
  assert.equal(galleryMove('ArrowUp', boxes, 6), 3)
  assert.equal(galleryMove('ArrowUp', boxes, 2), 2)
  assert.equal(galleryMove('Home', boxes, 5), 0)
  assert.equal(galleryMove('End', boxes, 1), 6)
  assert.equal(galleryMove('Enter', boxes, 1), null, 'Enter is the button’s own click')
  assert.equal(galleryMove('ArrowDown', [], 0), null)
})
