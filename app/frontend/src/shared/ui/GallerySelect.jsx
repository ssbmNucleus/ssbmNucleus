import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { playSound, playHoverSound } from '../audio/sounds'
import GalleryGrid from './GalleryGrid'
import './GallerySelect.css'

// Picture-first picker for skins and stage mods. The thumbnail IS the information
// here -- names like "plmswh-ghirihim-white-plmsre-ghirihim-red" tell you nothing
// at a glance -- so options render as a thumbnail grid with the name truncated
// underneath (full name on hover + title), plus a search box for finding by name.
//
// The TRIGGER deliberately reuses IconSelect's `icon-select-*` classes so the
// closed row looks identical and existing button CSS keeps applying. Only the
// popup differs.
//
// The panel renders in a portal on document.body so a scrolling parent can't clip
// it -- which means CSS scoped to an ancestor in the CALLER's markup will NOT
// match it. Pass `panelClassName` to style it.
export default function GallerySelect({
  value,
  onChange,
  options,
  placeholder,
  panelClassName = '',
  aspect = 'portrait',       // 'portrait' for CSPs, 'landscape' for stage shots
  searchPlaceholder = 'Search…',
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [pos, setPos] = useState(null)
  const btnRef = useRef(null)
  const panelRef = useRef(null)
  const searchRef = useRef(null)

  const PANEL_W = aspect === 'landscape' ? 460 : 380

  const place = () => {
    const r = btnRef.current?.getBoundingClientRect()
    if (!r) return
    const belowSpace = window.innerHeight - r.bottom
    const openUp = belowSpace < 320 && r.top > belowSpace
    const width = Math.min(PANEL_W, window.innerWidth - 24)
    // Right-align to the trigger, then clamp so it can't run off either edge.
    const left = Math.max(12, Math.min(r.right - width, window.innerWidth - width - 12))
    setPos({
      left,
      width,
      top: openUp ? undefined : Math.round(r.bottom + 6),
      bottom: openUp ? Math.round(window.innerHeight - r.top + 6) : undefined,
      maxH: Math.max(220, (openUp ? r.top : belowSpace) - 16),
    })
  }

  useLayoutEffect(() => { if (open) place() }, [open])

  useEffect(() => {
    if (!open) return undefined
    setQuery('')
    const t = setTimeout(() => searchRef.current?.focus(), 0)
    return () => clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const close = (e) => {
      if (!btnRef.current?.contains(e.target) && !panelRef.current?.contains(e.target)) setOpen(false)
    }
    const esc = (e) => { if (e.key === 'Escape') { setOpen(false) } }
    // Capture phase sees the PANEL's own scroll too -- ignore that, or the grid
    // closes the moment you scroll it. Only an ancestor scrolling invalidates
    // the measured position.
    const dismiss = (e) => {
      const t = e?.target
      if (t instanceof Node && panelRef.current?.contains(t)) return
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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => `${o.label}`.toLowerCase().includes(q))
  }, [options, query])

  const pick = (v) => {
    playSound('boop')
    setOpen(false)
    onChange(v)
  }

  return (
    <div className={`icon-select gallery-select ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        ref={btnRef}
        className="icon-select-button"
        onMouseEnter={playHoverSound}
        onClick={() => setOpen((o) => !o)}
      >
        {selected?.icon && <img src={selected.icon} alt="" className="icon-select-img" />}
        <span className="icon-select-label">{selected ? selected.label : placeholder}</span>
        <span className="icon-select-caret">▾</span>
      </button>

      {open && pos && createPortal(
        <div
          ref={panelRef}
          className={`gallery-panel gallery-panel--${aspect} ${panelClassName}`}
          style={{
            position: 'fixed', left: pos.left, width: pos.width,
            top: pos.top, bottom: pos.bottom, maxHeight: pos.maxH,
          }}
        >
          <input
            ref={searchRef}
            type="text"
            className="gallery-search"
            placeholder={searchPlaceholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />

          <GalleryGrid options={filtered} value={value} onPick={pick} plain={placeholder} />

          {filtered.length === 0 && (
            <div className="gallery-empty">No skins match “{query}”</div>
          )}
        </div>, document.body)}
    </div>
  )
}
