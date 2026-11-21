/**
 * errorRing - a small in-memory ring of recent renderer errors.
 *
 * Nothing in the renderer is written to disk, so UI crashes were invisible to
 * bug reports. install() (called once from main.jsx) hooks window 'error',
 * 'unhandledrejection', and console.error; snapshot() hands the ring to the
 * bug-report submit, which ships it as renderer-errors.json inside the zip.
 */

const MAX_ENTRIES = 50
const MESSAGE_MAX = 1000
const STACK_MAX = 4000

const ring = []
let installed = false

function push(message, stack) {
  ring.push({
    ts: new Date().toISOString(),
    message: String(message ?? '').slice(0, MESSAGE_MAX),
    stack: stack ? String(stack).slice(0, STACK_MAX) : null,
  })
  if (ring.length > MAX_ENTRIES) ring.shift()
}

export function install() {
  if (installed) return
  installed = true
  window.addEventListener('error', (e) => {
    push(e.message || 'window error', e.error?.stack)
  })
  window.addEventListener('unhandledrejection', (e) => {
    const reason = e.reason
    push(`unhandled rejection: ${reason?.message ?? reason}`, reason?.stack)
  })
  const original = console.error
  console.error = (...args) => {
    try {
      push(args.map((a) => (a instanceof Error ? a.message : typeof a === 'string' ? a : JSON.stringify(a))).join(' '),
        args.find((a) => a instanceof Error)?.stack)
    } catch {
      /* never let logging break logging */
    }
    original.apply(console, args)
  }
}

export function snapshot() {
  return ring.slice()
}
