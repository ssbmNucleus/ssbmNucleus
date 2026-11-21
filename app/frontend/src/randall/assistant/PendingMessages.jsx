// Ported from Ozone src/components/ChatPane.tsx: QueuedPrompts / QueuedChipMenu.
// Randall owns persistence; presentation and desktop gestures follow Ozone.
import { useEffect, useRef, useState } from 'react'
import { QueueIcon, SteerReturnIcon, TrashIcon, MoreIcon } from './QueueIcons'
import './QueuedPrompts.css'

export default function QueuedPrompts({ items: queued, running, disabled, onEdit, onRemove, onClear, onSend }) {
  const [openIds, setOpenIds] = useState(() => new Set())
  const listRef = useRef(null)
  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [queued.length])
  if (!queued.length) return null
  const toggleOpen = id => setOpenIds(previous => {
    const next = new Set(previous)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  return <div className="queued-chips" aria-label="Queued messages">
    {queued.length >= 3 && <div className="queued-chips-head">
      <span className="queued-chips-count">{queued.length} queued</span>
      <button type="button" className="queued-clear-btn" disabled={disabled} onClick={onClear} title="Remove all queued messages">Clear all</button>
    </div>}
    <div className="queued-chips-list" ref={listRef}>{queued.map((p, i) => {
      const isOpen = openIds.has(p.id)
      const isLast = i === queued.length - 1
      return <div className={`queued-chip${isOpen ? ' is-open' : ''}`} key={p.id} title={isOpen ? undefined : p.content}>
        <span className="queued-chip-lead" aria-hidden="true"><QueueIcon /></span>
        {p.context?.files?.length > 0 && <span className="queued-chip-img">?? {p.context.files.length}</span>}
        <span className={`queued-chip-text${isOpen ? ' is-open' : ''}`} role="button" tabIndex={0} aria-expanded={isOpen}
          onClick={() => toggleOpen(p.id)} onKeyDown={event => {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleOpen(p.id) }
          }}>{p.content}</span>
        <div className="queued-chip-actions">
          {isLast && <button type="button" className="queued-steer-btn" disabled={disabled} onClick={() => onSend([...queued])}
            title={queued.length > 1 ? `Send all ${queued.length} queued messages now` : undefined}>
            <SteerReturnIcon /><span>{running ? 'Send now' : 'Send'}{queued.length > 1 ? ` all ${queued.length}` : ''}</span>
          </button>}
          <button type="button" className="icon-btn queued-chip-icon" disabled={disabled} onClick={() => onRemove(p.id)} title="Remove" aria-label="Remove"><TrashIcon /></button>
          <QueuedChipMenu disabled={disabled} onEdit={() => onEdit(p)} onCopy={() => void navigator.clipboard?.writeText(p.content).catch(() => {})} />
        </div>
      </div>
    })}</div>
  </div>
}

function QueuedChipMenu({ disabled, onEdit, onCopy }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null), btnRef = useRef(null)
  const [pos, setPos] = useState(null)
  useEffect(() => {
    if (!open) return
    const onDown = event => { if (ref.current && !ref.current.contains(event.target)) setOpen(false) }
    const onKey = event => { if (event.key === 'Escape') setOpen(false) }
    const onScroll = () => setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    document.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('scroll', onScroll, true)
    }
  }, [open])
  const toggle = () => {
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setPos({ right: window.innerWidth - rect.right, bottom: window.innerHeight - rect.top + 8 })
    }
    setOpen(value => !value)
  }
  return <div className="queued-chip-more" ref={ref}>
    <button type="button" ref={btnRef} className="icon-btn queued-chip-icon" disabled={disabled} onClick={toggle} aria-haspopup="menu" aria-expanded={open} title="More" aria-label="More"><MoreIcon /></button>
    {open && <div className="chip-menu" role="menu" style={pos ? { position: 'fixed', ...pos } : undefined}>
      <button type="button" className="menu-item" role="menuitem" onClick={() => { setOpen(false); onEdit() }}><span className="menu-item-label">Edit</span></button>
      <button type="button" className="menu-item" role="menuitem" onClick={() => { setOpen(false); onCopy() }}><span className="menu-item-label">Copy</span></button>
    </div>}
  </div>
}
