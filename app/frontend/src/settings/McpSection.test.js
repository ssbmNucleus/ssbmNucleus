import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as commands from './mcpCommands.js'

const realRequire = createRequire(import.meta.url)
const built = transformSync(readFileSync(new URL('./McpSection.jsx', import.meta.url), 'utf8'),
  { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const mod = { exports: {} }
new Function('require', 'module', 'exports', built)(name => (name === './mcpCommands' ? commands
  : name === '../shared/audio/sounds' ? { playHoverSound: () => {}, playSound: () => {} } : realRequire(name)),
mod, mod.exports)
const { McpView } = mod.exports

const launch = { command: 'C:\\Programs\\SSBM Nucleus\\SSBM Nucleus.exe', args: ['--mcp'] }
const draw = props => renderToStaticMarkup(React.createElement(McpView, props))

test('one AI app at a time: three pills, the picked one on, only its command shown', () => {
  const html = draw({ launch })
  assert.equal(html.match(/class="ai-pill( is-on)?"/g).length, 3)
  assert.match(html, /aria-selected="true" class="ai-pill is-on">Claude Code</)
  assert.equal(html.match(/<pre /g).length, 1)
  assert.ok(html.includes('claude mcp add --scope user nucleus'))
  const codex = draw({ launch, client: 'codex' })
  assert.match(codex, /aria-selected="true" class="ai-pill is-on">Codex</)
  assert.ok(codex.includes('codex mcp add nucleus'))
  assert.ok(!codex.includes('claude mcp add'))
  assert.match(draw({ launch, client: 'claude-desktop' }), /mcpServers/)
})

test('outside the desktop app there is no command, and the approve-buttons caution always shows', () => {
  const html = draw({ launch: null })
  assert.match(html, /Available in the desktop app\./)
  assert.doesNotMatch(html, /<pre |ai-pill/)
  assert.match(html, /skip Randall&#x27;s Approve buttons/)
})
