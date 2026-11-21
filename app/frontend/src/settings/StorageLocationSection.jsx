import { useEffect, useState } from 'react'

function checked(result) {
  if (!result?.success) throw new Error(result?.error || 'Storage settings are unavailable.')
  return result
}

export default function StorageLocationSection() {
  const [status, setStatus] = useState(null)
  const [candidate, setCandidate] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const api = window.electron

  useEffect(() => {
    if (!api?.getStorageLocation) return
    let active = true
    api.getStorageLocation().then(checked).then(value => { if (active) setStatus(value) })
      .catch(err => { if (active) setError(err.message) })
    return () => { active = false }
  }, [api])

  if (!api?.getStorageLocation) return null

  async function perform(action) {
    setBusy(true)
    setError('')
    try { await action() } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  return (
    <section className="settings-section storage-location-section">
      <h3>Data location</h3>
      <p className="section-description">
        Choose the drive for your Vault downloads, projects, build output, extracted
        assets, local history and temporary import/build files. Browser caches and
        your application profile stay in their normal location.
      </p>
      {status && <>
        <dl className="storage-location-paths">
          <div className="storage-location-field">
            <dt>Current folder</dt>
            <dd className="iso-path-display storage-location-path">{status.currentRoot}</dd>
          </div>
          <div className="storage-location-field storage-location-temporary">
            <dt>Temporary files</dt>
            <dd className="storage-location-path">{status.scratchRoot}</dd>
          </div>
        </dl>
        {status.disabledReason && <p className="storage-location-notice" role="status">{status.disabledReason}</p>}
        {status.pending ? <div className="storage-location-plan">
          <p className="storage-location-plan-heading" role="status">
            {status.pending.phase === 'scheduled' ? 'Scheduled for your next normal launch' : 'Move needs attention'}
          </p>
          <p className="iso-path-display storage-location-path">{status.pending.target}</p>
          {status.pending.error && <p className="storage-location-error" role="alert">{status.pending.error}</p>}
          <p className="section-description">
            Finish active work, then close Nucleus when convenient.
            On your next launch, Nucleus
            copies and verifies your data before opening. Your original folder is
            kept for recovery. This setting does not restart the app.
          </p>
          <button type="button" className="iso-browse-button storage-location-button storage-location-button--secondary" disabled={busy} onClick={() => perform(async () => {
            setStatus(checked(await api.cancelStorageLocation()))
            setCandidate('')
          })}>Cancel scheduled move</button>
        </div> : <>
          <button type="button" className="iso-browse-button storage-location-button" disabled={busy || !!status.disabledReason} onClick={() => perform(async () => {
            const result = checked(await api.chooseStorageLocation())
            if (!result.canceled && result.path) {
              const separator = result.path.includes('\\') ? '\\' : '/'
              setCandidate(`${result.path.replace(/[\\/]+$/, '')}${separator}SSBM Nucleus Data`)
            }
          })}>Choose drive or parent folder…</button>
          {candidate && <div className="storage-location-plan">
            <dl className="storage-location-paths">
              <div className="storage-location-field">
                <dt>New data folder</dt>
                <dd className="iso-path-display storage-location-path">{candidate}</dd>
              </div>
            </dl>
            <p className="section-description">
              This folder must be new or empty, with enough free space for a full
              copy. Your external replay folders and ISO files stay where they are.
              Temporary files will use this drive too.
            </p>
            <button type="button" className="iso-browse-button storage-location-button" disabled={busy} onClick={() => perform(async () => {
              setStatus(checked(await api.scheduleStorageLocation(candidate)))
              setCandidate('')
            })}>Schedule move for next launch</button>
          </div>}
        </>}
      </>}
      {!status && !error && <p className="storage-location-status" role="status">Loading data location…</p>}
      {busy && <p className="storage-location-status" role="status">Checking storage…</p>}
      {error && <p className="storage-location-error" role="alert">{error}</p>}
    </section>
  )
}
