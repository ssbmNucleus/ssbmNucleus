import test from 'node:test'
import assert from 'node:assert/strict'
import { uniqueCostumeDisplayItems } from './costumeDisplayIdentity.js'

test('legacy duplicates get one key without changing raw reorder indices', () => {
  const items = [
    { type: 'skin', skin: { id: 'a' }, arrayIndex: 2 },
    { type: 'folder', folder: { id: 'folder' }, arrayIndex: 0 },
    { type: 'skin', skin: { id: 'b' }, arrayIndex: 1 },
    { type: 'skin', skin: { id: 'a' }, arrayIndex: 3 },
  ]
  assert.deepEqual(uniqueCostumeDisplayItems(items), items.slice(0, 3))
  assert.equal(items.length, 4)
})

test('reorder then remove and same-ID reimport do not keep a tombstone', () => {
  const a = { type: 'skin', skin: { id: 'a' }, arrayIndex: 0 }
  const b = { type: 'skin', skin: { id: 'b' }, arrayIndex: 1 }
  assert.deepEqual(uniqueCostumeDisplayItems([b, a, a]), [b, a])
  assert.deepEqual(uniqueCostumeDisplayItems([b]), [b])
  const reimported = { ...a, skin: { id: 'a', color: 'New' } }
  assert.deepEqual(uniqueCostumeDisplayItems([b, reimported]), [b, reimported])
})
