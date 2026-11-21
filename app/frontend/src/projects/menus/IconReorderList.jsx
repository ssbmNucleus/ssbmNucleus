import { Fragment, useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import './LayoutEditor.css'

/**
 * IconReorderList - the icon list in the CSS/SSS layout editor right panel.
 *
 * Rows show a thumbnail + label, support standard click selection
 * (plain = select one, ctrl/cmd-click = toggle, shift-click = range from the
 * anchor), right-click for the properties popup, and drag-and-drop reordering
 * (identity moves between slots; the editors re-zip the slot layout fields).
 *
 * When several rows are shift-selected and one of them is dragged, the whole
 * selected block moves together (bulk reorder) via onReorderBulk.
 *
 * Optional extras (the CSS editor's L alternates use them): `renderRowAction`
 * adds a control at the right end of a row, `renderAfterRow` adds content
 * under it. Both are outside drag-and-drop; they stop their own clicks.
 */
export default function IconReorderList({
  icons,
  selectedIndices,
  onSelect,          // (indices: number[]) => void
  onContextMenu,     // (x, y) => void
  onReorder,         // (from, to) => void
  onReorderBulk,     // (indices: number[], to) => void  (optional)
  getLabel,          // (icon, idx) => string
  getIconUrl,        // (icon) => string | null
  renderRowAction,   // (icon, idx) => node   (optional)
  renderAfterRow     // (icon, idx) => node   (optional)
}) {
  const [dragIdx, setDragIdx] = useState(null)
  const [overIdx, setOverIdx] = useState(null)
  // Anchor row for shift-click range selection (the last row clicked without
  // shift). Defaults to the current primary selection so the first shift-click
  // has something to range from.
  const [anchorIdx, setAnchorIdx] = useState(null)

  const handleClick = (e, idx) => {
    playSound('boop')
    const ctrl = e.ctrlKey || e.metaKey
    if (e.shiftKey) {
      // Range select from the anchor to the clicked row.
      const from = anchorIdx ?? (selectedIndices.length ? selectedIndices[0] : idx)
      const lo = Math.min(from, idx)
      const hi = Math.max(from, idx)
      const range = []
      for (let i = lo; i <= hi; i++) range.push(i)
      if (ctrl) {
        // Ctrl+Shift: add the range to the existing selection.
        const s = new Set(selectedIndices)
        range.forEach(i => s.add(i))
        onSelect([...s])
      } else {
        onSelect(range)
      }
      // The anchor stays put across shift-clicks (standard behavior).
    } else if (ctrl) {
      // Toggle this row in/out of the selection.
      const s = new Set(selectedIndices)
      if (s.has(idx)) s.delete(idx); else s.add(idx)
      onSelect([...s])
      setAnchorIdx(idx)
    } else {
      onSelect([idx])
      setAnchorIdx(idx)
    }
  }

  const handleContextMenu = (e, idx) => {
    e.preventDefault()
    if (!selectedIndices.includes(idx)) onSelect([idx])
    onContextMenu(e.clientX, e.clientY)
  }

  const endDrag = () => {
    setDragIdx(null)
    setOverIdx(null)
  }

  // A bulk drag carries every selected row when one of them is the grabbed row.
  const bulkDrag = dragIdx !== null && selectedIndices.length > 1 && selectedIndices.includes(dragIdx)
  const draggingSet = bulkDrag ? new Set(selectedIndices) : new Set([dragIdx])

  const handleDrop = (e, idx) => {
    e.preventDefault()
    if (dragIdx === null) { endDrag(); return }
    if (bulkDrag && onReorderBulk) {
      if (!selectedIndices.includes(idx)) {
        playSound('tick')
        onReorderBulk(selectedIndices, idx)
      }
    } else if (dragIdx !== idx) {
      playSound('tick')
      onReorder(dragIdx, idx)
    }
    endDrag()
  }

  return (
    <div className="sss-icon-list">
      {icons.map((icon, idx) => {
        const iconUrl = getIconUrl ? getIconUrl(icon) : null
        // No drop indicator on the rows being carried (the grabbed block)
        const isDragTarget = dragIdx !== null && overIdx === idx && !draggingSet.has(idx)
        const dropClass = isDragTarget ? (dragIdx < idx ? 'drop-after' : 'drop-before') : ''

        return (
          <Fragment key={idx}>
          <div
            className={`sss-icon-item ${selectedIndices.includes(idx) ? 'selected' : ''} ${draggingSet.has(idx) ? 'dragging' : ''} ${dropClass}`}
            onClick={(e) => handleClick(e, idx)}
            onContextMenu={(e) => handleContextMenu(e, idx)}
            draggable
            onDragStart={(e) => {
              setDragIdx(idx)
              e.dataTransfer.effectAllowed = 'move'
              // Required for Firefox to start the drag
              e.dataTransfer.setData('text/plain', String(idx))
            }}
            onDragOver={(e) => {
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
              if (overIdx !== idx) setOverIdx(idx)
            }}
            onDrop={(e) => handleDrop(e, idx)}
            onDragEnd={endDrag}
          >
            <span className="sss-icon-idx">{idx}</span>
            <span className="sss-icon-thumb">
              {iconUrl ? (
                <img src={iconUrl} alt="" draggable={false} onError={(e) => { e.target.style.display = 'none' }} />
              ) : (
                <span className="sss-icon-thumb-empty">?</span>
              )}
            </span>
            <span className="sss-icon-name">{getLabel(icon, idx)}</span>
            {renderRowAction && <span style={{ marginLeft: 'auto' }}>{renderRowAction(icon, idx)}</span>}
          </div>
          {renderAfterRow && renderAfterRow(icon, idx)}
          </Fragment>
        )
      })}
    </div>
  )
}
