/**
 * socket.js — the ONE Socket.IO connection to the Flask backend.
 *
 * The backend emits progress events (background jobs as `job` records, which
 * shared/jobs/ follows; capture, test-in-game, ...). Previously every
 * consumer opened its own `io(BACKEND_URL)`; now they share one connection
 * and just subscribe/unsubscribe to the events they care about.
 *
 *   import { subscribe } from './socket'
 *   useEffect(() => subscribe({
 *     job: (record) => jobStore.receive(record),
 *   }), [])
 *
 * `subscribe` returns the unsubscribe function, so it can be returned straight
 * from a `useEffect`. A `connect` handler in the map is invoked immediately
 * (async) if the shared socket is already connected, so "on connect, kick off
 * the job" patterns keep working.
 */
import { io } from 'socket.io-client'
import { BACKEND_TOKEN, BACKEND_URL } from '../config/config'

let socket = null

/** The shared socket (created lazily on first use). */
export function getSocket() {
  if (!socket) socket = io(BACKEND_URL, { auth: { token: BACKEND_TOKEN } })
  return socket
}

/**
 * Attach a map of { eventName: handler } to the shared socket.
 * @returns {() => void} unsubscribe — detaches exactly these handlers.
 */
export function subscribe(handlers) {
  const s = getSocket()
  const entries = Object.entries(handlers).filter(([, fn]) => typeof fn === 'function')
  for (const [event, fn] of entries) s.on(event, fn)
  if (typeof handlers.connect === 'function' && s.connected) {
    queueMicrotask(() => handlers.connect())
  }
  return () => {
    for (const [event, fn] of entries) s.off(event, fn)
  }
}

/** Emit on the shared socket. */
export function emit(event, payload) {
  getSocket().emit(event, payload)
}

/**
 * A scoped view of the shared socket with the classic `socket` surface
 * (`on`, `off`, `emit`, `disconnect`, `connected`) — drop-in for code that used
 * to call `io(BACKEND_URL)` and `socket.disconnect()` in its cleanup.
 * `disconnect()` detaches only the handlers registered through this channel;
 * the underlying connection stays up for everyone else.
 */
export function channel() {
  const s = getSocket()
  const bound = []
  const ch = {
    on(event, fn) {
      s.on(event, fn)
      bound.push([event, fn])
      if (event === 'connect' && s.connected) queueMicrotask(() => fn())
      return ch
    },
    off(event, fn) {
      s.off(event, fn)
      const i = bound.findIndex(([e, f]) => e === event && f === fn)
      if (i >= 0) bound.splice(i, 1)
      return ch
    },
    emit(event, payload) { s.emit(event, payload); return ch },
    get connected() { return s.connected },
    disconnect() {
      for (const [event, fn] of bound) s.off(event, fn)
      bound.length = 0
    },
  }
  return ch
}
