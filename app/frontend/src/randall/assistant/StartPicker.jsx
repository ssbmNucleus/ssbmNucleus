import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import CostumePicker from '../../vault/picker/CostumePicker'
import StagePicker from '../../vault/picker/StagePicker'
import { pickText } from './startPick'
import { controlKey, dialogKey, popoverPlacement } from './pickPopover'
import { backendMediaUrl } from '../../shared/config/config'

// The empty chat's starting point for a task that names a `picker` (status.tasks),
// as a control in the composer's control row, beside the task pill: "Retexture a
// costume" picks a fighter, then a costume; "Import a character model" picks the
// fighter the model goes on; "Retexture a stage" picks a stage, then a vault
// variant or the stock stage. Optional: typing the costume, fighter or stage in
// words still works, and nothing here blocks sending.

const NOUN = { costume: 'costume', fighter: 'fighter', stage: 'stage' }

const PictureIcon = () => <svg className="randall-pick-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><circle cx="9" cy="10" r="1.6" /><path d="m20.5 16-4.6-4.6L7 19.5" /></svg>

/**
 * "Choose costume" (or fighter, stage) until something is picked, then the pick's
 * thumbnail and name with × to clear it. The button opens the picker
 * (vault/picker/CostumePicker or StagePicker, unchanged) in a popover anchored to
 * the composer box: a non-modal dialog that opens above or below the box,
 * whichever side has the room (pickPopover.popoverPlacement), as wide as the box
 * up to 520px. It closes on a pick, on Escape once the picker has no step left to
 * go back to, on a press outside it, or when focus leaves it; a close that is not
 * a pick returns focus to the button. The pick itself goes to `onPick`; the panel
 * keeps it (startPick.js says what it sends).
 */
export function StartPickControl({ picker, pick, disabled, metadata, fighters, stages, onPick, onClear }) {
  const [open, setOpen] = useState(false)
  const [place, setPlace] = useState(null)
  const wrap = useRef(null), button = useRef(null), dialog = useRef(null)
  const dialogId = useId()
  useEffect(() => { setOpen(false) }, [picker])
  useEffect(() => { if (disabled) setOpen(false) }, [disabled])
  // Measured before paint, then again when the window changes size: the box it
  // anchors to, inside the chat page (the window when there is none).
  useLayoutEffect(() => {
    if (!open) return undefined
    const measure = () => {
      const box = wrap.current?.closest('.ozone-composer') || wrap.current
      if (!box) return
      const anchor = box.getBoundingClientRect()
      const page = wrap.current.closest('.coach-page')?.getBoundingClientRect() || { top: 0, bottom: window.innerHeight }
      setPlace(popoverPlacement({ anchorTop: anchor.top, anchorBottom: anchor.bottom,
        boundsTop: page.top, boundsBottom: page.bottom, viewportHeight: window.innerHeight }))
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [open])
  // GallerySelect's outside press: anything outside the control and its popover closes it.
  useEffect(() => {
    if (!open) return undefined
    const outside = event => { if (!wrap.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('mousedown', outside)
    return () => document.removeEventListener('mousedown', outside)
  }, [open])
  if (!picker) return null

  const noun = NOUN[picker] || 'pick'
  const label = pick ? pickText(pick) : ''
  const close = () => { setOpen(false); button.current?.focus() }
  const choose = next => { setOpen(false); onPick(next) }
  const keys = event => {
    const inDialog = Boolean(dialog.current?.contains(event.target))
    const action = inDialog
      ? dialogKey({ key: event.key, inSearch: Boolean(event.target.matches?.('input.gallery-search')), query: event.target.value || '' })
      : controlKey(event.key, open)
    if (!action) return
    event.preventDefault()
    if (action === 'open') setOpen(true)
    else if (action === 'close') { event.stopPropagation(); close() }
    else if (action === 'pick-first') dialog.current?.querySelector('.gallery-cell')?.click()
  }
  // Focus moving to something outside closes it. A null target is a picker step
  // swapping its cells (it puts focus back in its search box), not a move away.
  const blur = event => {
    if (open && event.relatedTarget && !wrap.current?.contains(event.relatedTarget)) setOpen(false)
  }
  const thumb = pick?.auto
    ? <span className="randall-pick-thumb randall-pick-thumb--fighter randall-pick-thumb--glyph" aria-hidden="true">?</span>
    : pick?.image
    ? <img src={backendMediaUrl(pick.image)} alt="" className={`randall-pick-thumb randall-pick-thumb--${pick.kind}`}
      onError={event => { event.currentTarget.style.visibility = 'hidden' }} />
    : <PictureIcon />
  return <div className="randall-pick" ref={wrap} onKeyDown={keys} onBlur={blur}>
    <div className={`randall-pick-chip${pick ? ' is-picked' : ''}`}>
      <button ref={button} type="button" className="randall-pick-open" disabled={disabled}
        aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? dialogId : undefined}
        aria-label={pick ? `${noun[0].toUpperCase()}${noun.slice(1)}: ${label}. Change` : undefined}
        title={pick ? `Change the ${noun}` : `Pick the ${noun} to start from (optional)`}
        onClick={() => setOpen(was => !was)}>
        {thumb}<span>{pick ? label : `Choose ${noun}`}</span>
      </button>
      {pick && <button type="button" className="randall-pick-clear" disabled={disabled}
        aria-label={`Clear the ${noun}`} title={`Clear the ${noun}`}
        onClick={() => { setOpen(false); onClear(); button.current?.focus() }}>
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" /></svg>
      </button>}
    </div>
    {open && <div ref={dialog} id={dialogId} role="dialog" aria-label={`Choose a ${noun}`}
      className={`randall-pick-popover ${place && !place.up ? 'is-down' : 'is-up'}`}
      style={place ? { maxHeight: place.maxHeight } : undefined}>
      {picker === 'stage'
        ? <StagePicker stages={stages} value={pick} onChange={choose} onCancel={close} autoFocus />
        : <CostumePicker mode={picker} metadata={metadata} fighters={fighters} value={pick}
          onChange={choose} onCancel={close} autoFocus />}
    </div>}
  </div>
}
