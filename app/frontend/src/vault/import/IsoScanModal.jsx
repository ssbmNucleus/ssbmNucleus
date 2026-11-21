/**
 * IsoScanModal - Rip new content out of one or more vanilla / modded ISOs.
 *
 * Four scan targets, chosen by checkbox:
 *   - Character skins: native extraction + hash filtering, live SocketIO
 *     progress, per-character CSP grid with checkboxes
 *   - Custom characters / Custom stages: m-ex extraction via a temp MexCLI
 *     project per ISO (synchronous, a minute or two per ISO); imported
 *     straight into the vault with a summary shown afterwards
 *
 * Flow:
 *   idle        → pick ISO files + scan targets, then "Start scan"
 *   scanning    → custom extraction passes first, then the skins job
 *   results     → skins CSP grid (+ custom extraction summary) → import
 *   importing   → loader while importing selected DATs
 *                 then refresh the vault and close on success
 *   results     → also retains partial imports / refresh errors
 *   error       → scan error display
 */

import { useEffect, useRef, useState } from 'react'
import { useJob, cancelJob } from '../../shared/jobs/useJobs'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import './IsoScanModal.css'
import { api } from '../../shared/transport/api'
import IsoScanResults from './IsoScanResults'
import IsoScanProgress from './IsoScanProgress'
import { SCAN_CATEGORIES } from './isoScanResultModel'

const TARGET_DEFAULTS = { skins: true, customCharacters: false, customStages: false, dasVariants: false }
const isNkitIsoPath = (path) => {
  const name = String(path || '').split(/[\\/]/).pop().toLowerCase()
  return name.includes('.nkit') && /\.(iso|gcm)$/i.test(name)
}
const unique = (items) => Array.from(new Set(items.filter(Boolean)))
const compatibleIsoPaths = (paths) => unique(paths).filter((p) => !isNkitIsoPath(p))
const skippedNkitIsoPaths = (paths) => unique(paths).filter(isNkitIsoPath)

export default function IsoScanModal({
  onClose,
  onRefresh,
  initialIsoPaths,
  initialPathError,
  initialTargets,
  onCustomCharactersChanged,
  onCustomStagesChanged
}) {
  const [phase, setPhase] = useState('idle') // idle | scanning | results | importing | error
  // Seeded when the unified Import button / drag-and-drop receives .iso files
  const [isoPaths, setIsoPaths] = useState(() => compatibleIsoPaths(initialIsoPaths || []))
  const [skippedNkitPaths, setSkippedNkitPaths] = useState(() => skippedNkitIsoPaths(initialIsoPaths || []))
  const [pathError, setPathError] = useState(initialPathError || null)
  // Which scan targets to run; remembered across sessions. An explicit
  // initialTargets (e.g. the custom grids' Scan ISO buttons) wins.
  const [targets, setTargets] = useState(() => {
    if (initialTargets) return { ...TARGET_DEFAULTS, skins: false, ...initialTargets }
    try {
      return { ...TARGET_DEFAULTS, ...JSON.parse(localStorage.getItem('iso_scan_targets') || '{}') }
    } catch {
      return TARGET_DEFAULTS
    }
  })
  const [customSummary, setCustomSummary] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [progress, setProgress] = useState({ status: 'pending', percent: 0, message: '' })
  const [stats, setStats] = useState(null)
  const [characters, setCharacters] = useState({})
  const [skippedVault, setSkippedVault] = useState([])
  const [selected, setSelected] = useState(new Set())
  const [importResult, setImportResult] = useState(null)
  const [errorMsg, setErrorMsg] = useState(null)
  const [extractionFailures, setExtractionFailures] = useState([])
  const [startedAt, setStartedAt] = useState(Date.now)
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState(null)
  const [refreshError, setRefreshError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const cancelRequested = useRef(false)
  const finishing = useRef(false)
  const closed = useRef(false)

  const scanJob = useJob(jobId)

  // The shared store reconciles on load and reconnect, including fast finishes.
  useEffect(() => {
    if (!scanJob || phase !== 'scanning') return
    const fail = message => {
      setCancelling(false)
      cancelRequested.current = false
      setErrorMsg(message || 'Scan failed')
      setPhase('error')
      playSound('error')
    }
    const j = scanJob.result || {}
    const extra = scanJob.extra || {}
    setProgress({
      status: extra.phase || scanJob.status,
      percent: Math.round((scanJob.progress || 0) * 100),
      message: scanJob.detail || '',
      current: extra.phase_current,
      total: extra.phase_total,
    })
    if (extra.stats) setStats(extra.stats)
    if (scanJob.status === 'cancelled') {
      setPhase(customSummary ? 'results' : 'idle')
      setCancelling(false)
      setJobId(null)
      api.delete(`/iso-scan/${jobId}`).catch(() => {})
    } else if (['failed', 'interrupted'].includes(scanJob.status)) {
      fail(scanJob.error)
    } else if (scanJob.status === 'done') {
      setCancelling(false)
      cancelRequested.current = false
      const visibleCharacters = Object.fromEntries(
        Object.entries(j.characters || {})
          .map(([char, skins]) => [char, (skins || []).filter(s => s.csp_url)])
          .filter(([, skins]) => skins.length > 0)
      )
      setCharacters(visibleCharacters)
      setSkippedVault(j.skipped_vault || [])
      setStats(j.stats || null)
      setExtractionFailures(j.extraction_failures || [])
      // Default: select all new skins
      const all = new Set()
      for (const [char, skins] of Object.entries(visibleCharacters)) {
        for (const s of skins) all.add(s.key)
      }
      setSelected(all)
      setPhase('results')
      playSound(all.size ? 'newSkin' : 'boop')
    }
  }, [scanJob, jobId, phase, customSummary])

  const addIsoPaths = (paths) => {
    const compatible = compatibleIsoPaths(paths || [])
    const skipped = skippedNkitIsoPaths(paths || [])
    if (compatible.length) {
      setIsoPaths(prev => unique([...prev, ...compatible]))
    }
    if (skipped.length) {
      setSkippedNkitPaths(prev => unique([...prev, ...skipped]))
    }
  }

  const pickFiles = async () => {
    if (!window.electron?.openIsoMultiDialog) return
    playSound('boop')
    try {
      const paths = await window.electron.openIsoMultiDialog()
      if (Array.isArray(paths) && paths.length) {
        addIsoPaths(paths)
        setPathError(null)
      }
    } catch {
      setPathError('Could not open the file picker. Try again.')
    }
  }

  const removeIso = (path) => {
    setIsoPaths(isoPaths.filter(p => p !== path))
  }

  const anyTarget = targets.skins || targets.customCharacters || targets.customStages || targets.dasVariants

  const toggleTarget = (key) => {
    const next = { ...targets, [key]: !targets[key] }
    setTargets(next)
    try { localStorage.setItem('iso_scan_targets', JSON.stringify(next)) } catch { /* ignore */ }
  }

  const startScan = async () => {
    if (!isoPaths.length || !anyTarget) return
    playSound('start')
    setPhase('scanning')
    setStartedAt(Date.now())
    setJobId(null)
    cancelRequested.current = false
    setCancelling(false)
    setCancelError(null)
    setProgress({ status: 'pending', percent: 0, message: 'Starting…' })
    setErrorMsg(null)
    setCustomSummary(null)
    setCharacters({})
    setSelected(new Set())
    setImportResult(null)
    setRefreshError(null)
    setStats(null)
    setSkippedVault([])
    setExtractionFailures([])

    // Custom extraction passes run first (synchronous, ~a minute or two per
    // ISO). Custom characters + stages SHARE one temp m-ex project build per
    // ISO (the /scan-iso/mex-content endpoint), so selecting both no longer
    // doubles the work. DAS variants run as their own pass.
    const wantMex = targets.customCharacters || targets.customStages
    const nameOf = (it) => (typeof it === 'string' ? it : (it.name || it.id || ''))
    const summary = {}
    const ensure = (k) => (summary[k] || (summary[k] = { imported: [], skipped: [], errors: [] }))

    const totalSteps = (wantMex ? isoPaths.length : 0)
      + (targets.dasVariants ? isoPaths.length : 0)
    let step = 0

    if (wantMex) {
      if (targets.customCharacters) ensure('characters')
      if (targets.customStages) ensure('stages')
      for (const isoPath of isoPaths) {
        if (cancelRequested.current) break
        const isoName = isoPath.split(/[\\/]/).pop()
        setProgress({
          status: 'custom',
          categories: [targets.customCharacters && 'characters', targets.customStages && 'stages'].filter(Boolean),
          percent: totalSteps ? Math.round((step / totalSteps) * 100) : 0,
          message: `Extracting custom content from ${isoName}…`,
          current: step + 1, total: totalSteps,
        })
        try {
          const data = await api.post(`/scan-iso/mex-content`, {
            isoPath,
            characters: targets.customCharacters,
            stages: targets.customStages,
          })
          if (targets.customCharacters && data.characters) {
            ensure('characters').imported.push(...(data.characters.imported || []).map(nameOf))
            ensure('characters').skipped.push(...(data.characters.skipped || []))
          }
          if (targets.customStages && data.stages) {
            ensure('stages').imported.push(...(data.stages.imported || []).map(nameOf))
            ensure('stages').skipped.push(...(data.stages.skipped || []))
          }
        } catch (e) {
          const msg = `${isoName}: ${e.message || 'failed'}`
          if (targets.customCharacters) ensure('characters').errors.push(msg)
          if (targets.customStages) ensure('stages').errors.push(msg)
        }
        step += 1
      }
    }

    if (targets.dasVariants && !cancelRequested.current) {
      ensure('das')
      for (const isoPath of isoPaths) {
        if (cancelRequested.current) break
        const isoName = isoPath.split(/[\\/]/).pop()
        setProgress({
          status: 'custom',
          categories: ['das'],
          percent: totalSteps ? Math.round((step / totalSteps) * 100) : 0,
          message: `Extracting stage variants from ${isoName}…`,
          current: step + 1, total: totalSteps,
        })
        try {
          const data = await api.post(`/das/scan-iso`, { isoPath })
          ensure('das').imported.push(...(data.imported || []))
          ensure('das').skipped.push(...(data.skipped || []))
        } catch (e) {
          ensure('das').errors.push(`${isoName}: ${e.message || 'failed'}`)
        }
        step += 1
      }
    }

    if (Object.keys(summary).length) {
      setCustomSummary(summary)
      // A view refresh must not strand a completed extraction in its loader.
      const notify = callback => Promise.resolve().then(() => callback?.()).catch(error => console.warn('ISO vault refresh failed', error))
      if (summary.characters?.imported.length) void notify(onCustomCharactersChanged)
      if (summary.stages?.imported.length || summary.das?.imported.length) void notify(onCustomStagesChanged)
    }

    if (!targets.skins || cancelRequested.current) {
      setPhase(Object.keys(summary).length ? 'results' : 'idle')
      setCancelling(false)
      playSound(Object.values(summary).some(s => s.errors.length) ? 'error'
        : Object.values(summary).some(s => s.imported.length) ? 'newSkin' : 'boop')
      return
    }

    setProgress({ status: 'pending', percent: 0, message: 'Starting…' })
    try {
      const data = await api.post(`/iso-scan/start`, { iso_paths: isoPaths })
      if (data.skipped?.length) {
        setSkippedNkitPaths(prev => unique([
          ...prev,
          ...data.skipped.map((s) => s.path || s).filter(Boolean),
        ]))
      }
      setJobId(data.job_id)
      if (cancelRequested.current) await requestCancel(data.job_id)
    } catch (e) {
      // A failed start still reports which ISOs were skipped (NKit) - keep that.
      if (e.data?.skipped?.length) {
        setSkippedNkitPaths(prev => unique([
          ...prev,
          ...e.data.skipped.map((s) => s.path || s).filter(Boolean),
        ]))
      }
      setErrorMsg(e.message || 'Failed to start scan')
      setPhase('error')
      playSound('error')
    }
  }

  const requestCancel = async (id) => {
    try {
      await cancelJob(id)
    } catch {
      cancelRequested.current = false
      setCancelling(false)
      setCancelError('Could not cancel. Try again.')
    }
  }

  const cancelScan = async () => {
    if (cancelRequested.current) return
    playSound('boop')
    cancelRequested.current = true
    setCancelling(true)
    setCancelError(null)
    // Custom imports have no interrupt endpoint: finish the current request,
    // keep its additions, and skip remaining passes. A pending skin-job start
    // sends cancellation as soon as its job ID arrives.
    if (jobId) await requestCancel(jobId)
  }

  const toggleSkin = (key) => {
    const next = new Set(selected)
    if (next.has(key)) next.delete(key); else next.add(key)
    setSelected(next)
  }

  const toggleAllForChar = (char) => {
    const skins = characters[char] || []
    const allSelected = skins.every(s => selected.has(s.key))
    const next = new Set(selected)
    if (allSelected) {
      for (const s of skins) next.delete(s.key)
    } else {
      for (const s of skins) next.add(s.key)
    }
    setSelected(next)
  }

  const selectAll = () => {
    const next = new Set()
    for (const skins of Object.values(characters)) {
      for (const s of skins) next.add(s.key)
    }
    setSelected(next)
  }

  const selectNone = () => setSelected(new Set())

  const importSelected = async () => {
    if (!selected.size || !jobId || finishing.current || importResult) return
    finishing.current = true
    playSound('start')
    setPhase('importing')
    setStartedAt(Date.now())
    setCancelling(false)
    setCancelError(null)
    // Only the import endpoint's complete result envelope proves what saved.
    // A lost response may follow writes; don't offer a blind duplicate retry.
    const isResult = data => Number.isInteger(data?.imported) && data.imported >= 0
      && data.total_selected === selected.size && Array.isArray(data.errors)
      && (data.imported > 0 || data.errors.length > 0)
    let result
    try {
      result = await api.post(`/iso-scan/${jobId}/import`, { keys: Array.from(selected), auto_fix: true })
      if (!isResult(result)) throw new Error('Could not confirm the import result')
    } catch (e) {
      result = isResult(e.data) ? { ...e.data, errors: e.data.errors.length ? e.data.errors : [e.message || 'Import did not complete'] }
        : { imported: 0, unconfirmed: true, errors: [
        `${e.message || 'Import interrupted'}. Check your vault before scanning again.`,
      ] }
    }
    setImportResult(result)
    const refreshed = await refreshVault()
    if (!result.errors.length && refreshed) {
      playSound('achievement')
      closeModal()
    } else {
      setPhase('results')
      playSound('error')
    }
    finishing.current = false
  }

  const refreshVault = async () => {
    try {
      await onRefresh?.()
      setRefreshError(null)
      return true
    } catch {
      setRefreshError('Could not refresh the vault.')
      return false
    }
  }

  const retryRefresh = async () => {
    if (finishing.current) return
    finishing.current = true
    setRefreshing(true)
    playSound('boop')
    if (await refreshVault()) {
      if (importResult && !importResult.errors.length) {
        playSound('achievement')
        closeModal()
      }
    } else playSound('error')
    setRefreshing(false)
    finishing.current = false
  }

  const closeModal = () => {
    if (closed.current) return
    closed.current = true
    onClose?.()
    // Temporary previews live until dismissal; deletion never delays closing.
    if (jobId) void api.delete(`/iso-scan/${jobId}`).catch(() => {})
  }

  const handleClose = () => {
    playSound('boop')
    return closeModal()
  }

  const selectedCount = selected.size
  const busy = phase === 'scanning' || phase === 'importing'
  const showingResults = phase === 'results' || (phase === 'error' && customSummary)

  // ─── Render ───────────────────────────────────────────────

  return (
    <div className="edit-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget && !busy && !showingResults) handleClose() }}>
      <div className={`edit-modal-content iso-scan-modal ${busy ? 'iso-scan-modal-progress' : showingResults ? 'iso-scan-modal-results' : ''}`} onClick={(e) => e.stopPropagation()}>
        {phase === 'idle' && (
          <>
            <h2>Scan ISOs</h2>

            {pathError && <div className="iso-scan-warning" role="alert">{pathError}</div>}

            {skippedNkitPaths.length > 0 && (
              <div className="iso-scan-warning">
                <strong>Skipped NKit ISO{skippedNkitPaths.length === 1 ? '' : 's'}.</strong>
                <p>
                  NKit images are not compatible with this importer:{' '}
                  {skippedNkitPaths.map(p => p.split(/[\\/]/).pop()).join(', ')}
                </p>
              </div>
            )}

            <p className="iso-scan-help">
              Character skins get a preview; other content goes straight to your vault.
            </p>

            <div className="iso-scan-targets">
              {SCAN_CATEGORIES.map(({ targetKey, label }) => <label key={targetKey} onMouseEnter={playHoverSound}>
                <input type="checkbox" checked={targets[targetKey]}
                  onChange={() => { playSound('boop'); toggleTarget(targetKey) }} />
                {label}
              </label>)}
            </div>

            <div className="iso-scan-file-list">
              {isoPaths.length === 0 && (
                <div className="iso-scan-empty">No ISOs selected.</div>
              )}
              {isoPaths.map(p => (
                <div key={p} className="iso-scan-file-row">
                  <span className="iso-scan-file-name" title={p}>
                    {p.split(/[\\/]/).pop()}
                  </span>
                  <button
                    className="iso-scan-remove"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); removeIso(p) }}
                    title="Remove"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>

            <div className="edit-buttons iso-scan-actions">
              <button
                className="btn-cancel"
                onMouseEnter={playHoverSound}
                onClick={pickFiles}
                disabled={!window.electron?.openIsoMultiDialog}
              >
                + Add ISOs
              </button>
              <button
                className="btn-save"
                onMouseEnter={playHoverSound}
                onClick={startScan}
                disabled={!isoPaths.length || !anyTarget}
              >
                Start scan ({isoPaths.length})
              </button>
              <button
                className="btn-cancel"
                onMouseEnter={playHoverSound}
                onClick={handleClose}
              >
                Close
              </button>
            </div>
          </>
        )}

        {busy && <IsoScanProgress progress={progress} isoPaths={isoPaths} startedAt={startedAt}
          importing={phase === 'importing'} count={selectedCount} cancelling={cancelling}
          cancelError={cancelError} onCancel={cancelScan} />}

        {showingResults && (
          <IsoScanResults
            characters={characters} customSummary={customSummary} stats={stats}
            skippedVault={skippedVault}
            extractionFailures={extractionFailures} isoPaths={isoPaths} scanSkins={targets.skins}
            scanError={phase === 'error' ? errorMsg : null}
            importResult={importResult} selected={selected}
            refreshError={refreshError} refreshing={refreshing} onRetryRefresh={retryRefresh}
            onToggleSkin={toggleSkin} onToggleCharacter={toggleAllForChar}
            onSelectAll={selectAll} onSelectNone={selectNone}
            onImport={importSelected} onClose={closeModal}
          />
        )}

        {phase === 'error' && !customSummary && (
          <>
            <h2 style={{ color: 'var(--color-error)' }}>Scan failed</h2>
            <div style={{ textAlign: 'center', padding: '1rem 0' }}>
              <div style={{ fontSize: '3rem', marginBottom: '1rem', color: 'var(--color-error)' }}>✕</div>
              <p style={{ color: 'var(--color-error)' }}>{errorMsg}</p>
            </div>
            <div className="edit-buttons">
              <button className="btn-cancel" onMouseEnter={playHoverSound} onClick={handleClose}>
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
