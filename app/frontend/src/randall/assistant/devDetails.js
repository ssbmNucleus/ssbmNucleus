// "Developer details": whether Randall's cards show how each step was decided (who decided it, the questions
// asked twice in two orders, measured values, the pictures each decision looked at) or only what a person needs
// (what is happening now, the result, the choices they can change). Off by default; a per-machine preference.
import { useEffect, useState } from 'react'

const KEY = 'nucleus.randall.devDetails'
const EVENT = 'nucleus:randall-dev-details'

export function readDevDetails() {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}

export function setDevDetails(on) {
  try { localStorage.setItem(KEY, on ? '1' : '0') } catch { /* storage unavailable: this session only */ }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: Boolean(on) }))
}

/** The current setting, kept in step with every other card and the settings panel. */
export function useDevDetails() {
  const [on, setOn] = useState(readDevDetails)
  useEffect(() => {
    const changed = event => setOn(typeof event?.detail === 'boolean' ? event.detail : readDevDetails())
    window.addEventListener(EVENT, changed)
    return () => window.removeEventListener(EVENT, changed)
  }, [])
  return on
}
