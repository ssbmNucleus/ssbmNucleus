import test from 'node:test'
import assert from 'node:assert/strict'
import { replayScanNeedsRefresh, comboScanNeedsRefresh } from './scanRefresh.js'

test('background replay scans preserve open months unless they add, update or remove games', () => {
  assert.equal(replayScanNeedsRefresh({ id: 'background', result: { added: 0, updated: 0, removed: 0 } }, 'manual'), false)
  for (const counter of ['added', 'updated', 'removed'])
    assert.equal(replayScanNeedsRefresh({ id: 'background', result: { [counter]: 1 } }, 'manual'), true)
  assert.equal(replayScanNeedsRefresh({ id: 'background', status: 'failed' }, 'manual'), false)
})

test('manual scans always refresh their own list, and combo scans refresh only after analyzing games', () => {
  assert.equal(replayScanNeedsRefresh({ id: 'manual', status: 'failed' }, 'manual'), true)
  assert.equal(comboScanNeedsRefresh({ id: 'manual', status: 'done' }, 'manual'), true)
  assert.equal(comboScanNeedsRefresh({ id: 'auto', result: { total: 0 } }, 'manual'), false)
  assert.equal(comboScanNeedsRefresh({ id: 'auto', result: { total: 3 } }, 'manual'), true)
  assert.equal(comboScanNeedsRefresh({ id: 'auto', status: 'failed' }, 'manual'), false)
})
