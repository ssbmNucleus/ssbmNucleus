import { useState, useCallback, useRef } from 'react'
import { api, authenticatedFetch } from '../../shared/transport/api'
import { recoverFailedDownload } from './downloadQueueRecovery.js'

/**
 * Download phases for the state machine
 */
export const DOWNLOAD_PHASES = {
  IDLE: 'idle',
  DOWNLOADING: 'downloading',
  IMPORTING: 'importing',
  COMPLETE: 'complete',
  ERROR: 'error'
}

/**
 * Custom hook for managing a download queue with sequential processing
 * Prevents data corruption from concurrent imports
 *
 * @returns {Object} Download queue state and controls
 */
export function useDownloadQueue() {
  const [currentDownload, setCurrentDownload] = useState(null)
  const [phase, setPhase] = useState(DOWNLOAD_PHASES.IDLE)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [queueLength, setQueueLength] = useState(0)

  // Queue for pending downloads
  const queueRef = useRef([])
  const isProcessingRef = useRef(false)
  const errorRecoveryAvailableRef = useRef(false)

  /**
   * Process the next download in the queue
   */
  const processNext = useCallback(async () => {
    if (isProcessingRef.current || queueRef.current.length === 0) {
      return
    }

    isProcessingRef.current = true
    errorRecoveryAvailableRef.current = false
    const download = queueRef.current.shift()
    setQueueLength(queueRef.current.length)

    setCurrentDownload(download)
    setPhase(DOWNLOAD_PHASES.DOWNLOADING)
    setError(null)
    setResult(null)

    let blob
    try {
      // Download the file
      const response = await authenticatedFetch(download.url)
      if (!response.ok) {
        throw new Error(`Download failed: ${response.status} ${response.statusText}`)
      }
      blob = await response.blob()

      // Switch to importing phase
      setPhase(DOWNLOAD_PHASES.IMPORTING)

      // Create FormData for import
      const formData = new FormData()
      formData.append('file', blob, `${download.name || 'mod'}.zip`)

      if (download.title) {
        formData.append('custom_title', download.title)
      }
      if (download.type) {
        formData.append('mod_type', download.type)
      }
      if (download.effectType) {
        formData.append('effect_type', download.effectType)
      }

      // Call the import API
      const importResult = await api.post('/import/file', formData)

      setResult({
        success: true,
        importType: importResult.type,
        cameraSound: importResult.camera_sound === true,
        message: `Successfully imported: ${download.title || download.name || 'mod'}`
      })
      setPhase(DOWNLOAD_PHASES.COMPLETE)
    } catch (err) {
      // The slippi/duplicate dialogs come back as { success: false, type: ... }
      // envelopes, so they surface as a thrown ApiError carrying the body.
      const importResult = err.data

      // Check for slippi dialog (special case that needs user interaction)
      if (importResult?.type === 'slippi_dialog') {
        setResult({
          ...importResult,
          needsSlippiChoice: true,
          blob,
          downloadName: download.name,
          downloadTitle: download.title,
          downloadType: download.type,
          downloadEffectType: download.effectType
        })
        setPhase(DOWNLOAD_PHASES.COMPLETE)
        return
      }

      // Check for duplicate dialog (skin already exists)
      if (importResult?.type === 'duplicate_dialog') {
        setResult({
          ...importResult,
          needsDuplicateChoice: true,
          blob,
          downloadName: download.name,
          downloadTitle: download.title,
          downloadType: download.type,
          downloadEffectType: download.effectType
        })
        setPhase(DOWNLOAD_PHASES.COMPLETE)
        return
      }

      console.error('[DownloadQueue] Error:', err)
      errorRecoveryAvailableRef.current = true
      setError(err.message)
      setPhase(DOWNLOAD_PHASES.ERROR)
    }
  }, [])

  /**
   * Queue a download for processing
   * @param {Object} download - Download info with url, name, title
   */
  const queueDownload = useCallback((download) => {
    queueRef.current.push(download)
    setQueueLength(queueRef.current.length)
    processNext()
  }, [processNext])

  /**
   * Clear the current download state (after user dismisses modal)
   */
  const clearDownload = useCallback(() => {
    setCurrentDownload(null)
    setPhase(DOWNLOAD_PHASES.IDLE)
    setError(null)
    setResult(null)
    isProcessingRef.current = false
    errorRecoveryAvailableRef.current = false
    setQueueLength(queueRef.current.length)

    // Process next in queue if any
    if (queueRef.current.length > 0) {
      setTimeout(processNext, 100)
    }
  }, [processNext])

  /**
   * Proceed to next download in queue (auto-continue without resetting to IDLE)
   */
  const proceedToNext = useCallback(() => {
    setError(null)
    setResult(null)
    isProcessingRef.current = false

    if (queueRef.current.length > 0) {
      processNext()
    } else {
      // Queue empty, reset to idle
      setCurrentDownload(null)
      setPhase(DOWNLOAD_PHASES.IDLE)
      setQueueLength(0)
    }
  }, [processNext])

  const recoverFromError = useCallback((action) => {
    const recovery = recoverFailedDownload({
      phase,
      recoveryAvailable: errorRecoveryAvailableRef.current,
      pending: queueRef.current,
      current: currentDownload
    }, action)
    if (!recovery.accepted) return

    // Claim this failed item before any state update or next request begins so
    // a repeated click cannot retry/skip an already active download.
    errorRecoveryAvailableRef.current = false
    queueRef.current = recovery.pending
    setQueueLength(queueRef.current.length)
    setError(null)
    setResult(null)
    isProcessingRef.current = false

    if (queueRef.current.length > 0) {
      processNext()
    } else {
      setCurrentDownload(null)
      setPhase(DOWNLOAD_PHASES.IDLE)
    }
  }, [currentDownload, phase, processNext])

  /**
   * Retry import with slippi action (after user makes choice)
   * @param {string} action - 'fix' or 'import_as_is'
   * @returns {Promise<Object>} Import result
   */
  const retryWithSlippiAction = useCallback(async (action) => {
    if (!result?.blob) {
      throw new Error('No pending import data')
    }

    setPhase(DOWNLOAD_PHASES.IMPORTING)
    setError(null)

    try {
      const formData = new FormData()
      formData.append('file', result.blob, `${result.downloadName || 'mod'}.zip`)
      formData.append('slippi_action', action)

      if (result.downloadTitle) {
        formData.append('custom_title', result.downloadTitle)
      }
      if (result.downloadType) {
        formData.append('mod_type', result.downloadType)
      }
      if (result.downloadEffectType) {
        formData.append('effect_type', result.downloadEffectType)
      }

      // Include duplicate_action if we already made that choice
      if (result.duplicateAction) {
        formData.append('duplicate_action', result.duplicateAction)
      }

      const importResult = await api.post('/import/file', formData)

      setResult({
        success: true,
        importType: importResult.type,
        cameraSound: importResult.camera_sound === true,
        message: `Successfully imported: ${result.downloadTitle || result.downloadName || 'mod'}`
      })
      setPhase(DOWNLOAD_PHASES.COMPLETE)
      return importResult
    } catch (err) {
      // A duplicate dialog arrives as a { success: false } envelope -> ApiError
      const importResult = err.data

      // Check for duplicate dialog after slippi action (skin might also be a duplicate)
      if (importResult?.type === 'duplicate_dialog') {
        setResult({
          ...importResult,
          needsDuplicateChoice: true,
          blob: result.blob,
          downloadName: result.downloadName,
          downloadTitle: result.downloadTitle,
          downloadType: result.downloadType,
          downloadEffectType: result.downloadEffectType,
          // Preserve slippi action for when we retry with duplicate action
          slippiAction: action
        })
        setPhase(DOWNLOAD_PHASES.COMPLETE)
        return importResult
      }

      console.error('[DownloadQueue] Slippi retry error:', err)
      errorRecoveryAvailableRef.current = true
      setError(err.message)
      setPhase(DOWNLOAD_PHASES.ERROR)
      throw err
    }
  }, [result])

  /**
   * Retry import with duplicate action (after user makes choice)
   * @param {string} action - 'import_anyway'
   * @returns {Promise<Object>} Import result
   */
  const retryWithDuplicateAction = useCallback(async (action) => {
    if (!result?.blob) {
      throw new Error('No pending import data')
    }

    setPhase(DOWNLOAD_PHASES.IMPORTING)
    setError(null)

    try {
      const formData = new FormData()
      formData.append('file', result.blob, `${result.downloadName || 'mod'}.zip`)
      formData.append('duplicate_action', action)

      if (result.downloadTitle) {
        formData.append('custom_title', result.downloadTitle)
      }
      if (result.downloadType) {
        formData.append('mod_type', result.downloadType)
      }
      if (result.downloadEffectType) {
        formData.append('effect_type', result.downloadEffectType)
      }

      // Include slippi_action if we already made that choice (skin was both unsafe AND duplicate)
      if (result.slippiAction) {
        formData.append('slippi_action', result.slippiAction)
      }

      const importResult = await api.post('/import/file', formData)

      setResult({
        success: true,
        importType: importResult.type,
        cameraSound: importResult.camera_sound === true,
        message: `Successfully imported: ${result.downloadTitle || result.downloadName || 'mod'}`
      })
      setPhase(DOWNLOAD_PHASES.COMPLETE)
      return importResult
    } catch (err) {
      // A slippi dialog arrives as a { success: false } envelope -> ApiError
      const importResult = err.data

      // Check for slippi dialog after duplicate action (skin might also be slippi unsafe)
      // This only happens if duplicate was detected first (before slippi check)
      if (importResult?.type === 'slippi_dialog') {
        setResult({
          ...importResult,
          needsSlippiChoice: true,
          blob: result.blob,
          downloadName: result.downloadName,
          downloadTitle: result.downloadTitle,
          downloadType: result.downloadType,
          downloadEffectType: result.downloadEffectType,
          // Preserve duplicate action for when we retry with slippi action
          duplicateAction: action
        })
        setPhase(DOWNLOAD_PHASES.COMPLETE)
        return importResult
      }

      console.error('[DownloadQueue] Duplicate retry error:', err)
      errorRecoveryAvailableRef.current = true
      setError(err.message)
      setPhase(DOWNLOAD_PHASES.ERROR)
      throw err
    }
  }, [result])

  return {
    // State
    currentDownload,
    phase,
    error,
    result,
    isDownloading: phase !== DOWNLOAD_PHASES.IDLE,
    queueLength,

    // Actions
    queueDownload,
    clearDownload,
    proceedToNext,
    recoverFromError,
    retryWithSlippiAction,
    retryWithDuplicateAction
  }
}
