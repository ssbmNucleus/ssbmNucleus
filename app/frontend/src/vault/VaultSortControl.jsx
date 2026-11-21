/**
 * VaultSortControl - single "Sort" button that opens a dropdown menu, for the
 * vault skin/stage detail views.
 *
 * CombosPage sort pattern: picking a new sort selects it at its natural
 * direction; picking the active sort again flips direction. "Custom" is the
 * stored drag-reorder order (no direction arrow).
 */
import { useEffect, useRef, useState } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { useClickOutside } from '../shared/hooks/useClickOutside'
import './VaultSortControl.css'

const arrow = (sort) => (sort.dir === 'asc' ? '↑' : '↓')

export default function VaultSortControl({ sorts, sort, onChange }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)

  useClickOutside(rootRef, open, () => setOpen(false))

  useEffect(() => {
    if (!open) return undefined
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [open])

  const active = sorts.find((s) => s.value === sort.key) || sorts[0]
  const isCustom = active.value === 'custom'

  const choose = (value, defDir) => {
    playSound('boop')
    setOpen(false)
    if (sort.key === value && value !== 'custom') {
      onChange({ key: value, dir: sort.dir === 'asc' ? 'desc' : 'asc' })
    } else {
      onChange({ key: value, dir: defDir })
    }
  }

  return (
    <div className={`vault-sort ${open ? 'is-open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className={`vault-sort-btn ${isCustom ? '' : 'active'}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('boop'); setOpen((o) => !o); }}
        title="Change how the cards are ordered"
      >
        <span className="vault-sort-label">Sort:</span>
        {active.label}
        {!isCustom && <span className="vault-sort-arrow">{arrow(sort)}</span>}
        <span className="vault-sort-caret">▾</span>
      </button>
      {open && (
        <div className="vault-sort-menu" role="listbox" aria-label="Sort by">
          {sorts.map(({ value, label, defDir }) => {
            const selected = sort.key === value
            return (
              <button
                type="button"
                key={value}
                role="option"
                aria-selected={selected}
                className={`vault-sort-option ${selected ? 'is-selected' : ''}`}
                onMouseEnter={playHoverSound}
                onClick={() => choose(value, defDir)}
                title={value === 'custom'
                  ? 'Your own order — drag cards to rearrange'
                  : selected
                    ? `Flip to ${sort.dir === 'asc' ? 'descending' : 'ascending'}`
                    : `Sort by ${label}`}
              >
                {label}
                {selected && value !== 'custom' && (
                  <span className="vault-sort-arrow">{arrow(sort)}</span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
