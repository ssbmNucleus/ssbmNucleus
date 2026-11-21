import test from 'node:test'
import assert from 'node:assert/strict'
import { selectionHitZone, selectionCursor, gripRadius, moveSelection,
         resizeSelection, constrainDrag, selectionHandles } from './canvasUtils.js'

const box = { x: 10, y: 10, w: 20, h: 20 }   // covers 10..30 on both axes
const bounds = { width: 64, height: 64 }

test('the grab radius is a screen distance, so grips stay reachable at any zoom', () => {
  assert.equal(gripRadius(1), 5)            // 5 texture px at 1:1
  assert.equal(gripRadius(10), 0.5)         // still 5 screen px when zoomed 10x
  assert.equal(gripRadius(0), 5)            // a zoom of 0 must not divide by zero
})

test('hit zones name the edge, corner or middle under the pointer', () => {
  assert.equal(selectionHitZone(box, 10, 10, 1), 'nw')
  assert.equal(selectionHitZone(box, 30, 30, 1), 'se')
  assert.equal(selectionHitZone(box, 30, 10, 1), 'ne')
  assert.equal(selectionHitZone(box, 10, 30, 1), 'sw')
  assert.equal(selectionHitZone(box, 20, 10, 1), 'n')
  assert.equal(selectionHitZone(box, 20, 30, 1), 's')
  assert.equal(selectionHitZone(box, 10, 20, 1), 'w')
  assert.equal(selectionHitZone(box, 30, 20, 1), 'e')
  assert.equal(selectionHitZone(box, 20, 20, 1), 'inside')
  assert.equal(selectionHitZone(box, 50, 50, 1), null)   // outside -> drag a new one
  assert.equal(selectionHitZone(null, 20, 20, 1), null)
  // Corners win over the edges they share, so a corner is never unreachable.
  assert.equal(selectionHitZone(box, 11, 11, 3), 'nw')
  assert.equal(selectionCursor('nw'), 'nwse-resize')
  assert.equal(selectionCursor('inside'), 'move')
  assert.equal(selectionCursor(null), 'crosshair')
})

test('moving keeps the size and stays on the texture', () => {
  assert.deepEqual(moveSelection(box, 5, 5, bounds), { x: 15, y: 15, w: 20, h: 20 })
  assert.deepEqual(moveSelection(box, -100, -100, bounds), { x: 0, y: 0, w: 20, h: 20 })
  assert.deepEqual(moveSelection(box, 100, 100, bounds), { x: 44, y: 44, w: 20, h: 20 })
  // A selection wider than the texture is trimmed rather than left off-canvas.
  assert.deepEqual(moveSelection({ x: 0, y: 0, w: 200, h: 200 }, 0, 0, bounds),
    { x: 0, y: 0, w: 64, h: 64 })
})

test('resizing drags the grabbed edge only, and flips past its opposite', () => {
  assert.deepEqual(resizeSelection(box, 'e', 10, 0, bounds), { x: 10, y: 10, w: 30, h: 20 })
  assert.deepEqual(resizeSelection(box, 'w', 5, 0, bounds), { x: 15, y: 10, w: 15, h: 20 })
  assert.deepEqual(resizeSelection(box, 'n', 5, 5, bounds), { x: 10, y: 15, w: 20, h: 15 })
  assert.deepEqual(resizeSelection(box, 'se', 10, 10, bounds), { x: 10, y: 10, w: 30, h: 30 })
  // pulling the east edge left past the west edge mirrors the box
  assert.deepEqual(resizeSelection(box, 'e', -30, 0, bounds), { x: 0, y: 10, w: 10, h: 20 })
  // collapsed to nothing = no selection at all
  assert.equal(resizeSelection(box, 'e', -20, 0, bounds), null)
  // clamped to the texture, never past its edge
  assert.deepEqual(resizeSelection(box, 'se', 100, 100, bounds), { x: 10, y: 10, w: 54, h: 54 })
  assert.deepEqual(resizeSelection(box, 'inside', 10, 10, bounds), box)  // moves are not resizes
})

test('shift squares the drag off from its start corner in every direction', () => {
  assert.deepEqual(constrainDrag({ x: 0, y: 0 }, { x: 10, y: 3 }), { x: 10, y: 10 })
  assert.deepEqual(constrainDrag({ x: 20, y: 20 }, { x: 10, y: 17 }), { x: 10, y: 10 })
  assert.deepEqual(constrainDrag({ x: 20, y: 20 }, { x: 25, y: 10 }), { x: 30, y: 10 })
})

test('handles sit on the corners and edge midpoints', () => {
  const points = selectionHandles(box)
  assert.equal(points.length, 8)
  assert.deepEqual(points.find(p => p.zone === 'nw'), { zone: 'nw', x: 10, y: 10 })
  assert.deepEqual(points.find(p => p.zone === 's'), { zone: 's', x: 20, y: 30 })
  assert.deepEqual(selectionHandles(null), [])
})
