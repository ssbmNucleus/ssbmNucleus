import { useEffect, useRef, useState } from 'react'
import { playSound, playHoverSound } from '../audio/sounds'
import './IconSelect.css'
import './FilterSelect.css'

// Custom dropdown for the text-only filters (combo length, damage, start %,
// sort), styled like IconSelect so the filter bar reads as one family.
// Besides preset options it can render typed-number rows ("At least [4] moves")
// so any value is reachable, not just the presets.
//   options:  [{ value, label }] presets
//   anyLabel: label of the clear-filter row (omit for always-set selects like sort)
//   prefix:   static text before the current label on the button ("Sort:")
//   inputs:   [{ key, before, after, encode(n)->value, decode(value)->n|null,
//               format(n)->button label }] typed rows; decode also tells the
//               button how to label a non-preset value.
export default function FilterSelect({ value, onChange, options, anyLabel, prefix, inputs = [] }) {
  const [open, setOpen] = useState(false)
  const [drafts, setDrafts] = useState({})
  const rootRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const close = (e) => { if (!rootRef.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  const selected = options.find((o) => `${o.value}` === `${value}`)
  const customInput = !selected && value !== ''
    ? inputs.find((inp) => inp.decode(value) != null) : null
  const label = selected ? selected.label
    : customInput ? customInput.format(customInput.decode(value))
      : anyLabel

  const toggle = () => {
    setOpen((o) => {
      if (!o) {
        // seed drafts from the applied value so the inputs show what's active
        const seeded = {}
        for (const inp of inputs) {
          const n = inp.decode(value)
          seeded[inp.key] = n == null || selected ? '' : `${n}`
        }
        setDrafts(seeded)
      }
      return !o
    })
  }

  const pick = (v) => {
    playSound('boop')
    setOpen(false)
    onChange(v)
  }

  const applyDraft = (inp, close) => {
    const raw = drafts[inp.key]
    const n = Number(raw)
    if (raw == null || raw === '' || !Number.isFinite(n) || n < 0) return
    const encoded = inp.encode(n)
    if (encoded !== value) {
      playSound('boop')
      onChange(encoded)
    }
    if (close) setOpen(false)
  }

  return (
    <div className={`icon-select filter-select ${open ? 'is-open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className="icon-select-button"
        onMouseEnter={playHoverSound}
        onClick={toggle}
      >
        <span className="icon-select-label">
          {prefix && <span className="filter-select-prefix">{prefix} </span>}
          {label}
        </span>
        <span className="icon-select-caret">▾</span>
      </button>
      {open && (
        <div className="icon-select-list" role="listbox">
          {anyLabel != null && (
            <button
              type="button"
              className={`icon-select-option ${value === '' ? 'is-selected' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => pick('')}
            >
              <span className="icon-select-label">{anyLabel}</span>
            </button>
          )}
          {options.map((o) => (
            <button
              type="button"
              key={o.value}
              className={`icon-select-option ${`${o.value}` === `${value}` ? 'is-selected' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => pick(`${o.value}`)}
            >
              <span className="icon-select-label">{o.label}</span>
            </button>
          ))}
          {inputs.length > 0 && <div className="filter-select-divider" />}
          {inputs.map((inp) => (
            <form
              key={inp.key}
              className={`filter-select-inputrow ${customInput?.key === inp.key ? 'is-selected' : ''}`}
              onSubmit={(e) => { e.preventDefault(); applyDraft(inp, true) }}
            >
              {inp.before && <span>{inp.before}</span>}
              <input
                type="number"
                min="0"
                inputMode="numeric"
                placeholder="…"
                value={drafts[inp.key] ?? ''}
                onChange={(e) => setDrafts((d) => ({ ...d, [inp.key]: e.target.value }))}
                onBlur={() => applyDraft(inp, false)}
              />
              {inp.after && <span>{inp.after}</span>}
            </form>
          ))}
        </div>
      )}
    </div>
  )
}
