/**
 * BackendStoppedScreen - covers the window when the backend process dies after
 * startup. Without it every screen fails or spins on its own, and nothing says
 * why. Restart relaunches Nucleus: the renderer has the backend's port and
 * token baked in at load, so restarting only the backend would mean reloading
 * the window anyway.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { playSound } from '../audio/sounds'
import './BackendStoppedScreen.css'

export default function BackendStoppedScreen() {
  const [exit, setExit] = useState(null)
  const [copied, setCopied] = useState(false)
  const [restarting, setRestarting] = useState(false)

  useEffect(() => {
    const bridge = window.electron
    if (!bridge?.onBackendExited) return undefined
    const cleanup = bridge.onBackendExited((info) => setExit(info || {}))
    // A window that loaded after the backend died missed the event.
    bridge.getBackendDiagnostics?.()
      .then((diag) => { if (diag?.exit) setExit(diag.exit) })
      .catch(() => {})
    return cleanup
  }, [])

  if (!exit) return null

  const copyLog = async () => {
    try {
      const diag = await window.electron.getBackendDiagnostics()
      await navigator.clipboard.writeText((diag?.output || []).join('\n'))
      setCopied(true)
    } catch { /* clipboard refused; the button stays as it was */ }
  }

  const restart = () => {
    playSound('boop')
    setRestarting(true)
    window.electron?.relaunchApp?.()
  }

  const code = exit.code ?? null
  return createPortal(
    <div className="backend-stopped-overlay" role="alertdialog" aria-labelledby="backend-stopped-title">
      <div className="backend-stopped-content">
        <h2 id="backend-stopped-title">Nucleus's backend stopped</h2>
        <p>
          The part of Nucleus that does the work closed unexpectedly
          {code !== null ? ` (exit code ${code})` : ''}. Nothing in this window can work until Nucleus restarts.
        </p>
        <div className="backend-stopped-actions">
          <button className="btn-primary" onClick={restart} disabled={restarting}>
            {restarting ? 'Restarting…' : 'Restart Nucleus'}
          </button>
          <button className="btn-secondary" onClick={copyLog}>
            {copied ? 'Log copied' : 'Copy log'}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
