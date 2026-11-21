import test from 'node:test'
import assert from 'node:assert/strict'
import { SSS_STATUS_LOCKED, SSS_STATUS_UNLOCKED, stageSlotUpdates } from './sssSlots.js'

// A slot as the editor's "add page" makes it (and as m-ex reads it back).
const lockedSlot = () => ({
  status: SSS_STATUS_LOCKED, stageID: 0, stageName: 'Locked',
  previewID: 0, randomSelectID: 0, iconPath: null, x: 1, y: 2, group: 0,
})

const BATTLEFIELD = { externalId: 31, internalId: 36, name: 'Battlefield' }
const CUSTOM = { externalId: 285, internalId: 71, name: 'Custom Stage' }

const firstPage = {
  name: 'Page 1',
  icons: [
    { status: 3, stageID: 0, stageName: 'Random', previewID: 255, randomSelectID: 0, iconPath: 'a/null.png' },
    { status: SSS_STATUS_UNLOCKED, stageID: 31, stageName: 'Battlefield',
      previewID: 24, randomSelectID: 17, iconPath: 'a/bf.png' },
  ],
}
const newPage = { name: 'New Page', icons: Array.from({ length: 30 }, lockedSlot) }

test('a Locked slot on a new page takes a stage and is unlocked', () => {
  const slot = { ...lockedSlot(), ...stageSlotUpdates(CUSTOM, [firstPage, newPage]) }
  assert.equal(slot.status, SSS_STATUS_UNLOCKED)
  assert.equal(slot.stageID, CUSTOM.externalId)
  assert.equal(slot.stageName, 'Custom Stage')
  // No icon for this stage anywhere yet: own ids kept, no picture until saved.
  assert.equal(slot.previewID, 0)
  assert.equal(slot.randomSelectID, 0)
  assert.equal(slot.iconPath, null)
  // Position fields are not touched.
  assert.equal(slot.x, 1)
  assert.equal(slot.y, 2)
})

test('a stage already on another page lends its picture and ids', () => {
  const updates = stageSlotUpdates(BATTLEFIELD, [firstPage, newPage])
  assert.deepEqual(updates, {
    status: SSS_STATUS_UNLOCKED, stageID: 31, stageName: 'Battlefield',
    iconPath: 'a/bf.png', previewID: 24, randomSelectID: 17,
  })
})

test('only an Unlocked icon of the same stage counts as its twin', () => {
  // The Random icon has stageID 0 too; it must not lend its ids to stage 0.
  const stage0 = { externalId: 0, internalId: 0, name: 'Dummy' }
  const updates = stageSlotUpdates(stage0, [firstPage, newPage])
  assert.equal(updates.iconPath, null)
  assert.equal('previewID' in updates, false)
})

test('no pages is fine', () => {
  assert.equal(stageSlotUpdates(BATTLEFIELD).stageID, 31)
})
