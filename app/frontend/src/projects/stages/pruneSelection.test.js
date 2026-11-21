import test from 'node:test'
import assert from 'node:assert/strict'
import { pruneSelection } from './pruneSelection.js'

test('drops keys whose item was deleted', () => {
  const live = new Set(['a', 'c'])
  const next = pruneSelection(new Set(['a', 'b', 'c']), key => live.has(key))
  assert.deepEqual([...next], ['a', 'c'])
})

test('returns the same Set when nothing is stale', () => {
  const selected = new Set(['a'])
  assert.equal(pruneSelection(selected, () => true), selected)
})

test('deleting the only selected item empties the selection', () => {
  assert.equal(pruneSelection(new Set(['x']), () => false).size, 0)
})
