import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { playSound, playHoverSound } from '../audio/sounds'
import './IconSelect.css'

// Native <select> can't render images, so filter dropdowns that want stock /
// stage icons use this tiny listbox instead. options: [{ value, label,
// count, icon }] — icon is an <img> src (optional per option).
// The open list renders in a portal (fixed position) so a scrolling parent
// (e.g. the Watch playlist skin picker) can't clip it.
// `listClassName` is REQUIRED for any caller that wants to restyle the open list:
// it renders in a portal on document.body, so selectors scoped to an ancestor in
// the caller's own markup (e.g. `.watchmods-player .icon-select-img`) do NOT match.
export default function IconSelect({ value, onChange, options, placeholder, icon: placeholderIcon, listClassName = '', disabled = false }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)
  const btnRef = useRef(null)
  const listRef = useRef(null)
  useEffect(() => { if (disabled) setOpen(false) }, [disabled])

  const place = () => {
    const r = btnRef.current?.getBoundingClientRect()
    if (!r) return
    const belowSpace = window.innerHeight - r.bottom
    const openUp = belowSpace < 260 && r.top > belowSpace
    setPos({
      left: r.left, width: r.width,
      top: openUp ? undefined : Math.round(r.bottom + 6),
      bottom: openUp ? Math.round(window.innerHeight - r.top + 6) : undefined,
      maxH: Math.max(140, (openUp ? r.top : belowSpace) - 16),
    })
  }

  useLayoutEffect(() => { if (open) place() }, [open])

  useEffect(() => {
    if (!open) return undefined
    const close = (e) => {
      if (!btnRef.current?.contains(e.target) && !listRef.current?.contains(e.target)) setOpen(false)
    }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    // Reposition is fiddly across scroll containers, so an ANCESTOR scrolling just
    // closes the list. But this is a capture-phase listener, so it also sees the
    // list's OWN scroll — ignore that, or the menu shuts the moment you scroll it.
    const dismiss = (e) => {
      const t = e?.target
      if (t instanceof Node && listRef.current?.contains(t)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    window.addEventListener('scroll', dismiss, true)
    window.addEventListener('resize', dismiss)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
      window.removeEventListener('scroll', dismiss, true)
      window.removeEventListener('resize', dismiss)
    }
  }, [open])

  const selected = options.find((o) => `${o.value}` === `${value}`)

  const pick = (v) => {
    if (disabled) return
    playSound('boop')
    setOpen(false)
    onChange(v)
  }

  return (
    <div className={`icon-select ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        ref={btnRef}
        className="icon-select-button"
        disabled={disabled}
        onMouseEnter={playHoverSound}
        onClick={() => setOpen((o) => !o)}
      >
        {selected?.icon && <img src={selected.icon} alt="" className="icon-select-img" />}
        <span className="icon-select-label">{selected ? selected.label : placeholder}</span>
        <span className="icon-select-caret">▾</span>
      </button>
      {open && pos && createPortal(
        <div
          className={`icon-select-list icon-select-list--portal ${listClassName}`}
          role="listbox"
          ref={listRef}
          style={{
            position: 'fixed', left: pos.left, minWidth: pos.width, right: 'auto',
            top: pos.top, bottom: pos.bottom, maxHeight: pos.maxH,
          }}
        >
          <button
            type="button"
            className={`icon-select-option ${value === '' ? 'is-selected' : ''}`}
            onClick={() => pick('')}
          >
            {placeholderIcon && <span className="icon-select-img icon-select-img--spacer" />}
            <span className="icon-select-label">{placeholder}</span>
          </button>
          {options.map((o) => (
            <button
              type="button"
              key={o.value}
              className={`icon-select-option ${`${o.value}` === `${value}` ? 'is-selected' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => pick(`${o.value}`)}
            >
              {o.icon && <img src={o.icon} alt="" className="icon-select-img" loading="lazy" />}
              <span className="icon-select-label">{o.label}</span>
              {o.count != null && <span className="icon-select-count">{o.count.toLocaleString()}</span>}
            </button>
          ))}
        </div>, document.body)}
    </div>
  )
}
