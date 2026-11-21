import test from 'node:test'
import assert from 'node:assert/strict'
import { inSelection, selectionFromDrag } from './canvasUtils.js'

const canvas = { width: 64, height: 32 }

test('no selection means every pixel is in scope', () => {
  assert.equal(inSelection(null, 0, 0), true)
  assert.equal(inSelection(null, 9999, 9999), true)
})

test('a selection excludes pixels outside it, edges included', () => {
  const sel = { x: 4, y: 8, w: 10, h: 6 }
  assert.equal(inSelection(sel, 4, 8), true)        // top-left corner is inside
  assert.equal(inSelection(sel, 13, 13), true)      // bottom-right corner is inside
  assert.equal(inSelection(sel, 14, 13), false)     // one past the right edge
  assert.equal(inSelection(sel, 13, 14), false)     // one past the bottom edge
  assert.equal(inSelection(sel, 3, 8), false)
})

test('a drag becomes a normalized rect whichever way it is dragged', () => {
  const forward = selectionFromDrag(canvas, { x: 5, y: 5 }, { x: 9, y: 8 })
  const backward = selectionFromDrag(canvas, { x: 9, y: 8 }, { x: 5, y: 5 })
  assert.deepEqual(forward, { x: 5, y: 5, w: 5, h: 4 })
  assert.deepEqual(backward, forward)
})

test('a drag is clamped to the canvas', () => {
  const sel = selectionFromDrag(canvas, { x: -20, y: -20 }, { x: 999, y: 999 })
  assert.deepEqual(sel, { x: 0, y: 0, w: 64, h: 32 })
})

test('a click (no drag) clears the selection instead of selecting one pixel', () => {
  assert.equal(selectionFromDrag(canvas, { x: 7, y: 7 }, { x: 7, y: 7 }), null)
})
