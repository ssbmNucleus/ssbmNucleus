/**
 * useXdeltaPatches Hook
 *
 * Manages XDelta patches including:
 * - Fetching, importing, editing, deleting patches
 * - Building ISOs from patches
 * - Creating new patches from modded ISOs
 * - Download functionality
 * - Bundle (.ssbm) import, and installing a stored bundle
 *
 * Building, creating and installing are backend jobs (`xdelta_build`,
 * `xdelta_create`, `bundle_install`; core/jobs.py). Each attempt follows the
 * record of the job it started, by id, so a job that ended before the window
 * learned its id still shows how it ended, and an earlier attempt's outcome
 * never lands on a later one.
 */

import { useEffect, useRef, useState } from 'react'
import { appConfirm } from '../../shared/ui/appDialogs'
import { API_URL, backendMediaUrl } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'
import { useFinishedJobs, useJob } from '../../shared/jobs/useJobs'
import { jobOutcome, jobPercent } from '../../shared/jobs/jobOutcome'
import { downloadPatchFile } from '../patches/patchDownload'

// One attempt's state, from its request and then its job record:
// idle (no attempt) | running | complete | error.
function attemptState(attempt, job) {
  if (!attempt) return { state: 'idle', outcome: null }
  if (attempt.error) return { state: 'error', outcome: null }
  const outcome = jobOutcome(job)
  if (!outcome) return { state: 'running', outcome: null }
  return { state: outcome.ok ? 'complete' : 'error', outcome }
}

// An attempt ({ jobId, error, ... }) that a newer one can replace while its
// request is still in flight.
function useAttempt() {
  const [attempt, setAttempt] = useState(null)
  const ref = useRef(null)
  const set = (next) => {
    ref.current = next
    setAttempt(next)
  }
  // Start: POST, then follow the returned job unless a newer attempt began.
  const start = async (fields, post, errorText) => {
    const next = { ...fields, jobId: null, error: null }
    set(next)
    try {
      const data = await post()
      if (ref.current === next) set({ ...next, jobId: data.job_id })
    } catch (err) {
      if (ref.current === next) set({ ...next, error: errorText(err) })
    }
  }
  return [attempt, start, () => set(null)]
}

export function useXdeltaPatches({ onBundleImportSuccess }) {
  // Patches list state
  const [xdeltaPatches, setXdeltaPatches] = useState([])

  // Import modal state
  const [showXdeltaImportModal, setShowXdeltaImportModal] = useState(false)
  const [xdeltaImportData, setXdeltaImportData] = useState({ name: '', description: '', file: null, image: null })
  const [importingXdelta, setImportingXdelta] = useState(false)

  // Edit modal state
  const [showXdeltaEditModal, setShowXdeltaEditModal] = useState(false)
  const [editingXdelta, setEditingXdelta] = useState(null)

  // Build ISO: { patch, jobId, error } while the modal is open
  const [xdeltaBuild, startBuild, clearBuild] = useAttempt()
  const buildJob = useJob(xdeltaBuild?.jobId || null)
  const build = attemptState(xdeltaBuild, buildJob)

  // Create patch modal state; the creation is { jobId, error }
  const [showXdeltaCreateModal, setShowXdeltaCreateModal] = useState(false)
  const [xdeltaCreateData, setXdeltaCreateData] = useState({ name: '', description: '', moddedIsoPath: '' })
  const [xdeltaCreate, startCreate, clearCreate] = useAttempt()
  const createJob = useJob(xdeltaCreate?.jobId || null)
  const create = attemptState(xdeltaCreate, createJob)

  // Bundle import (a synchronous save to storage) state
  const [bundlePreview, setBundlePreview] = useState(null)
  const [bundleUploading, setBundleUploading] = useState(false)
  const [bundleUploadResult, setBundleUploadResult] = useState(null)
  const [bundleUploadError, setBundleUploadError] = useState(null)

  // Bundle install: { jobId, error }
  const [bundleInstall, startInstall, clearInstall] = useAttempt()
  const installJob = useJob(bundleInstall?.jobId || null)
  const install = attemptState(bundleInstall, installJob)

  // Fetch patches list
  const fetchXdeltaPatches = async () => {
    try {
      const data = await api.get('/xdelta/list')
      // `data` is null when the server answered with something that is not JSON
      // (e.g. an HTML error page) - leave the list untouched in that case.
      if (data?.success) {
        setXdeltaPatches(data.patches)
      }
    } catch (err) {
      console.error('Failed to fetch xdelta patches:', err)
    }
  }

  // A patch created here or by the export builder joins the list when its job is done.
  const finishedCreates = useFinishedJobs('xdelta_create')
  useEffect(() => {
    if (finishedCreates) fetchXdeltaPatches()
  }, [finishedCreates])

  // An installed bundle refreshes the bundle list, as an imported one does.
  useEffect(() => {
    if (install.state === 'complete') onBundleImportSuccess?.()
  }, [install.state])

  // Import patch
  const handleImportXdelta = async () => {
    if (!xdeltaImportData.file) {
      alert('Please select an xdelta file')
      return
    }

    setImportingXdelta(true)

    try {
      const formData = new FormData()
      formData.append('file', xdeltaImportData.file)
      formData.append('name', xdeltaImportData.name || xdeltaImportData.file.name.replace('.xdelta', ''))
      formData.append('description', xdeltaImportData.description)
      if (xdeltaImportData.image) {
        formData.append('image', xdeltaImportData.image)
      }

      await api.post('/xdelta/import', formData)

      setShowXdeltaImportModal(false)
      setXdeltaImportData({ name: '', description: '', file: null, image: null })
      await fetchXdeltaPatches()
    } catch (err) {
      alert(`Import error: ${err.message}`)
    } finally {
      setImportingXdelta(false)
    }
  }

  // Preview bundle
  const handleBundlePreview = async (file) => {
    try {
      const formData = new FormData()
      formData.append('file', file)

      const data = await api.post('/bundle/preview', formData)

      setBundlePreview(data)
    } catch (err) {
      setBundleUploadError(`Preview error: ${err.message}`)
    }
  }

  // Import bundle (just saves to storage, does NOT install)
  const handleBundleImport = async () => {
    if (!xdeltaImportData.file) {
      alert('Please select a bundle file')
      return
    }

    setBundleUploading(true)
    setBundleUploadError(null)

    try {
      const formData = new FormData()
      formData.append('file', xdeltaImportData.file)

      const data = await api.post('/bundle/import', formData)

      // Import complete - just saved to storage
      setBundleUploadResult({ name: data.name, saved: true })
      setBundleUploading(false)
      // Refresh bundles list
      onBundleImportSuccess?.()
    } catch (err) {
      setBundleUploadError(`Import error: ${err.message}`)
      setBundleUploading(false)
    }
  }

  // Install a stored bundle (builds its ISO, loads its textures): a job the
  // import modal follows.
  const installBundle = (bundleId, body) => startInstall(
    { bundleId },
    () => api.post(`/bundle/install/${bundleId}`, body),
    // err.data => the backend reported the failure itself
    (err) => (err.data ? err.message : `Install error: ${err.message}`),
  )

  // Reset bundle state
  const handleBundleReset = () => {
    setBundlePreview(null)
    setBundleUploading(false)
    setBundleUploadResult(null)
    setBundleUploadError(null)
    clearInstall()
  }

  // Build ISO from patch
  const handleBuildXdeltaIso = async (patch) => {
    const vanillaIsoPath = localStorage.getItem('vanilla_iso_path')

    if (!vanillaIsoPath) {
      alert('No vanilla ISO path set. Please set it in Settings first.')
      return
    }

    // Opens the modal; the build's own job drives it from here
    await startBuild(
      { patch },
      () => api.post(`/xdelta/build/${patch.id}`, { vanillaIsoPath }),
      (err) => err.message,
    )
  }

  // Download built ISO (by its build job; the file is deleted once sent)
  const handleDownloadXdeltaIso = () => {
    const filename = build.outcome?.result?.filename
    if (!filename || !xdeltaBuild?.jobId) return

    const link = document.createElement('a')
    link.href = backendMediaUrl(`${API_URL}/xdelta/download/${encodeURIComponent(xdeltaBuild.jobId)}`)
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  // Close build modal
  const closeXdeltaBuildModal = () => clearBuild()

  // Select modded ISO for creating patch
  const handleSelectModdedIso = async () => {
    try {
      // Use Electron's file dialog if available
      if (window.electron?.openIsoDialog) {
        const result = await window.electron.openIsoDialog()
        if (result) {
          setXdeltaCreateData({ ...xdeltaCreateData, moddedIsoPath: result })
        }
      } else {
        alert('File selection requires the desktop app')
      }
    } catch (err) {
      console.error('Failed to select ISO:', err)
    }
  }

  // Start creating patch
  const handleStartCreateXdelta = async () => {
    if (!xdeltaCreateData.moddedIsoPath) {
      alert('Please select a modded ISO file')
      return
    }

    if (!xdeltaCreateData.name.trim()) {
      alert('Please enter a name for the patch')
      return
    }

    const vanillaIsoPath = localStorage.getItem('vanilla_iso_path')
    if (!vanillaIsoPath) {
      alert('No vanilla ISO path set. Please set it in Settings first.')
      return
    }

    await startCreate(
      {},
      () => api.post('/xdelta/create', {
        vanillaIsoPath,
        moddedIsoPath: xdeltaCreateData.moddedIsoPath,
        name: xdeltaCreateData.name,
        description: xdeltaCreateData.description
      }),
      (err) => err.message,
    )
  }

  // Close create modal
  const closeXdeltaCreateModal = () => {
    setShowXdeltaCreateModal(false)
    setXdeltaCreateData({ name: '', description: '', moddedIsoPath: '' })
    clearCreate()
  }

  // Download patch file
  const handleDownloadPatch = async (patchId) => {
    try {
      await downloadPatchFile(patchId)
    } catch (err) {
      alert(`Patch download failed: ${err.message}`)
    }
  }

  // Delete patch
  const handleDeleteXdelta = async (patchId) => {
    if (!await appConfirm('Are you sure you want to delete this patch?', {
      title: 'Delete Patch',
      confirmText: 'Delete',
    })) return

    try {
      await api.post(`/xdelta/delete/${patchId}`)

      await fetchXdeltaPatches()
    } catch (err) {
      alert(`Delete error: ${err.message}`)
    }
  }

  // Edit patch metadata
  const handleEditXdelta = (patch) => {
    setEditingXdelta({ ...patch })
    setShowXdeltaEditModal(true)
  }

  // Save patch metadata edit
  const handleSaveXdeltaEdit = async () => {
    if (!editingXdelta) return

    try {
      await api.post(`/xdelta/update/${editingXdelta.id}`, {
        name: editingXdelta.name,
        description: editingXdelta.description
      })

      setShowXdeltaEditModal(false)
      setEditingXdelta(null)
      await fetchXdeltaPatches()
    } catch (err) {
      alert(`Save error: ${err.message}`)
    }
  }

  // Update patch image
  const handleUpdateXdeltaImage = async (e) => {
    if (!editingXdelta) return

    const file = e.target.files[0]
    if (!file) return

    const formData = new FormData()
    formData.append('image', file)

    try {
      const data = await api.post(`/xdelta/update-image/${editingXdelta.id}`, formData)

      setEditingXdelta({ ...editingXdelta, imageUrl: data.imageUrl })
      await fetchXdeltaPatches()
    } catch (err) {
      alert(`Image update error: ${err.message}`)
    }
  }

  // Close import modal and reset bundle state
  const closeXdeltaImportModal = () => {
    setShowXdeltaImportModal(false)
    setXdeltaImportData({ name: '', description: '', file: null, image: null })
    handleBundleReset()
  }

  const buildState = { idle: 'idle', running: 'building', complete: 'complete', error: 'error' }[build.state]
  const createState = { idle: 'idle', running: 'creating', complete: 'complete', error: 'error' }[create.state]
  const installing = install.state === 'running'

  return {
    // State
    xdeltaPatches,
    showXdeltaImportModal,
    setShowXdeltaImportModal,
    xdeltaImportData,
    setXdeltaImportData,
    importingXdelta,
    showXdeltaEditModal,
    setShowXdeltaEditModal,
    editingXdelta,
    setEditingXdelta,
    showXdeltaBuildModal: Boolean(xdeltaBuild),
    xdeltaBuildState: buildState,
    xdeltaBuildPatch: xdeltaBuild?.patch || null,
    xdeltaBuildFilename: build.outcome?.ok ? build.outcome.result.filename : null,
    xdeltaBuildError: xdeltaBuild?.error || (build.outcome && !build.outcome.ok ? build.outcome.error : null),
    xdeltaBuildProgress: jobPercent(buildJob) ?? 0,
    xdeltaBuildMessage: buildJob?.detail || 'Starting...',
    showXdeltaCreateModal,
    setShowXdeltaCreateModal,
    xdeltaCreateData,
    setXdeltaCreateData,
    xdeltaCreateState: createState,
    xdeltaCreateProgress: jobPercent(createJob) ?? 0,
    xdeltaCreateMessage: createJob?.detail || 'Starting...',
    xdeltaCreateError: xdeltaCreate?.error || (create.outcome && !create.outcome.ok ? create.outcome.error : null),
    xdeltaCreateResult: create.outcome?.ok ? create.outcome.result : null,

    // Bundle state: the import (save to storage) or the install job
    bundlePreview,
    setBundlePreview,
    bundleImporting: bundleUploading || installing,
    bundleProgress: installing ? (jobPercent(installJob) ?? 0) : 0,
    bundleMessage: installing ? (installJob?.detail || 'Starting install...') : '',
    bundleComplete: Boolean(bundleUploadResult) || install.state === 'complete',
    bundleError: bundleInstall?.error || (install.outcome && !install.outcome.ok ? install.outcome.error : null)
      || bundleUploadError,
    bundleResult: install.outcome?.ok ? install.outcome.result : bundleUploadResult,

    // Handlers
    fetchXdeltaPatches,
    handleImportXdelta,
    handleBuildXdeltaIso,
    handleDownloadXdeltaIso,
    closeXdeltaBuildModal,
    handleSelectModdedIso,
    handleStartCreateXdelta,
    closeXdeltaCreateModal,
    handleDownloadPatch,
    handleDeleteXdelta,
    handleEditXdelta,
    handleSaveXdeltaEdit,
    handleUpdateXdeltaImage,
    closeXdeltaImportModal,

    // Bundle handlers
    handleBundlePreview,
    handleBundleImport,
    handleBundleReset,
    installBundle
  }
}
