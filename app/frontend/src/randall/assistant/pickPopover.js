// The starting pick's popover (StartPicker.jsx `StartPickControl`): which side of
// the composer it opens on, how tall it may be, and what the keys do. Pure: no
// React, no DOM reads, so the rules are tested on their own (pickPopover.test.js).
//
// The side follows GallerySelect's own rule (shared/ui/GallerySelect.jsx `place`,
// the Tracker's picture picker): below the anchor, unless there is less than
// 320px there and more above. Its height is what that side leaves, never more
// than 60% of the window, and the picker scrolls inside it.

/**
 * `anchorTop`/`anchorBottom`: the composer box on screen; `boundsTop`/`boundsBottom`:
 * the chat page it must stay inside; `viewportHeight`: the window.
 * -> {up: true when it opens above the composer, maxHeight in px}
 */
export function popoverPlacement({ anchorTop, anchorBottom, boundsTop, boundsBottom, viewportHeight },
  { gap = 8, margin = 12, prefer = 320, cap = 0.6, least = 160 } = {}) {
  const above = Math.max(0, anchorTop - boundsTop - gap - margin)
  const below = Math.max(0, boundsBottom - anchorBottom - gap - margin)
  const up = below < prefer && above > below
  const room = up ? above : below
  return { up, maxHeight: Math.floor(Math.min(room, Math.max(least, viewportHeight * cap))) }
}

/** A key on the selection control itself: 'open' (arrows, like the task pill), 'close' (Escape while open) or null. */
export function controlKey(key, open) {
  if (!open && (key === 'ArrowDown' || key === 'ArrowUp')) return 'open'
  if (open && key === 'Escape') return 'close'
  return null
}

/**
 * A key inside the open popover that the picker itself left alone (its search box
 * and grid handle arrows, and Escape while there is a step to go back to).
 * 'close': Escape with nothing left to step back from. 'pick-first': Enter in a
 * search box with words in it picks the first match. 'hold': Enter in an empty
 * search box does nothing; the popover sits inside the message form, so letting
 * it through would send the message. null: not ours.
 */
export function dialogKey({ key, inSearch = false, query = '' }) {
  if (key === 'Escape') return 'close'
  if (key === 'Enter' && inSearch) return query.trim() ? 'pick-first' : 'hold'
  return null
}
