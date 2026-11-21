import test from 'node:test'
import assert from 'node:assert/strict'

import { summarizeTransformFixResults } from './stadiumTransformFix.js'

test('returns no notice for non-Stadium imports', () => {
  assert.equal(summarizeTransformFixResults([]), null)
  assert.equal(summarizeTransformFixResults([{ name: 'Battlefield' }]), null)
})

test('summarizes a repaired Stadium and its geometry actions', () => {
  assert.deepEqual(summarizeTransformFixResults([{
    name: 'Sky High',
    transformFix: { status: 'repaired', actions: ['one', 'two'] }
  }]), {
    tone: 'success',
    title: 'Stadium transformation visibility fixed',
    message: 'This Stadium passed the transformation check and was repaired. 2 geometry moves applied.'
  })
})

test('keeps clean Stadium checks quiet when nothing changed', () => {
  const notice = summarizeTransformFixResults([{
    name: 'Texture Stadium',
    transformFix: { status: 'clean', actions: [] }
  }])
  assert.equal(notice, null)
})

test('aggregates repaired and clean batch results', () => {
  const notice = summarizeTransformFixResults([
    { name: 'Sky High', transformFix: { status: 'repaired', actions: ['a'] } },
    { name: 'Bell Tower', transformFix: { status: 'repaired', actions: ['b', 'c'] } },
    { name: 'Vanilla', transformFix: { status: 'clean', actions: [] } }
  ])
  assert.equal(notice.tone, 'success')
  assert.match(notice.message, /3 Stadium imports/)
  assert.match(notice.message, /2 repaired and 1 already clean/)
  assert.match(notice.message, /3 geometry moves/)
})

test('prioritizes a flagged or error result and names affected imports', () => {
  const notice = summarizeTransformFixResults([
    { name: 'Safe', transformFix: { status: 'repaired', actions: ['a'] } },
    { name: 'Unknown Layout', transformFix: { status: 'flagged', actions: [] } },
    { name: 'Broken File', transformFix: { status: 'error', notes: ['bad pointer'] } }
  ])
  assert.equal(notice.tone, 'warning')
  assert.match(notice.message, /2 imports/)
  assert.match(notice.message, /Unknown Layout, Broken File/)
  assert.match(notice.message, /test a transformation/i)
})
