import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

const realRequire = createRequire(import.meta.url)
const loadModule = (file, resolve) => {
  const built = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', built)(name => resolve(name) || realRequire(name), mod, mod.exports)
  return mod.exports
}
// The view only: the state (the job store, the cancel route) is mcpImport.js, tested in mcpImport.test.js.
let hookState = null
const chip = loadModule('./McpImportChip.jsx', name => {
  if (name === './mcpImport') return { useMcpImportChip: () => hookState }
  if (name === '../../shared/audio/sounds') return { playHoverSound: () => {}, playSound: () => {} }
  return null
})
const draw = view => renderToStaticMarkup(React.createElement(chip.McpImportChipView, { view, onCancel: () => {} }))

test('no import running: no chip at all', () => {
  assert.equal(draw(null), '')
  hookState = { view: null, cancel: () => {} }
  assert.equal(renderToStaticMarkup(React.createElement(chip.default)), '')
})

const running = (fields = {}) => ({ id: 'imp', state: 'running', model: 'Neos', fighter: 'Marth', change: false,
  step: 'putting it on the fighter', canCancel: true, error: null,
  title: 'Your AI is importing Neos as Marth: putting it on the fighter', ...fields })

test('a running import: Your AI, the model, onto whom, the step in words, and Cancel; the whole of it in the tooltip', () => {
  const html = draw(running())
  assert.equal(html, '<div class="mcp-import-chip is-running" role="status" aria-live="polite"'
    + ' title="Your AI is importing Neos as Marth: putting it on the fighter">'
    + '<span class="mcp-import-chip-words"><span class="mcp-import-chip-lead">Your AI</span>'
    + '<span class="mcp-import-chip-what"><span class="mcp-import-chip-model">Neos</span>'
    + '<span class="mcp-import-chip-fighter">as Marth</span>'
    + '<span class="mcp-import-chip-step">putting it on the fighter</span></span></span>'
    + '<button type="button" class="mcp-import-chip-cancel">Cancel</button></div>')
  assert.doesNotMatch(html, /style=/, 'no inline styles: the renderer runs under a strict CSP')
  // a change, on its fighter; no fighter yet (the importer picks one) and no step yet: those parts are left out
  assert.match(draw(running({ change: true })),
    /<span class="mcp-import-chip-model">changing Neos<\/span><span class="mcp-import-chip-fighter">on Marth<\/span>/)
  const bare = draw(running({ fighter: null, step: null }))
  assert.match(bare, /<span class="mcp-import-chip-what"><span class="mcp-import-chip-model">Neos<\/span><\/span>/)
})

test('stopping: Cancel is held; a failed Cancel says why where the step was; stopped: the note alone', () => {
  const stopping = draw(running({ state: 'stopping', step: 'Stopping…', canCancel: false }))
  assert.match(stopping, /class="mcp-import-chip is-stopping"/)
  assert.match(stopping, /<span class="mcp-import-chip-step">Stopping…<\/span>/)
  assert.match(stopping, /<button type="button" class="mcp-import-chip-cancel" disabled="">Cancel<\/button>/)
  const failed = draw(running({ error: 'Could not stop it: offline' }))
  assert.match(failed, /<span class="mcp-import-chip-error">Could not stop it: offline<\/span><\/span>/)
  assert.doesNotMatch(failed, /mcp-import-chip-step/, 'the error takes the step\'s place')
  const stopped = draw({ id: 'imp', state: 'stopped', text: 'Import stopped: nothing saved',
    title: 'Import stopped: nothing saved (Neos)', canCancel: false })
  assert.equal(stopped, '<div class="mcp-import-chip is-stopped" role="status" aria-live="polite"'
    + ' title="Import stopped: nothing saved (Neos)"><span class="mcp-import-chip-note">Import stopped: nothing saved</span></div>')
})
