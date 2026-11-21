import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { parse } from '@babel/parser'

// Evaluate the actual header URL expression, including aliases. The older
// inline-src lint guard missed iconUrl and let authenticated images regress.
const source = fs.readFileSync(new URL('./CustomCharacterDetailView.jsx', import.meta.url), 'utf8')
const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] })
let initializer
function visit(node) {
  if (!node || typeof node !== 'object') return
  if (node.type === 'VariableDeclarator' && node.id.name === 'iconUrl') initializer = node.init
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach(visit)
    else if (value && typeof value === 'object') visit(value)
  }
}
visit(ast)
assert.ok(initializer, 'custom character header defines an icon URL')
const expression = source.slice(initializer.start, initializer.end)

test('built Giga and imported character header URLs authenticate and preserve refresh versions', async () => {
  const previous = globalThis.window
  globalThis.window = { electron: { backendPort: 51234, backendToken: 'icon-test-token' } }
  try {
    const config = await import('../../shared/config/config.js?character-icon-test')
    for (const slug of ['giga-bowser', 'custom-fighter']) {
      const makeUrl = overrides => vm.runInNewContext(`(${expression})`, {
        ...config, hasIcon: true, character: { slug }, assetBust: 17, ...overrides
      })
      const url = new URL(makeUrl())
      assert.equal(url.origin, 'http://127.0.0.1:51234')
      assert.equal(url.pathname, `/api/mex/custom-characters/${slug}/icon`)
      assert.equal(url.searchParams.get('_nucleus_token'), 'icon-test-token')
      assert.equal(url.searchParams.get('v'), '17')
      assert.equal(makeUrl({ hasIcon: false }), null)
    }
  } finally {
    if (previous === undefined) delete globalThis.window
    else globalThis.window = previous
  }
})
