import { playHoverSound } from '../audio/sounds'
import './GalleryGrid.css'

// The picture-first grid ("Apple Photos" look): GallerySelect's popup body, and
// the inline grid of the starting-point picker (vault/picker/CostumePicker.jsx).
// It only renders: `options` (already filtered) as thumbnail cells with the name
// truncated underneath, `value` marked as picked, `onPick(value)` on a click.
//
// `plain` labels a leading no-pick cell (GallerySelect's "Vanilla", picked as
// ''); leave it out for none. An option may carry `badge` (a small tag on the
// thumbnail) or a `glyph` (a big character drawn instead of an image).
//
// `navigable` turns on the grid's own keyboard model for inline use: one tab
// stop (the picked cell, else the first), arrow keys move by cell and by row,
// Home/End, Enter/Space pick (cells are buttons), Escape calls `onEscape`. It
// also hides a thumbnail that fails to load. Off by default, so GallerySelect
// (the Tracker's watch-with-mods pickers) renders and behaves exactly as before.
export default function GalleryGrid({ options, value, onPick, plain, navigable = false, onEscape, className, label, gridRef }) {
  const picked = (o) => `${o.value}` === `${value}`
  // Roving tab stop: the picked cell, else the first. Cell 0 is the plain cell when there is one.
  const offset = plain === undefined ? 0 : 1
  const pickedAt = plain !== undefined && value === '' ? 0 : options.findIndex(picked) + offset
  const stop = pickedAt >= offset || (plain !== undefined && value === '') ? pickedAt : 0
  const tab = (index) => (navigable ? (index === stop ? 0 : -1) : undefined)
  return (
    <div
      ref={gridRef}
      className={['gallery-grid', className, navigable && 'gallery-grid--navigable'].filter(Boolean).join(' ')}
      role={navigable ? 'listbox' : undefined}
      aria-label={navigable ? label : undefined}
      onKeyDown={navigable ? (event) => galleryKeys(event, onEscape) : undefined}
    >
      {plain !== undefined && (
        <button
          type="button"
          className={`gallery-cell gallery-cell--plain ${value === '' ? 'is-selected' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={() => onPick('')}
          title={plain}
          role={navigable ? 'option' : undefined}
          aria-selected={navigable ? value === '' : undefined}
          tabIndex={tab(0)}
        >
          <span className="gallery-thumb">
            <span className="gallery-thumb--empty">{plain}</span>
          </span>
          <span className="gallery-name">{plain}</span>
        </button>
      )}

      {options.map((o, index) => (
        <button
          type="button"
          key={o.value}
          className={`gallery-cell ${picked(o) ? 'is-selected' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={() => onPick(`${o.value}`)}
          title={o.label}
          role={navigable ? 'option' : undefined}
          aria-selected={navigable ? picked(o) : undefined}
          tabIndex={tab(index + offset)}
        >
          <span className="gallery-thumb">
            {o.glyph
              ? <span className="gallery-thumb--glyph" aria-hidden="true">{o.glyph}</span>
              : o.icon
              ? <img src={o.icon} alt="" loading="lazy"
                  onError={navigable ? (event) => { event.currentTarget.style.visibility = 'hidden' } : undefined} />
              : <span className="gallery-thumb--empty">No image</span>}
            {o.badge && <span className="gallery-badge">{o.badge}</span>}
          </span>
          <span className="gallery-name">{o.label}</span>
        </button>
      ))}
    </div>
  )
}

/**
 * Keys for the search box above a navigable grid (the starting-point pickers):
 * ArrowDown moves into the grid (its tab stop, else the first cell), Escape calls
 * `onEscape` (a picker steps back).
 */
export function searchBoxKeys(event, grid, onEscape) {
  if (event.key === 'ArrowDown') {
    const cell = grid?.querySelector('.gallery-cell[tabindex="0"]') || grid?.querySelector('.gallery-cell')
    if (cell) { event.preventDefault(); cell.focus() }
  } else if (event.key === 'Escape') {
    event.preventDefault(); event.stopPropagation(); onEscape?.()
  }
}

// The cells of a navigable grid in reading order, and where they are on screen.
const cellsOf = (grid) => [...grid.querySelectorAll('.gallery-cell')]
const at = (cell) => ({ top: cell.offsetTop, left: cell.offsetLeft })

/**
 * The cell index an arrow key lands on, from where the cells are laid out:
 * left/right step in reading order, up/down go to the nearest cell (by x) of the
 * row above/below, Home/End jump to the ends. -> an index, or null when the key
 * is not a move. Pure over `{top, left}` boxes so the layout rule can be tested.
 */
export function galleryMove(key, boxes, from) {
  const last = boxes.length - 1
  if (last < 0) return null
  if (key === 'Home') return 0
  if (key === 'End') return last
  if (key === 'ArrowLeft') return Math.max(0, from - 1)
  if (key === 'ArrowRight') return Math.min(last, from + 1)
  if (key !== 'ArrowDown' && key !== 'ArrowUp') return null
  const here = boxes[from]
  const down = key === 'ArrowDown'
  const rows = boxes.map((box) => box.top).filter((top) => (down ? top > here.top + 1 : top < here.top - 1))
  if (!rows.length) return from
  const row = down ? Math.min(...rows) : Math.max(...rows)
  let best = from, distance = Infinity
  boxes.forEach((box, index) => {
    if (Math.abs(box.top - row) > 1) return
    const gap = Math.abs(box.left - here.left)
    if (gap < distance) { best = index; distance = gap }
  })
  return best
}

function galleryKeys(event, onEscape) {
  if (event.key === 'Escape') {
    if (!onEscape) return
    event.preventDefault()
    event.stopPropagation()
    onEscape()
    return
  }
  const cells = cellsOf(event.currentTarget)
  const from = cells.indexOf(document.activeElement)
  if (from < 0) return
  const next = galleryMove(event.key, cells.map(at), from)
  if (next === null) return
  event.preventDefault()
  cells[next]?.focus()
}
