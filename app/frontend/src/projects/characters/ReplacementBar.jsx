/**
 * ReplacementBar - header strip for the "Available to Import" list while a
 * vanilla costume is being replaced.
 *
 * Picking a replacement happens by CLICKING a card in the list that is already
 * on screen (see CostumesPanel / ZeldaSheikPanel), so this is a header strip,
 * NOT a modal - nothing covers or greys out the page.
 */
import './ReplacementBar.css'

const SLOT_COLORS = {
  Nr: { label: 'Normal', background: '#64748b', foreground: '#fff' },
  Re: { label: 'Red', background: '#b83240', foreground: '#fff' },
  Bu: { label: 'Blue', background: '#285db5', foreground: '#fff' },
  Gr: { label: 'Green', background: '#267445', foreground: '#fff' },
  Ye: { label: 'Yellow', background: '#ebca55', foreground: '#251e08' },
  Bk: { label: 'Black', background: '#252832', foreground: '#fff' },
  Wh: { label: 'White', background: '#edf0f5', foreground: '#252832' },
  Pi: { label: 'Pink', background: '#ef9bc2', foreground: '#361626' },
  Or: { label: 'Orange', background: '#ed9b49', foreground: '#321e09' },
  La: { label: 'Purple', background: '#7750ad', foreground: '#fff' },
  Aq: { label: 'Aqua', background: '#75d5d7', foreground: '#143638' },
  Gy: { label: 'Gray', background: '#737982', foreground: '#fff' },
}

const slotColorFor = (replacement) => {
  const slotCode = replacement.target?.color || replacement.costume?.vanillaTarget?.color
  const namedColor = Object.values(SLOT_COLORS)
    .find(color => color.label.toLowerCase() === replacement.costume?.name?.toLowerCase())
  // G&W's vanilla colors share the same Nr DAT; their names distinguish them.
  return (replacement.fighter === 'Mr. Game & Watch' && namedColor)
    || SLOT_COLORS[slotCode] || namedColor || SLOT_COLORS.Nr
}

export default function ReplacementBar({ cm }) {
  const { replacement, replacementBusy, replacementError, cancelReplacement } = cm
  const slotColor = slotColorFor(replacement)
  const status = replacementError ? replacementError
    : replacementBusy ? 'Converting and replacing costume…'
    : !replacement.version ? 'Checking destination…'
    : `Click a ${replacement.fighter} costume below to replace it`
  return (
    <>
      <h3 className="replacement-heading">
        <span>Replacing</span>
        <span className="replacement-color-pill" style={{ backgroundColor: slotColor.background, color: slotColor.foreground }}>
          {slotColor.label}
        </span>
        <span className={`replacement-hint ${replacementError ? 'replacement-error' : ''}`}
          role={replacementError ? 'alert' : 'status'}>
          {status}
        </span>
      </h3>
      <div className="batch-controls">
        <button type="button" className="btn-clear-selection" onClick={cancelReplacement} disabled={replacementBusy}>
          Cancel
        </button>
      </div>
    </>
  )
}
