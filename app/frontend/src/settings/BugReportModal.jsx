/**
 * BugReportModal - describe a bug, logs attach themselves.
 *
 * The backend bundles app logs, optional Slippi Dolphin logs and diagnostics
 * with usernames/tokens redacted, then uploads them privately to the bugreport worker — R2 storage +
 * a ping in the developer's private Discord channel. Nothing public.
 *
 * "Update first" gate: when a newer release is known (background check) the
 * form is replaced by an update prompt — the worker enforces the same rule
 * server-side (HTTP 426), so stale clients can't file already-fixed bugs.
 */
import { useEffect, useRef, useState } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { api, ApiError } from '../shared/transport/api'
import { useUpdateStatus } from './useUpdateStatus'
import { snapshot as errorRingSnapshot } from '../shared/lib/errorRing'
import '../shared/ui/CreditsModalChrome.css'

export default function BugReportModal({ show, onClose }) {
  const [description, setDescription] = useState('')
  const [contact, setContact] = useState('')
  const [includeSlippi, setIncludeSlippi] = useState(true)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)   // {id} on success
  const [error, setError] = useState(null)     // string
  const [gate, setGate] = useState(null)       // {latest, url} from a 426
  const [downloading, setDownloading] = useState(false)
  const [progress, setProgress] = useState(0)
  const cleanupRef = useRef(null)

  const { update } = useUpdateStatus()
  const slippiPath = localStorage.getItem('slippi_dolphin_path') || ''
  // Known update from the background check, or one the server told us about.
  const pendingUpdate = update || gate

  useEffect(() => {
    if (!show) return undefined
    const onKey = (e) => { if (e.key === 'Escape' && !sending) { playSound('back'); onClose() } }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [show, onClose, sending])

  useEffect(() => () => { if (cleanupRef.current) cleanupRef.current() }, [])

  if (!show) return null

  const handleSend = async () => {
    if (!description.trim() || sending) return
    setSending(true)
    setError(null)
    try {
      let electron = null
      try {
        if (window.electron?.getElectronDiagnostics) {
          electron = await window.electron.getElectronDiagnostics()
        }
        if (window.electron?.getBackendDiagnostics) {
          const backend = await window.electron.getBackendDiagnostics()
          electron = { ...(electron || {}), backend }
        }
      } catch { /* diagnostics are best-effort */ }
      const appVersion = await window.electron?.getAppVersion?.().catch(() => null)
      const data = await api.post('/bugreport', {
        description: description.trim(),
        contact: contact.trim(),
        slippiPath: includeSlippi ? slippiPath : '',
        app_version: appVersion || undefined,
        electron,
        renderer_errors: errorRingSnapshot(),
      })
      playSound('start')
      setResult({ id: data.id })
    } catch (err) {
      if (err instanceof ApiError && err.status === 426) {
        setGate({ latest: err.data?.latest, url: err.data?.url })
      } else if (err instanceof ApiError && err.status === 429) {
        setError('Too many reports right now — please try again in a minute.')
      } else if (err instanceof ApiError && err.status === 0) {
        setError('No connection — check your internet and try again.')
      } else {
        setError(err.message || 'Sending failed')
      }
    } finally {
      setSending(false)
    }
  }

  const handleInstall = async () => {
    if (!window.electron?.installUpdate) return
    setDownloading(true)
    setError(null)
    setProgress(0)
    cleanupRef.current = window.electron.onUpdateProgress?.(({ received, total }) => {
      setProgress(total > 0 ? Math.round((received / total) * 100) : 0)
    })
    try {
      const res = await window.electron.installUpdate()
      if (!res.success) {
        setError(res.error || 'Update failed')
        setDownloading(false)
      }
      // On success the installer launches and the app quits on its own.
    } catch (err) {
      setError(err.message)
      setDownloading(false)
    } finally {
      if (cleanupRef.current) { cleanupRef.current(); cleanupRef.current = null }
    }
  }

  const close = () => { if (!sending) { playSound('back'); onClose() } }

  return (
    <div className="credits-overlay" onClick={close}>
      <div className="credits-modal bugreport-modal" onClick={(e) => e.stopPropagation()}>
        <h2 className="credits-modal-title">Report a Bug</h2>

        {pendingUpdate ? (
          <div className="bugreport-gate">
            <p className="credits-modal-sub">
              A newer version{pendingUpdate.version || pendingUpdate.latest
                ? ` (v${pendingUpdate.version || pendingUpdate.latest})` : ''} is
              available. Updating is always step one — your bug may already be
              fixed. Report again if it survives the update.
            </p>
            {window.electron?.installUpdate && update ? (
              <button
                className="restore-button update-install-button"
                disabled={downloading}
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('start'); handleInstall() }}
              >
                {downloading ? `Downloading... ${progress}%` : `Update to v${update.version}`}
              </button>
            ) : (
              <p className="setup-section-note">
                Use Settings → Updates to install the new version, then come back.
              </p>
            )}
            {error && <p className="update-status-error">{error}</p>}
          </div>
        ) : result ? (
          <div className="bugreport-done">
            <p className="credits-modal-sub">
              Report sent — thank you! The logs went along with it, so there is
              nothing else to attach.
            </p>
            <p className="bugreport-id">Reference: {result.id.slice(0, 8)}</p>
          </div>
        ) : (
          <>
            <p className="credits-modal-sub">
              What happened, and what were you doing when it happened? Your app
              logs are attached automatically (usernames and tokens are removed)
              and go privately to the developer. Kept 90 days.
            </p>
            <textarea
              className="bugreport-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={'e.g. Installing a Falco skin crashed on "Building ISO" — repro: import the zip, pick slot 3, click Install.'}
              rows={6}
              maxLength={4000}
              disabled={sending}
              autoFocus
            />
            <input
              className="bugreport-contact"
              type="text"
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              placeholder="How can we reach you? Discord or email (optional)"
              maxLength={200}
              disabled={sending}
            />
            {slippiPath && (
              <label className="bugreport-slippi">
                <input
                  type="checkbox"
                  checked={includeSlippi}
                  onChange={(e) => setIncludeSlippi(e.target.checked)}
                  disabled={sending}
                />
                Include Slippi Dolphin logs (for in-game crashes)
              </label>
            )}
            {error && <p className="update-status-error">{error}</p>}
          </>
        )}

        <div className="credits-modal-buttons">
          {!pendingUpdate && !result && (
            <button
              className="restore-button"
              disabled={sending || !description.trim()}
              onMouseEnter={playHoverSound}
              onClick={handleSend}
            >
              {sending ? 'Sending...' : 'Send Report'}
            </button>
          )}
          <button
            className="credits-close-button"
            disabled={sending}
            onMouseEnter={playHoverSound}
            onClick={close}
          >
            {result ? 'Done' : 'Close'}
          </button>
        </div>
      </div>
    </div>
  )
}
