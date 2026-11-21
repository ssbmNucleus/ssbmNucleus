/**
 * UpdateSection - Check for and install app updates from releases.ssbmnucleus.net
 */
import { useState, useEffect } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { useUpdateStatus } from './useUpdateStatus'
import HexagonLoader from '../shared/ui/HexagonLoader'

export default function UpdateSection() {
  const [currentVersion, setCurrentVersion] = useState('')
  const [checking, setChecking] = useState(false)
  const [update, setUpdate] = useState(null)
  // The background check (electron main) may already know about a release —
  // show it without making the user click Check.
  const { update: backgroundUpdate, checkedAt, error: backgroundError } = useUpdateStatus()
  const [upToDate, setUpToDate] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState(null)

  useEffect(() => {
    // A successful null result clears stale availability. Never replace the
    // selected update while its installer is downloading, or treat an unchecked
    // snapshot/network failure as confirmation that this version is current.
    if (downloading || checkedAt == null || backgroundError) return
    setUpdate(backgroundUpdate)
    setUpToDate(!backgroundUpdate)
  }, [backgroundUpdate, checkedAt, backgroundError, downloading])

  const isElectron = Boolean(window.electron?.checkForUpdate)

  useEffect(() => {
    const bridge = window.electron
    if (bridge?.getAppVersion) {
      bridge.getAppVersion().then(setCurrentVersion).catch(() => {})
    }
    // The download belongs to main, so this card follows it whichever card
    // started it: leaving Settings mid-download and coming back shows it still
    // running instead of offering a second install.
    const percent = ({ received, total }) => (total > 0 ? Math.round((received / total) * 100) : 0)
    const offProgress = bridge?.onUpdateProgress?.((data) => setProgress(percent(data)))
    const offDone = bridge?.onUpdateInstallDone?.(({ success, error: message }) => {
      // On success the installer launches and the app quits on its own.
      if (success) return
      setError(message || 'Update failed')
      setDownloading(false)
    })
    bridge?.getUpdateInstallStatus?.().then((install) => {
      if (!install?.installing) return
      setDownloading(true)
      setProgress(percent(install))
    }).catch(() => {})
    return () => {
      offProgress?.()
      offDone?.()
    }
  }, [])

  const handleCheck = async () => {
    setChecking(true)
    setError(null)
    setUpToDate(false)
    try {
      const result = await window.electron.checkForUpdate()
      if (!result.success) {
        setError(result.error || 'Update check failed')
      } else if (result.update) {
        setUpdate(result.update)
      } else {
        setUpdate(null)
        setUpToDate(true)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setChecking(false)
    }
  }

  const handleInstall = async () => {
    setDownloading(true)
    setError(null)
    setProgress(0)
    try {
      const result = await window.electron.installUpdate()
      if (!result.success) {
        setError(result.error || 'Update failed')
        setDownloading(false)
      }
      // On success the installer launches and the app quits on its own.
    } catch (err) {
      setError(err.message)
      setDownloading(false)
    }
  }

  if (!isElectron) {
    return null
  }

  // One hexagon, one spot, every state: static outline when idle/up to date,
  // the indeterminate trace while checking or an update waits, and the real
  // download percentage while installing.
  const hexProgress = downloading ? progress : (checking || update) ? null : 100

  return (
    <section className="settings-section">
      <div className="update-header">
        <div className="update-header-copy">
          <h3>Updates</h3>
          <p className="section-description">
            Current version: <strong>{currentVersion ? `v${currentVersion}` : '...'}</strong>
          </p>
        </div>
        <HexagonLoader size={48} decorative className="update-hex" progress={hexProgress} />
      </div>

      {update ? (
        <div className="update-available">
          <div className="update-available-copy">
            <p className="update-available-kicker">Update detected</p>
            <p className="update-available-version">v{update.version} is available</p>
          </div>
          {update.notes && <p className="update-notes">{update.notes}</p>}
          <button
            className="restore-button update-install-button"
            disabled={downloading}
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('start'); handleInstall(); }}
          >
            {downloading ? `Downloading... ${progress}%` : `Update to v${update.version}`}
          </button>
          {downloading && (
            <div className="update-progress-track">
              <div className="update-progress-fill" style={{ width: `${progress}%` }} />
            </div>
          )}
          <p className="setup-section-note">
            The installer will open after the download finishes and the app will close.
          </p>
        </div>
      ) : (
        <button
          className="restore-button"
          disabled={checking}
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); handleCheck(); }}
        >
          {checking ? 'Checking...' : 'Check for Updates'}
        </button>
      )}

      {upToDate && !update && (
        <p className="update-status-ok">You&apos;re up to date.</p>
      )}
      {error && (
        <p className="update-status-error">Update failed: {error}</p>
      )}
    </section>
  )
}
