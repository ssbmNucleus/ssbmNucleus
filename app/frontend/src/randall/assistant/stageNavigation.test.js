import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveStageNavigation } from './stageNavigation.js'

const catalog = [{ code: 'GrOp', folder: 'dreamland', name: 'Dream Land' }, { code: 'GrNBa', folder: 'battlefield' }]
const variants = [{ id: 'same', stageCode: 'GrOp', name: 'Dream skin' }, { id: 'same', stageCode: 'GrNBa', name: 'Battle skin' }]
test('old folder receipts and new stage-code cards resolve the exact stage variant', () => {
  assert.equal(resolveStageNavigation({ folder: 'dreamland', id: 'same' }, catalog, variants).variant.name, 'Dream skin')
  assert.equal(resolveStageNavigation({ stageCode: 'GrNBa', id: 'same' }, catalog, variants).variant.name, 'Battle skin')
})
test('removed skins, folders, and unsupported stages cannot launch an editor', () => {
  for (const item of [{ folder: '../x', id: 'same' }, { stageCode: 'GrOp', id: 'gone' }]) {
    assert.throws(() => resolveStageNavigation(item, catalog, variants))
  }
  assert.throws(() => resolveStageNavigation({ stageCode: 'GrOp', id: 'same' }, catalog, [{ ...variants[0], type: 'folder' }]))
})
