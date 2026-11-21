// One clock for everything that says how long Randall has been at it: the import card and the status bar below the
// chat read the same second from one shared tick, so side by side they never disagree ("2.5 min" beside "2 min 55
// sec" was two clocks: one counted from the last progress event, the other from the turn's start, every 5 s).
import { useEffect, useState } from 'react'

const TICK_MS = 1000
const listeners = new Set()
let timer = null
let last = null   // the newest tick, while the clock runs

/** Calls `listener(now)` on the shared one-second tick until the returned function is called. */
export function onTick(listener) {
  listeners.add(listener)
  if (!timer) {
    timer = setInterval(() => {
      const now = Date.now()
      last = now
      for (const each of listeners) each(now)
    }, TICK_MS)
  }
  return () => {
    listeners.delete(listener)
    if (!listeners.size && timer) { clearInterval(timer); timer = null; last = null }
  }
}

/** The current time in ms, ticking once a second while `active`; every caller gets the same tick. */
export function useNow(active = true) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    if (!active) return undefined
    // A clock that joins a running tick shows that tick, so it never reads a second apart from the others.
    setNow(timer && last ? last : Date.now())
    return onTick(setNow)
  }, [active])
  return now
}
