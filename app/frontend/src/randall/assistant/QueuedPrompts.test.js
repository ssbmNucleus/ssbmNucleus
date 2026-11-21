import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import postcss from 'postcss'

const realRequire = createRequire(import.meta.url)
function compile(name) {
  const source = readFileSync(new URL(name, import.meta.url), 'utf8')
  const compiled = transformSync(source, { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const module = { exports: {} }
  const require = name => name.endsWith('.css') ? {} : name === './QueueIcons' ? compile('./QueueIcons.jsx') : realRequire(name)
  new Function('require', 'module', 'exports', compiled)(require, module, module.exports)
  return module.exports
}
const Queue = compile('./PendingMessages.jsx').default
const render = (n, running = true) => renderToStaticMarkup(React.createElement(Queue, {
  items: Array.from({ length: n }, (_, i) => ({ id: `${i}`, content: `Message ${i}` })), running,
}))

test('Ozone queue has one Send now action on the last bubble', () => {
  const html = render(3)
  assert.equal((html.match(/class="queued-steer-btn"/g) || []).length, 1)
  assert.match(html, /Send now all 3/)
  assert.ok(html.indexOf('Message 2') < html.indexOf('Send now all 3'))
  assert.equal((html.match(/title="Remove"/g) || []).length, 3)
  assert.equal((html.match(/title="More"/g) || []).length, 3)
  assert.doesNotMatch(html, /Steer now|Resume queue|Queue paused|Up next/)
})

test('Ozone count and Clear all appear only for at least three queued messages', () => {
  assert.doesNotMatch(render(2), /Clear all/)
  assert.match(render(3), /3 queued/)
  assert.match(render(3), /Clear all/)
  assert.match(render(1, false), /<span>Send<\/span>/)
  assert.equal(render(0), '')
})

test('ported queue CSS cannot style the app header, tabs or other menus', () => {
  const css = readFileSync(new URL('./QueuedPrompts.css', import.meta.url), 'utf8')
  const parsed = postcss.parse(css)
  parsed.walkRules(rule => {
    for (const selector of rule.selectors) {
      assert.match(selector, /(?:^|\s)\.queued-[\w-]+|^\.nucleus-assistant \.steered-tag$/,
        `Non-queue selector leaked into the port: ${selector}`)
    }
  })
  assert.doesNotMatch(css, /(?:^|\n)\s*(?:button|header|\.tab|\.brand|:root)[\s.{:#>]/)
})
