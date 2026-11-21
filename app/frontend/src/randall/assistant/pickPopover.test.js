// Where the starting pick's popover opens, how tall it may be, and its keys.
import assert from 'node:assert/strict'
import test from 'node:test'
import { controlKey, dialogKey, popoverPlacement } from './pickPopover.js'

// A chat page from 0 to 800 in an 800px window.
const PAGE = { boundsTop: 0, boundsBottom: 800, viewportHeight: 800 }

test('the composer at the bottom of a chat: it opens above, as tall as the room up to 60% of the window', () => {
  const placed = popoverPlacement({ ...PAGE, anchorTop: 680, anchorBottom: 780 })
  assert.deepEqual(placed, { up: true, maxHeight: 480 })
  // A short page: the room above is the limit; a short window: 60% of it is.
  assert.deepEqual(popoverPlacement({ boundsTop: 0, boundsBottom: 420, viewportHeight: 1000, anchorTop: 300, anchorBottom: 400 }),
    { up: true, maxHeight: 280 })
  assert.deepEqual(popoverPlacement({ boundsTop: 0, boundsBottom: 420, viewportHeight: 420, anchorTop: 300, anchorBottom: 400 }),
    { up: true, maxHeight: 252 })
})

test('the centred composer of a new chat: below when there is 320px there, else the roomier side', () => {
  // A tall page: 400px under the box.
  assert.equal(popoverPlacement({ boundsTop: 0, boundsBottom: 1000, viewportHeight: 1000, anchorTop: 470, anchorBottom: 570 }).up, false)
  assert.equal(popoverPlacement({ boundsTop: 0, boundsBottom: 1000, viewportHeight: 1000, anchorTop: 470, anchorBottom: 570 }).maxHeight, 410)
  // An 800px page: the box's centre a little under the middle leaves 316 below and 350 above.
  const placed = popoverPlacement({ ...PAGE, anchorTop: 370, anchorBottom: 464 })
  assert.equal(placed.up, true)
  assert.equal(placed.maxHeight, 350)
  // GallerySelect's own rule: less than 320 below but more below than above stays below.
  assert.equal(popoverPlacement({ ...PAGE, anchorTop: 100, anchorBottom: 500 }).up, false)
})

test('it stays inside the chat page, not the window (the editor sidebar, a page below a header)', () => {
  const placed = popoverPlacement({ boundsTop: 100, boundsBottom: 700, viewportHeight: 1000, anchorTop: 580, anchorBottom: 680 })
  assert.deepEqual(placed, { up: true, maxHeight: 460 })
  assert.equal(popoverPlacement({ boundsTop: 0, boundsBottom: 50, viewportHeight: 50, anchorTop: 0, anchorBottom: 50 }).maxHeight, 0)
})

test('keys on the control: arrows open it, Escape closes it, the rest are the button’s', () => {
  assert.equal(controlKey('ArrowDown', false), 'open')
  assert.equal(controlKey('ArrowUp', false), 'open')
  assert.equal(controlKey('ArrowDown', true), null)
  assert.equal(controlKey('Escape', true), 'close')
  assert.equal(controlKey('Escape', false), null)
  assert.equal(controlKey('Enter', false), null, 'Enter and Space are the button’s own click')
})

test('keys in the open popover: Escape closes; Enter in the search picks the first match and never sends the message', () => {
  assert.equal(dialogKey({ key: 'Escape' }), 'close')
  assert.equal(dialogKey({ key: 'Enter', inSearch: true, query: 'fox' }), 'pick-first')
  assert.equal(dialogKey({ key: 'Enter', inSearch: true, query: '  ' }), 'hold')
  assert.equal(dialogKey({ key: 'Enter', inSearch: false }), null, 'Enter on a cell is the cell’s own click')
  assert.equal(dialogKey({ key: 'ArrowDown', inSearch: true, query: 'fox' }), null)
})
