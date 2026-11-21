/**
 * BackupRestore - Vault backup and restore functionality
 *
 * Features:
 * - Export vault as a backup .zip, saved where a save dialog picks (a download outside the app)
 * - Import vault from backup
 * - Replace or merge modes for restore
 * - Live restore progress: upload % (XHR), then the restore job's progress
 *   from the job store (core/jobs.py, shared/jobs)
 */
import { useState, useEffect, useRef } from 'react'

import ProgressPanel from '../shared/ui/ProgressPanel'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { api } from '../shared/transport/api'
import { BACKEND_TOKEN, backendMediaUrl } from '../shared/config/config'
import { ACTIVE } from '../shared/jobs/jobStore'
import { restoreOutcome, clearBackupMessage } from './restoreJob'
import { refreshJob, useActiveJob, useJob } from '../shared/jobs/useJobs'

const RESTORE_KIND = 'vault_restore'
// Every open of the restore dialog starts here, whatever the last restore used.
const DEFAULT_RESTORE_MODE = 'replace'
// The restore this window started, so a reload mid-restore still shows how it ended.
const FOLLOWED_KEY = 'nucleus.vaultRestoreJob'

function readFollowed() {
  try { return window.sessionStorage.getItem(FOLLOWED_KEY) } catch { return null }
}

function writeFollowed(id) {
  try {
    if (id) window.sessionStorage.setItem(FOLLOWED_KEY, id)
    else window.sessionStorage.removeItem(FOLLOWED_KEY)
  } catch { /* no storage: a reload only loses the outcome message */ }
}

export default function BackupRestore({}) {
  // State
  const [backingUp, setBackingUp] = useState(false)
  const [showRestoreModal, setShowRestoreModal] = useState(false)
  const [restoreFile, setRestoreFile] = useState(null)
  const [restoreMode, setRestoreMode] = useState(DEFAULT_RESTORE_MODE) // 'replace' or 'merge'
  const [backupMessage, setBackupMessage] = useState({ text: '', type: '' })

  // A restore is this window's upload, then a backend job. The job's record
  // (status, progress, result) lives in the job store; nothing here copies it.
  const [upload, setUpload] = useState(null) // { title, progress, status } until the job takes over
  const [followedId, setFollowedId] = useState(readFollowed)
  const [outcome, setOutcome] = useState(null) // { message, report?, recoveryPath?, reloading? }
  const running = useActiveJob(RESTORE_KIND)
  // While the upload is in flight the backend has not heard of this window's restore id (the job starts when the
  // upload is in), so only read it; the upload's reply asks for it (refreshJob).
  const job = useJob(followedId || running?.id || null, { ask: !upload })
  const handledRef = useRef(new Set())
  const xhrRef = useRef(null)

  useEffect(() => {
    if (!job || handledRef.current.has(job.id)) return
    if (ACTIVE.has(job.status)) {
      setUpload(null)
      return
    }
    handledRef.current.add(job.id)
    setUpload(null)
    setFollowedId(null)
    writeFollowed(null)
    const result = restoreOutcome(job)
    if (result.outcome) {
      playSound('start')
      setOutcome(result.outcome)
      if (result.outcome.reloading) setTimeout(() => window.location.reload(), 1500)
    } else {
      setBackupMessage(result.message)
    }
  }, [job])

  const restoring = Boolean(upload) || ACTIVE.has(job?.status) || Boolean(outcome?.reloading)
  const restoreReport = outcome?.report || null
  const restoreRecoveryPath = outcome?.recoveryPath || null
  const restoreTitle = upload?.title || (job?.params?.mode === 'merge' ? 'Merging vault…' : 'Restoring vault…')
  const restoreProgress = outcome?.reloading ? 100 : upload ? upload.progress : Math.round((job?.progress || 0) * 100)
  const restoreStatus = outcome?.message || upload?.status || job?.detail || ''

  // Handlers
  const handleBackupVault = async () => {
    // The app: ask where to save first (a dialog titled "Export Vault"), then the backend writes the backup there.
    // Cancel and no backup is made. Never a Chromium download: its own Save As dialog was titled with the
    // download URL, backend token included, and cancelling it deleted the backup.
    const chooseDestination = window.electron?.saveVaultBackupDialog
    let destination = null
    if (chooseDestination) {
      destination = await chooseDestination()
      if (!destination) return
    }

    setBackingUp(true)
    setBackupMessage({ text: 'Creating backup...', type: '' })

    try {
      if (destination) {
        const data = await api.post('/storage/backup', { destination })
        playSound('start')
        setBackupMessage({ text: `Vault exported to ${data.path}`, type: 'success' })
        return
      }

      // Browser fallback (the dev server outside the app): a plain download.
      const data = await api.post('/storage/backup')

      const created = { text: 'Backup created! Downloading...', type: 'success' }
      setBackupMessage(created)
      playSound('start')

      // Download the backup file
      const downloadUrl = backendMediaUrl(api.url(`/storage/backup/download/${data.filename}`))
      const link = document.createElement('a')
      link.href = downloadUrl
      link.download = data.filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)

      // Clear only this message: a later backup's or restore's error stays.
      setTimeout(() => {
        setBackupMessage((current) => clearBackupMessage(current, created))
      }, 3000)
    } catch (err) {
      setBackupMessage({ text: `Backup failed: ${err.message}`, type: 'error' })
    } finally {
      setBackingUp(false)
    }
  }

  const handleRestoreClick = () => {
    setRestoreFile(null)
    setRestoreMode(DEFAULT_RESTORE_MODE)
    setShowRestoreModal(true)
  }

  const handleRestoreFileSelect = (e) => {
    const file = e.target.files[0]
    if (file) {
      playSound('start')
      setRestoreFile(file)
    }
  }

  const confirmRestore = () => {
    if (!restoreFile) return

    setShowRestoreModal(false)
    setBackupMessage({ text: '', type: '' })
    setOutcome(null)
    // The id is ours from the start, so job events that beat the upload
    // response are already this restore's.
    const restoreId = crypto.randomUUID()
    setFollowedId(restoreId)
    setUpload({ title: 'Uploading backup…', progress: 0, status: 'Sending backup to the app…' })

    const formData = new FormData()
    formData.append('file', restoreFile)
    formData.append('mode', restoreMode)
    formData.append('restore_id', restoreId)

    // Use XHR (not fetch) so we can show real upload progress for a multi-GB
    // backup; once uploaded, the restore job drives the rest of the bar.
    const xhr = new XMLHttpRequest()
    xhrRef.current = xhr
    xhr.open('POST', api.url('/storage/restore'))
    if (BACKEND_TOKEN) xhr.setRequestHeader('X-Nucleus-Token', BACKEND_TOKEN)

    const failUpload = (text) => {
      setUpload(null)
      setFollowedId(null)
      setBackupMessage({ text, type: 'error' })
    }

    xhr.upload.onprogress = (e) => {
      if (xhrRef.current !== xhr || !e.lengthComputable) return
      const pct = Math.round((e.loaded / e.total) * 100)
      setUpload((current) => current && { ...current, progress: pct, status: `Uploading backup… ${pct}%` })
    }

    xhr.onload = () => {
      if (xhrRef.current !== xhr) return
      xhrRef.current = null
      let data = {}
      try { data = JSON.parse(xhr.responseText) } catch { /* ignore */ }
      if (xhr.status === 200 && data.success && data.restore_id === restoreId) {
        if (!handledRef.current.has(restoreId)) writeFollowed(restoreId)
        setUpload((current) => current && {
          title: restoreMode === 'merge' ? 'Merging vault…' : 'Restoring vault…',
          progress: 0,
          status: 'Backup received — processing…',
        })
        refreshJob(restoreId).catch(() => {})
      } else {
        failUpload(`Restore failed: ${data.error || `HTTP ${xhr.status}`}`)
      }
    }

    xhr.onerror = () => {
      if (xhrRef.current !== xhr) return
      xhrRef.current = null
      failUpload('Error: upload failed')
    }

    xhr.send(formData)
  }

  const cancelRestore = () => {
    setShowRestoreModal(false)
    setRestoreFile(null)
    setRestoreMode(DEFAULT_RESTORE_MODE)
  }

  // Render one side of the merge report (added / kept): named custom
  // characters/stages, then a count line for the bulkier item types.
  const renderReportSide = (title, side, kind) => {
    if (!side) return null
    const named = [...(side.custom_characters || []), ...(side.custom_stages || [])]
    const counts = []
    if (side.skins?.length) counts.push(`${side.skins.length} skin${side.skins.length === 1 ? '' : 's'}`)
    if (side.variants?.length) counts.push(`${side.variants.length} stage variant${side.variants.length === 1 ? '' : 's'}`)
    if (side.xdelta?.length) counts.push(`${side.xdelta.length} patch${side.xdelta.length === 1 ? '' : 'es'}`)
    if (side.bundles?.length) counts.push(`${side.bundles.length} bundle${side.bundles.length === 1 ? '' : 's'}`)
    if (side.extras?.length) counts.push(`${side.extras.length} effect${side.extras.length === 1 ? '' : 's'}`)
    if (side.menu_mods?.length) counts.push(`${side.menu_mods.length} menu mod${side.menu_mods.length === 1 ? '' : 's'}`)
    if (side.codes?.length) counts.push(`${side.codes.length} code${side.codes.length === 1 ? '' : 's'}`)
    const total = Object.values(side).reduce((sum, items) => sum + items.length, 0)
    if (total === 0) {
      return (
        <div className={`report-side report-${kind}`}>
          <strong>{title} (0)</strong>
          <p className="report-empty">{kind === 'kept' ? 'No conflicts.' : 'Nothing new.'}</p>
        </div>
      )
    }
    return (
      <div className={`report-side report-${kind}`}>
        <strong>{title} ({total})</strong>
        {named.length > 0 && (
          <ul className="report-names">
            {named.map((n) => <li key={n}>{n}</li>)}
          </ul>
        )}
        {counts.length > 0 && <p className="report-counts">{counts.join(' · ')}</p>}
      </div>
    )
  }

  return (
    <>
      {/* Main Section */}
      <section className="settings-section">
        <h3>Vault Backup & Restore</h3>
        <p className="section-description">
          Create a backup of your entire vault collection or restore from a previous backup.
        </p>

        <div className="backup-buttons">
          <button
            className="backup-button"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('start'); handleBackupVault(); }}
            disabled={backingUp || restoring}
          >
            {backingUp ? 'Creating Backup...' : 'Export Vault'}
          </button>

          <button
            className="restore-button"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('start'); handleRestoreClick(); }}
            disabled={backingUp || restoring}
          >
            {restoring ? 'Restoring...' : 'Import Vault'}
          </button>
        </div>

        {restoreRecoveryPath && (
          <div className="backup-message success">
            <p>Restore complete. Your previous Vault is retained for recovery at:</p>
            <p>{restoreRecoveryPath}</p>
            <p>It still uses disk space. Keep it until you have checked the restored library.</p>
            <button className="backup-button" onClick={() => window.location.reload()}>
              Open Restored Vault
            </button>
          </div>
        )}
        {restoring && !restoreReport && !restoreRecoveryPath && (
          <ProgressPanel
            title={restoreTitle}
            label="Restore progress"
            progressValue={restoreProgress}
            messageText={restoreStatus || 'Working…'}
          />
        )}

        {restoreReport && (
          <div className="restore-report">
            <h4>{restoreStatus || 'Merge complete'}</h4>
            {renderReportSide('Added to your vault', restoreReport.added, 'added')}
            {renderReportSide('Kept your version (skipped backup’s)', restoreReport.kept, 'kept')}
            <button
              className="backup-button"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('start'); window.location.reload(); }}
            >
              Done
            </button>
          </div>
        )}

        {backupMessage.text && (
          <div className={`message ${backupMessage.type}`}>
            {backupMessage.text}
          </div>
        )}
      </section>

      {/* Restore Modal */}
      {showRestoreModal && (
        <div className="modal-overlay" onClick={cancelRestore}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Restore Vault from Backup</h3>
            <p>
              Select a backup file to restore your vault collection.
            </p>

            <div className="file-input-container">
              <label htmlFor="restore-file-input" className="file-input-label">
                {restoreFile ? restoreFile.name : 'Choose backup file...'}
              </label>
              <input
                id="restore-file-input"
                type="file"
                accept=".zip"
                onChange={handleRestoreFileSelect}
                style={{ display: 'none' }}
              />
            </div>

            <div className="restore-mode-options">
              <label className="radio-label">
                <input
                  type="radio"
                  value="replace"
                  checked={restoreMode === 'replace'}
                  onChange={(e) => setRestoreMode(e.target.value)}
                />
                <div>
                  <strong>Replace All</strong>
                  <p className="radio-description">Validate and restore the backup, retaining the current Vault for recovery</p>
                </div>
              </label>

              <label className="radio-label">
                <input
                  type="radio"
                  value="merge"
                  checked={restoreMode === 'merge'}
                  onChange={(e) => setRestoreMode(e.target.value)}
                />
                <div>
                  <strong>Merge</strong>
                  <p className="radio-description">Keep current items and add backup items</p>
                </div>
              </label>
            </div>

            {restoreMode === 'replace' && (
              <p className="warning-text">
                Warning: This will delete all current vault items!
              </p>
            )}

            <div className="modal-actions">
              <button className="btn-cancel" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); cancelRestore(); }}>
                Cancel
              </button>
              <button
                className="btn-confirm"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); confirmRestore(); }}
                disabled={!restoreFile}
              >
                Restore Vault
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
