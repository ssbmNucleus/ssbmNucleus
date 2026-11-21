// The assistant panel's per-tool routing (ToolCard in AssistantPanel.jsx).
// Everything it delegates to is stubbed: these tests are about which path a
// stored tool call takes, and that it renders at all.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as activity from './activity.js'

const compiled = transformSync(readFileSync(new URL('./AssistantPanel.jsx', import.meta.url), 'utf8'),
  { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
const realRequire = createRequire(import.meta.url)
const routed = []
// Any other app module: components render a marker naming themselves, helpers return nothing.
const stub = (name) => new Proxy({}, {
  get: (_, key) => {
    if (key === '__esModule') return true
    if (key === 'then') return undefined
    const label = `${name}:${String(key)}`
    const fn = (props) => { routed.push(label); return props?.tool ? React.createElement('i', { 'data-stub': label }) : null }
    return fn
  },
})
new Function('require', 'module', 'exports', compiled)(name => {
  if (name === './activity') return activity
  if (name === 'react-markdown' || name === 'remark-gfm') return { __esModule: true, default: () => null }
  if (name.endsWith('.css')) return {}
  if (name.startsWith('.')) return stub(name)
  return realRequire(name)
}, module, module.exports)
const { ToolCard } = module.exports
const render = tool => renderToStaticMarkup(React.createElement(ToolCard, { tool, cards: [], selection: new Set() }))

test('a stored chat with a retired first-import step renders as a plain labelled step', () => {
  // model_candidate, model_fit, model_mesh and model_revise are not produced by
  // any backend code now; an old chat's export result must still render.
  for (const [name, label] of [['model_candidate', 'The costume file'], ['model_fit', 'Fitted to a fighter'],
    ['model_revise', 'Repaired the costume']]) {
    routed.length = 0
    const html = render({ id: 't1', name, status: 'done', result: { operation: 'export', file_id: 'f1',
      warnings: ['The file did not read back the same.'], files: [{ file_id: 'f1', name: 'PlFxNr.dat' }] } })
    assert.match(html, new RegExp(`<strong>${label}</strong>`), name)
    assert.match(html, /Done/, name)
    assert.doesNotMatch(html, /ModFileCards:ModToolActivity/, name)
    assert.equal(routed.includes('./ModFileCards:ModToolActivity'), false, name)
  }
})

test('the current import tool still reaches the model step card', () => {
  routed.length = 0
  const html = render({ id: 't2', name: 'import_model', status: 'done', result: {} })
  assert.match(html, /data-stub="\.\/ModFileCards:ModToolActivity"/)
})
