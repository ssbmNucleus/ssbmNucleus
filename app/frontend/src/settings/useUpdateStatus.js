import { useState, useEffect } from 'react'

export function subscribeUpdateStatus(bridge, onStatus, now = Date.now) {
  let alive = true
  let revision = 0
  // Subscribe before requesting the snapshot, then fence its late response.
  const cleanup = bridge?.onUpdateAvailable?.((update) => {
    if (!alive) return
    revision++
    onStatus({ update: update || null, checkedAt: now(), error: null })
  })
  const requestedAtRevision = revision
  try {
    Promise.resolve(bridge?.getUpdateStatus?.()).then(status => {
      if (alive && revision === requestedAtRevision && status) onStatus(status)
    }).catch(() => {})
  } catch { /* bridge unavailable during teardown */ }
  return () => {
    alive = false
    if (typeof cleanup === 'function') cleanup()
  }
}

/**
 * useUpdateStatus - the app-wide "is a newer release waiting?" signal.
 *
 * Electron's main process checks releases.ssbmnucleus.net shortly after
 * startup and every few hours (see electron/updates/update-monitor.js); a failed check
 * retries sooner. Manual checks publish through the same status channel.
 * This hook reads the current answer on mount — covering the case where the
 * check finished before React did — and then follows update:available events.
 * Outside Electron (vite dev in a browser) it stays {update: null} forever.
 *
 * Returns {update: {version, notes, url, size}|null, checkedAt, error}.
 */
export function useUpdateStatus() {
  const [status, setStatus] = useState({ update: null, checkedAt: null, error: null })

  useEffect(() => subscribeUpdateStatus(window.electron, setStatus), [])

  return status
}
