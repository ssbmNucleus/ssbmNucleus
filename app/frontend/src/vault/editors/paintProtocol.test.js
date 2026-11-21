import test from 'node:test'
import assert from 'node:assert/strict'
import { textureKey, textureAddress, normalizePaintTextures, capturePaintPairExport,
  isCurrentTextureReply, isCurrentPaintTarget, texturesInPaintScope, requireCompletePairSave,
  shouldReloadPaintCanvas } from './paintProtocol.js'
import { createPaintPair, addPaintPairToZip } from './paintPair.js'

const source = () => createPaintPair([
  { name: 'Popo', datFile: '/popo.dat', datName: 'PlPpNr.dat', datBase64: 'old-popo' },
  { name: 'Nana', datFile: '/nana.dat', datName: 'PlNnNr.dat', datBase64: 'old-nana' }
])

test('a partial HTTP-success Vault import is never reported as a saved pair', () => {
  requireCompletePairSave({ success: true, imported_count: 2, pairing_complete: true })
  for (const result of [{ success: true, imported_count: 1 }, { success: true },
    { success: false, imported_count: 2 }, { success: true, imported_count: 2 },
    { success: true, imported_count: 2, pairing_complete: false }]) {
    assert.throws(() => requireCompletePairSave(result), /edits are retained/)
  }
})

test('both local texture zeroes remain distinct through list, edits and wire addressing', () => {
  const rows = normalizePaintTextures([{ memberId: 'popo', index: 0 }, { memberId: 'nana', index: 0 }], true)
  const edits = Object.fromEntries(rows.map(row => [textureKey(row), `${row.memberId}-paint`]))
  assert.deepEqual(edits, { 'popo:0': 'popo-paint', 'nana:0': 'nana-paint' })
  assert.deepEqual(rows.map(row => textureAddress(textureKey(row))), [
    { memberId: 'popo', index: 0 }, { memberId: 'nana', index: 0 }
  ])
  assert.deepEqual(normalizePaintTextures([{}, {}]).map(textureKey), ['0', '1'])
  assert.deepEqual(textureAddress('0'), { index: 0 })
  assert.throws(() => textureAddress('unknown:0'), /Invalid/)
  assert.throws(() => normalizePaintTextures([{ index: 0 }], true), /owner/)
  assert.throws(() => normalizePaintTextures([rows[0], rows[0]], true), /duplicate/)
})

test('full texture replies require matching session, request, owner and local index', () => {
  const current = { sessionId: 'new-editor', requestId: 'read-2', textureId: 'nana:0' }
  const reply = { sessionId: 'new-editor', requestId: 'read-2', memberId: 'nana', index: 0 }
  assert.equal(isCurrentTextureReply(reply, current), true)
  for (const mutation of [{ sessionId: 'closed-editor' }, { requestId: 'read-1' },
    { memberId: 'popo' }, { index: 1 }]) {
    assert.equal(isCurrentTextureReply({ ...reply, ...mutation }, current), false)
  }
})

test('delayed PNG decoding cannot paint after selection, return navigation or close/reopen', async () => {
  const captured = { generation: 2, textureId: 'popo:0', selection: 3 }
  let current = { ...captured }
  let commits = 0
  const finishImport = async () => { await Promise.resolve(); if (isCurrentPaintTarget(captured, current)) commits++ }
  await finishImport()
  assert.equal(commits, 1)
  current = { ...captured, textureId: 'nana:0' }
  await finishImport()
  current = { ...captured, selection: 5 }
  await finishImport()
  current = { ...captured, generation: 3 }
  await finishImport()
  assert.equal(commits, 1)
})

test('palette scope defaults to an owner and only explicit both spans DATs', () => {
  const rows = normalizePaintTextures([{ memberId: 'popo', index: 0 }, { memberId: 'nana', index: 0 }], true)
  assert.deepEqual(texturesInPaintScope(rows, 'popo').map(textureKey), ['popo:0'])
  assert.deepEqual(texturesInPaintScope(rows, 'nana').map(textureKey), ['nana:0'])
  assert.deepEqual(texturesInPaintScope(rows, 'both').map(textureKey), ['popo:0', 'nana:0'])
})

test('pair export binds by member ID, includes untouched partner, and writes original names', () => {
  const members = source()
  const updated = capturePaintPairExport(members, [{ memberId: 'nana', data: 'old-nana' },
    { memberId: 'popo', data: 'new-popo' }])
  const files = {}
  addPaintPairToZip({ file(name, data) { files[name] = data } }, updated)
  assert.deepEqual(files, { 'PlPpNr.dat': 'new-popo', 'PlNnNr.dat': 'old-nana' })
  assert.equal(members[0].datBase64, 'old-popo')
})

test('incomplete, duplicate or empty pair export leaves both original buffers intact', () => {
  const members = source()
  for (const invalid of [undefined, [{ memberId: 'popo', data: 'new-popo' }],
    [{ memberId: 'popo', data: 'new-popo' }, { memberId: 'popo', data: 'duplicate' }],
    [{ memberId: 'popo', data: 'new-popo' }, { memberId: 'nana', data: '' }],
    [{ memberId: 'popo', data: 'new-popo' }, { memberId: 'unknown', data: 'unknown' }]]) {
    assert.throws(() => capturePaintPairExport(members, invalid), /export|climber|pair/i)
    assert.deepEqual(members.map(member => member.datBase64), ['old-popo', 'old-nana'])
  }
})

test('the canvas skips reloading its own published stroke but repaints outside writes', () => {
  const stroke = 'data:image/png;base64,after-stroke'
  const mine = { textureId: 'popo:0', canvasOwner: 'popo:0', editedData: stroke, publishedData: stroke }

  // The echo of our own stroke: reloading here drops ownership mid-edit, which
  // is what ate undo clicks and the next stroke.
  assert.equal(shouldReloadPaintCanvas(mine), false)
  // Re-selecting a texture we edited earlier: same pixels, so the stack stands.
  assert.equal(shouldReloadPaintCanvas({ ...mine, canvasOwner: 'popo:0' }), false)

  // A palette recolor writes editedTextures without touching the canvas.
  assert.equal(shouldReloadPaintCanvas({ ...mine, editedData: 'data:image/png;base64,recolored' }), true)
  // First paint of the session: nothing published for this texture yet.
  assert.equal(shouldReloadPaintCanvas({ ...mine, publishedData: undefined }), true)
  // The canvas is holding another texture (or is mid-load), so it must repaint.
  assert.equal(shouldReloadPaintCanvas({ ...mine, canvasOwner: 'nana:0' }), true)
  assert.equal(shouldReloadPaintCanvas({ ...mine, canvasOwner: null }), true)
})
