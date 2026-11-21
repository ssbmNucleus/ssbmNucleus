import { useState, useEffect, useRef } from 'react'
import { playSound, playHoverSound, reloadSounds } from '../shared/audio/sounds'
import { api } from '../shared/transport/api'
import HexagonLoader from '../shared/ui/HexagonLoader'
import { getProgressMessage } from '../shared/ui/progressText'
import { ACTIVE } from '../shared/jobs/jobStore'
import { markJobSeen, refreshJob, useJobList } from '../shared/jobs/useJobs'
import { setupJobToShow, setupStep, setupRetryPath } from './setupJob'
import './FirstRunSetup.css'

export default function FirstRunSetup({ onComplete, onCancel = null }) {
  // welcome / select-iso until a setup job exists; then the job's record
  // (core/jobs.py, from the job store) decides the step.
  const [step, setStep] = useState('welcome')
  const [isoPath, setIsoPath] = useState('')
  const [error, setError] = useState(null)
  const [autoDetecting, setAutoDetecting] = useState(true)
  const [autoDetectedPaths, setAutoDetectedPaths] = useState(null)
  const [starting, setStarting] = useState(false)
  const [startedId, setStartedId] = useState(null)
  const [dismissedId, setDismissedId] = useState(null)
  const [appliedId, setAppliedId] = useState(null)
  const endedRef = useRef(null)
  const job = setupJobToShow(useJobList(), { startedId, dismissedId })

  // A setup that ended: save its ISO path before Get Started can show, or
  // sound its failure. Once per job, wherever the wizard was when it ended.
  useEffect(() => {
    if (!job || ACTIVE.has(job.status) || endedRef.current === job.id) return
    endedRef.current = job.id
    if (job.status === 'done') {
      if (job.result?.isoPath) localStorage.setItem('vanilla_iso_path', job.result.isoPath)
      reloadSounds()
      setAppliedId(job.id)
    } else {
      playSound('error')
    }
  }, [job])

  // Auto-detect Slippi and ISO paths on mount
  useEffect(() => {
    const autoDetect = async () => {
      try {
        console.log('[FirstRunSetup] Starting auto-detection...')
        const data = await api.get('/setup/auto-detect')

        console.log('[FirstRunSetup] Auto-detect result:', data)

        setAutoDetectedPaths(data)

        // If ISO path found, pre-fill it
        if (data.isoPath) {
          setIsoPath(data.isoPath)
        }

        // Save Slippi path if found
        if (data.slippiPath) {
          localStorage.setItem('slippi_dolphin_path', data.slippiPath)
          window.dispatchEvent(new Event('nucleus:slippi-dolphin-path'))  // the MCP mirror (randall/assistant/mcpAccount.js)
          console.log('[FirstRunSetup] Saved Slippi path:', data.slippiPath)
        }

        // Save ISO folder path for later use
        if (data.isoFolderPath) {
          localStorage.setItem('dolphin_iso_folder_path', data.isoFolderPath)
          console.log('[FirstRunSetup] Saved ISO folder path:', data.isoFolderPath)
        }
      } catch (err) {
        console.log('[FirstRunSetup] Auto-detect failed, continuing with manual setup:', err)
      } finally {
        setAutoDetecting(false)
      }
    }

    autoDetect()
  }, [])

  const handleBrowseIso = async () => {
    if (!window.electron) {
      playSound('error')
      setError('Electron API not available')
      return
    }

    try {
      const selectedPath = await window.electron.openIsoDialog()
      if (selectedPath) {
        setIsoPath(selectedPath)
      }
    } catch (err) {
      playSound('error')
      setError(`Error selecting file: ${err.message}`)
    }
  }

  const handleStartSetup = async () => {
    if (!isoPath) {
      playSound('error')
      setError('Please select an ISO file')
      return
    }

    playSound('start')
    setError(null)
    setStarting(true)
    try {
      // The backend verifies and extracts in a job; the store reports it.
      const data = await api.post('/setup/start', { isoPath })
      setStartedId(data.jobId)
      refreshJob(data.jobId).catch(() => {})
    } catch (err) {
      if (err.status === 409 && err.data?.jobId) {
        // A setup is already running: show that one instead of failing.
        setStartedId(err.data.jobId)
      } else {
        playSound('error')
        setStep('error')
        // A backend envelope (err.data) reported the failure itself; anything else
        // (network/transport) keeps the old "Failed to start setup" wording.
        setError(err.data ? (err.message || 'Setup failed') : `Failed to start setup: ${err.message}`)
      }
    } finally {
      setStarting(false)
    }
  }

  // The user has seen how this setup ended; a reopened wizard starts fresh.
  const leaveJob = () => {
    if (!job || ACTIVE.has(job.status)) return
    markJobSeen(job.id).catch(() => {})
    setDismissedId(job.id)
  }

  const handleComplete = () => {
    playSound('start')
    leaveJob()
    onComplete()
  }

  const handleRetry = () => {
    leaveJob()
    setStartedId(null)
    setStep('welcome')
    // Welcome shows a detected ISO with Continue; Start must submit that same path.
    setIsoPath(setupRetryPath(autoDetectedPaths))
    setError(null)
  }

  const handleCancel = () => {
    if (!onCancel) {
      return
    }

    playSound('back')
    onCancel()
  }

  // Until the store has the job just started, it is still verifying.
  const shownStep = setupStep(job, appliedId) || (starting || startedId ? 'verifying' : step)
  const progressPercentage = Math.max(0, Math.min(Math.round((job?.progress || 0) * 100), 100))
  const progressMessage = job?.detail || ''
  const result = job?.status === 'done' ? job.result || {} : null
  const errorMessage = job && !ACTIVE.has(job.status) && job.status !== 'done'
    ? job.error || 'Setup failed' : error

  // Render different steps
  const renderWelcome = () => {
    // Show loading spinner while auto-detecting
    if (autoDetecting) {
      return (
        <div className="setup-step">
          <HexagonLoader size={72} className="setup-loader" decorative />
          <h2>Welcome to SSBM Nucleus</h2>
          <p className="setup-description">
            Detecting your Slippi Dolphin installation...
          </p>
        </div>
      )
    }

    // Check what was auto-detected
    const hasSlippi = autoDetectedPaths?.slippiPath
    const hasIso = autoDetectedPaths?.isoPath

    // ISO found - streamlined flow
    if (hasIso) {
      return (
        <div className="setup-step">
          <div className="setup-icon success">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
          </div>
          <h2>Welcome to SSBM Nucleus</h2>
          <p className="setup-description">
            We found your Melee ISO and Slippi Dolphin installation.
          </p>
          <div className="auto-detected-paths">
            <div className="detected-path">
              <span className="detected-label">Melee ISO:</span>
              <span className="detected-value">{autoDetectedPaths.isoPath}</span>
            </div>
            {hasSlippi && (
              <div className="detected-path">
                <span className="detected-label">Slippi Dolphin:</span>
                <span className="detected-value">{autoDetectedPaths.slippiPath}</span>
              </div>
            )}
          </div>
          <div className="setup-buttons">
            <button className="btn-secondary" onClick={() => {
              setAutoDetectedPaths(null)
              setIsoPath('')
            }}>
              Use Different ISO
            </button>
            <button className="btn-primary" onClick={handleStartSetup}>
              Continue with Setup
            </button>
          </div>
        </div>
      )
    }

    // Only Slippi found - need ISO selection
    if (hasSlippi && !hasIso) {
      return (
        <div className="setup-step">
          <div className="setup-icon">
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/>
              <path d="M2 17l10 5 10-5"/>
              <path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <h2>Welcome to SSBM Nucleus</h2>
          <p className="setup-description">
            We found your Slippi Dolphin installation, but we need you to locate your Melee ISO.
          </p>
          <div className="auto-detected-paths">
            <div className="detected-path">
              <span className="detected-label">Slippi Dolphin:</span>
              <span className="detected-value">{autoDetectedPaths.slippiPath}</span>
            </div>
          </div>
          {autoDetectedPaths.isoProblem && (
            <div className="setup-error">{autoDetectedPaths.isoProblem}</div>
          )}
          <p className="setup-description">
            You'll need to provide your own <strong>vanilla Super Smash Bros. Melee 1.02 (NTSC) ISO</strong>.
            This is typically named <code>GALE01</code>.
          </p>
          <div className="setup-note">
            <strong>Note:</strong> Only the original, unmodified Melee 1.02 ISO will work.
            Modified or other region ISOs won't be accepted.
          </div>
          <button className="btn-primary" onClick={() => setStep('select-iso')}>
            Select ISO
          </button>
        </div>
      )
    }

    // Nothing found - full manual flow
    return (
      <div className="setup-step">
        <div className="setup-icon">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/>
            <path d="M2 17l10 5 10-5"/>
            <path d="M2 12l10 5 10-5"/>
          </svg>
        </div>
        <h2>Welcome to SSBM Nucleus</h2>
        <p className="setup-description">
          Before you can use Nucleus, we need to set up the vanilla Melee assets.
          This is required for legal reasons - we can't distribute copyrighted game files.
        </p>
        <p className="setup-description">
          You'll need to provide your own <strong>vanilla Super Smash Bros. Melee 1.02 (NTSC) ISO</strong>.
          This is typically named <code>GALE01</code>.
        </p>
        <div className="setup-note">
          <strong>Note:</strong> Only the original, unmodified Melee 1.02 ISO will work.
          Modified or other region ISOs won't be accepted.
        </div>
        <button className="btn-primary" onClick={() => setStep('select-iso')}>
          Get Started
        </button>
      </div>
    )
  }

  const renderSelectIso = () => (
    <div className="setup-step">
      <h2>Select Your Melee ISO</h2>
      <p className="setup-description">
        Browse to your vanilla Melee 1.02 (NTSC) ISO file.
      </p>

      <div className="iso-selector">
        <input
          type="text"
          value={isoPath}
          placeholder="No file selected..."
          readOnly
          className="iso-path-input"
        />
        <button className="btn-secondary" onClick={handleBrowseIso}>
          Browse...
        </button>
      </div>

      {error && (
        <div className="setup-error">
          {error}
        </div>
      )}

      <div className="setup-buttons">
        <button className="btn-secondary" onClick={() => setStep('welcome')}>
          Back
        </button>
        <button
          className="btn-primary"
          onClick={handleStartSetup}
          disabled={!isoPath}
        >
          Start Setup
        </button>
      </div>
    </div>
  )

  const renderVerifying = () => (
    <div className="setup-step">
      <HexagonLoader size={72} className="setup-loader" decorative />
      <h2>Verifying ISO</h2>
      <p className="setup-description">
        Checking that this is a valid vanilla Melee 1.02 ISO...
      </p>
    </div>
  )

  const renderExtracting = () => (
    <div className="setup-step">
      <HexagonLoader
        size={104}
        className="setup-loader"
        progress={progressPercentage}
        label="Extracting ISO"
      />
      <h2>Extracting ISO</h2>
      <p className="setup-description">
        {getProgressMessage(progressMessage, 'Extracting game files... This may take 1-2 minutes.')}
      </p>
    </div>
  )

  const renderCopying = () => (
    <div className="setup-step">
      <HexagonLoader
        size={104}
        className="setup-loader"
        progress={progressPercentage}
        label="Copying assets"
      />
      <h2>Copying Assets</h2>
      <p className="setup-description">
        {getProgressMessage(progressMessage, 'Copying character and stage assets...')}
      </p>
    </div>
  )

  const renderComplete = () => (
    <div className="setup-step">
      <div className="setup-icon success">
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
          <polyline points="22 4 12 14.01 9 11.01"/>
        </svg>
      </div>
      <h2>Setup Complete!</h2>
      <p className="setup-description">
        {result?.message || 'All vanilla assets have been extracted. You can now use SSBM Nucleus!'}
      </p>
      <button className="btn-primary" onClick={handleComplete}>
        Get Started
      </button>
    </div>
  )

  const renderError = () => (
    <div className="setup-step">
      <div className="setup-icon error">
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="15" y1="9" x2="9" y2="15"/>
          <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
      </div>
      <h2>Setup Failed</h2>
      <p className="setup-description error-text">
        {errorMessage || 'An unknown error occurred during setup.'}
      </p>
      <div className="setup-buttons">
        <button className="btn-primary" onClick={handleRetry}>
          Try Again
        </button>
      </div>
    </div>
  )

  return (
    <div className="first-run-overlay">
      <div className="first-run-modal">
        <div className="first-run-modal-surface">
          <div className="first-run-header">
            <div className="first-run-header-brand">
              <img src="./nucleuslogo.svg" alt="SSBM Nucleus" className="first-run-logo" />
              <h1>First-Time Setup</h1>
            </div>
            {onCancel && (
              <button
                type="button"
                className="btn-secondary first-run-cancel-button"
                onMouseEnter={playHoverSound}
                onClick={handleCancel}
              >
                Back to Settings
              </button>
            )}
          </div>

          <div className="first-run-content">
            {shownStep === 'welcome' && renderWelcome()}
            {shownStep === 'select-iso' && renderSelectIso()}
            {shownStep === 'verifying' && renderVerifying()}
            {shownStep === 'extracting' && renderExtracting()}
            {shownStep === 'copying' && renderCopying()}
            {shownStep === 'complete' && renderComplete()}
            {shownStep === 'error' && renderError()}
          </div>

          <div className="first-run-footer">
            <div className="step-indicator">
              <div className={`step-dot ${['welcome', 'select-iso', 'verifying', 'extracting', 'copying', 'complete'].indexOf(shownStep) >= 0 ? 'active' : ''}`}></div>
              <div className={`step-dot ${['select-iso', 'verifying', 'extracting', 'copying', 'complete'].indexOf(shownStep) >= 0 ? 'active' : ''}`}></div>
              <div className={`step-dot ${['verifying', 'extracting', 'copying', 'complete'].indexOf(shownStep) >= 0 ? 'active' : ''}`}></div>
              <div className={`step-dot ${['extracting', 'copying', 'complete'].indexOf(shownStep) >= 0 ? 'active' : ''}`}></div>
              <div className={`step-dot ${['copying', 'complete'].indexOf(shownStep) >= 0 ? 'active' : ''}`}></div>
              <div className={`step-dot ${shownStep === 'complete' ? 'active' : ''}`}></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
