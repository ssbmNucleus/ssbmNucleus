// The Skin Creator's texture strip in sections: Model (with an "also low-poly"
// mark on images both models draw), Low-poly model, Animated. The split comes
// from the backend's textureModels rows (one per texture the viewer lists before
// its animation frames); anything that does not line up keeps today's one list.
// Synthetic texture lists only. TextureStrip is server-rendered for the markup.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as paintProtocol from './paintProtocol.js'
import * as textureSections from './textureSections.js'

const { sectionTextures, launchTextureModels } = textureSections

const tex = (index, width = 64, height = 64, extra = {}) =>
  ({ index, name: `Texture_${index}`, width, height, thumbnail: '', ...extra })
const anim = (index, n, animates) =>
  ({ index, name: `MatAnim_${n}`, width: 32, height: 32, thumbnail: '', matAnim: true, animates })
const row = (model, width = 64, height = 64) => ({ width, height, model })

// Five material textures (one 128 wide), two blink frames.
const TEXTURES = [tex(0), tex(1, 128), tex(2), tex(3), tex(4), anim(5, 0, 2), anim(6, 1, 2)]
const MODELS = [row('both'), row('high', 128), row('low'), row('high'), row('low')]
const entries = (textures = TEXTURES) => textures.map((texture, position) => ({ texture, position }))
const ids = section => section.entries.map(entry => entry.position)

test('textures split into Model, Low-poly model and Animated, in list order', () => {
  const sections = sectionTextures(entries(), MODELS)
  assert.deepEqual(sections.map(s => [s.id, s.label]),
    [['model', 'Model'], ['low', 'Low-poly model'], ['animated', 'Animated']])
  const [model, low, animated] = sections
  assert.deepEqual(ids(model), [0, 1, 3])
  assert.deepEqual(ids(low), [2, 4])
  assert.deepEqual(ids(animated), [5, 6])
  assert.deepEqual(model.entries.map(e => e.model), ['both', 'high', 'high'])
  assert.ok(animated.entries.every(e => e.model === 'matanim'))
  assert.equal(model.entries[0].texture, TEXTURES[0], 'entries carry the strip\'s own texture rows')
})

test('a costume root past the model (a drawn hat, or an extra root) is part of the Model', () => {
  // Jigglypuff's hats: the viewer draws the hat root after the model, so its
  // textures follow the rows; an extra (undrawn) root is flagged instead.
  const textures = [tex(0), tex(1), tex(2, 8, 8), anim(3, 0, 0), tex(4, 16, 16, { extra: true })]
  const [model, low, animated] = sectionTextures(entries(textures), [row('high'), row('low')])
  assert.deepEqual(ids(model), [0, 2, 4])
  assert.deepEqual(model.entries.map(e => e.model), ['high', 'high', 'high'])
  assert.deepEqual(ids(low), [1])
  assert.deepEqual(ids(animated), [3])
})

test('unknown or mismatched models keep the single list', () => {
  assert.equal(sectionTextures(entries(), null), null)
  assert.equal(sectionTextures(entries(), undefined), null)
  assert.equal(sectionTextures(entries(), []), null)
  assert.equal(sectionTextures(entries(), MODELS.slice(1)), null, 'shifted by one: the sizes stop lining up')
  assert.equal(sectionTextures(entries(), [...MODELS, row('high')]), null, 'more rows than the viewer listed')
  assert.equal(sectionTextures(entries(), MODELS.map((r, i) => i === 1 ? row('high') : r)), null, 'a size differs')
  assert.equal(sectionTextures(entries(), MODELS.map((r, i) => i === 3 ? { ...r, model: 'alternate' } : r)), null)
  assert.equal(sectionTextures([], MODELS), null, 'nothing listed yet')
})

test('each viewer launch carries its own rows: one costume, or each climber of a pair', () => {
  assert.deepEqual(launchTextureModels({ textureModels: MODELS }, null), { '': MODELS })
  assert.deepEqual(launchTextureModels({}, null), { '': null })
  const pair = [{ memberId: 'popo', textureModels: MODELS }, { memberId: 'nana' }]
  assert.deepEqual(launchTextureModels(pair[0], pair), { popo: MODELS, nana: null })
})

// ------------------------------------------------------------------ TextureStrip
const realRequire = createRequire(import.meta.url)
let queued = []
const hooked = { ...React, useState: initial => queued.length ? [queued.shift(), () => {}] : React.useState(initial) }
const source = transformSync(readFileSync(new URL('./TextureStrip.jsx', import.meta.url), 'utf8'),
  { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
new Function('require', 'module', 'exports', source)(name => {
  if (name === 'react') return hooked
  if (name === './paintProtocol') return paintProtocol
  if (name === './textureSections') return textureSections
  return realRequire(name)
}, module, module.exports)
const TextureStrip = module.exports.default

const render = (props, query = '') => {
  queued = [query]
  try {
    return renderToStaticMarkup(React.createElement(TextureStrip, {
      modelTextures: TEXTURES, selectedTextureIndex: null, onSelectTexture: () => {}, editedTextures: {}, ...props }))
  } finally { queued = [] }
}
const sectionHtml = (html, label) => {
  const start = html.indexOf(`aria-label="${label} textures"`)
  assert.ok(start >= 0, `no ${label} section`)
  const end = html.indexOf('</section>', start)
  return html.slice(start, end)
}
const names = html => [...html.matchAll(/class="texture-name">([^<]*)</g)].map(m => m[1])

test('the strip shows each section with its header and count, the shared images marked', () => {
  const html = render({ textureModels: { '': MODELS }, selectedTextureIndex: 4 })
  assert.match(html, /Textures <span class="texture-count">7<\/span>/, 'the total stays in the panel header')
  const model = sectionHtml(html, 'Model')
  assert.match(model, /Model <span class="texture-count">3<\/span>/)
  assert.deepEqual(names(model), ['Texture_0', 'Texture_1', 'Texture_3'])
  assert.equal((model.match(/class="texture-also">also low-poly</g) || []).length, 1)
  assert.match(model, /aria-label="Textures Texture_0 · also low-poly"/)
  const low = sectionHtml(html, 'Low-poly model')
  assert.match(low, /Low-poly model <span class="texture-count">2<\/span>/)
  assert.deepEqual(names(low), ['Texture_2', 'Texture_4'])
  assert.match(low, /class="skin-creator-texture-item selected "[^>]*aria-label="Textures Texture_4 · low-poly"[^>]*aria-pressed="true"/,
    'selection is by list position, whichever section the texture sits in')
  const animated = sectionHtml(html, 'Animated')
  assert.match(animated, /Animated <span class="texture-count">2<\/span>/)
  assert.deepEqual(names(animated), ['MatAnim_0', 'MatAnim_1'])
  assert.ok(html.indexOf('Model textures') < html.indexOf('Low-poly model textures'))
  assert.ok(html.indexOf('Low-poly model textures') < html.indexOf('Animated textures'))
})

test('search filters across sections, recounts them, and hides an emptied one', () => {
  const html = render({ textureModels: { '': MODELS } }, '64x64')
  assert.deepEqual(names(sectionHtml(html, 'Model')), ['Texture_0', 'Texture_3'])
  assert.match(sectionHtml(html, 'Model'), /Model <span class="texture-count">2<\/span>/)
  assert.deepEqual(names(sectionHtml(html, 'Low-poly model')), ['Texture_2', 'Texture_4'])
  assert.doesNotMatch(html, /Animated textures/, 'no blink frame is 64x64')
  assert.deepEqual(names(render({ textureModels: { '': MODELS } }, 'matanim_1')), ['MatAnim_1'])
})

test('without models, or with rows that do not line up, the strip is one list as before', () => {
  for (const textureModels of [null, { '': null }, { '': MODELS.slice(2) }]) {
    const html = render({ textureModels })
    assert.doesNotMatch(html, /texture-section-header|also low-poly/)
    assert.deepEqual(names(html), TEXTURES.map(t => t.name))
  }
  assert.match(render({ modelTextures: [], textureModels: { '': MODELS } }), /Loading textures/)
})

test('an Ice Climbers pair sections each climber with its own rows', () => {
  const popo = [tex(0), tex(1), anim(2, 0, 0)].map(t => ({ ...t, memberId: 'popo' }))
  const nana = [tex(0, 32, 32), tex(1)].map(t => ({ ...t, memberId: 'nana' }))
  const html = render({ modelTextures: [...popo, ...nana],
    textureModels: { popo: [row('high'), row('low')], nana: [row('both', 32, 32), row('low')] } })
  assert.deepEqual(names(sectionHtml(html, 'Popo Model')), ['Texture_0'])
  assert.deepEqual(names(sectionHtml(html, 'Popo Low-poly model')), ['Texture_1'])
  assert.deepEqual(names(sectionHtml(html, 'Popo Animated')), ['MatAnim_0'])
  assert.match(sectionHtml(html, 'Nana Model'), /also low-poly/)
  assert.deepEqual(names(sectionHtml(html, 'Nana Low-poly model')), ['Texture_1'])
  // One climber's rows missing: that climber alone falls back to its list.
  const fallback = render({ modelTextures: [...popo, ...nana], textureModels: { popo: [row('high'), row('low')], nana: null } })
  assert.match(fallback, /Popo Low-poly model textures/)
  assert.doesNotMatch(fallback, /Nana Model textures/)
  assert.deepEqual(names(sectionHtml(fallback, 'Nana')), ['Texture_0', 'Texture_1'])
})
