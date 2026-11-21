import test from 'node:test'
import assert from 'node:assert/strict'
import { describeScanResults } from './isoScanResultModel.js'

const custom = (imported = [], errors = []) => ({ imported, skipped: [], errors })

test('zero skins does not hide three successfully imported characters', () => {
  const result = describeScanResults({ scanSkins: true, customSummary: {
    characters: custom(['Shulk', 'Little Mac', 'Incineroar']), stages: custom(), das: custom(),
  } })
  assert.equal(result.title, '3 items added to your vault')
  assert.equal(result.initialCategory, 'characters')
  assert.equal(result.ready, 0)
  assert.equal(result.issues, 0)
})

test('skins awaiting a decision are distinct from already imported content', () => {
  const result = describeScanResults({ scanSkins: true, characters: { Fox: [{ key: 'a' }, { key: 'b' }] },
    customSummary: { stages: custom(['New stage']) } })
  assert.equal(result.title, '2 character skins ready to import')
  assert.equal(result.added, 1)
  assert.equal(result.initialCategory, 'skins')
  assert.equal(result.categories.find(c => c.key === 'characters').scanned, false)
})

test('partial skin import counts successes without offering failed selections again', () => {
  const result = describeScanResults({ scanSkins: true, characters: { Fox: [{}, {}] },
    customSummary: { characters: custom(['Shulk']) },
    importResult: { imported: 1, errors: [{ key: 'b', error: 'failed' }] } })
  assert.equal(result.added, 2)
  assert.equal(result.ready, 0)
  assert.equal(result.issues, 1)
})

test('custom-only extraction failure never reports an empty successful scan', () => {
  const result = describeScanResults({ scanSkins: false, customSummary: { stages: custom([], ['Unreadable ISO']) } })
  assert.equal(result.title, 'Scan needs attention')
  assert.equal(result.initialCategory, 'stages')
  assert.equal(result.issues, 1)
})

test('a later skin scan failure retains earlier custom additions', () => {
  const result = describeScanResults({ scanSkins: true, scanError: 'Unreadable ISO',
    customSummary: { characters: custom(['Shulk']) } })
  assert.equal(result.title, '1 item added to your vault')
  assert.equal(result.initialCategory, 'characters')
  assert.equal(result.categories[0].issues, 1)
})

test('unavailable previews are reported as issues, not a successful empty scan', () => {
  const result = describeScanResults({ scanSkins: true, stats: { preview_failed: 2 } })
  assert.equal(result.title, 'Scan needs attention')
  assert.equal(result.issues, 2)
})

test('stage variants precede custom content without changing the category counts', () => {
  const result = describeScanResults({ scanSkins: true, customSummary: {
    das: custom(['Variant']), characters: custom(['Wolf', 'Shulk']), stages: custom(['Stage']),
  } })
  assert.deepEqual(result.categories.map(c => [c.key, c.label, c.added]), [
    ['skins', 'Character skins', 0], ['das', 'Stage variants', 1],
    ['characters', 'Custom characters', 2], ['stages', 'Custom stages', 1],
  ])
  assert.equal(result.initialCategory, 'das')
  assert.equal(result.added, 4)
})
