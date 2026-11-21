import { useEffect } from 'react'
import { DOWNLOAD_PHASES } from './useDownloadQueue'
import { playSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import HexagonLoader from '../../shared/ui/HexagonLoader'
import './DownloadModal.css'

/**
 * Modal component for showing nucleus:// download progress
 *
 * @param {Object} props
 * @param {Object} props.download - Current download info (url, name, title)
 * @param {string} props.phase - Current phase from DOWNLOAD_PHASES
 * @param {string} props.error - Error message if phase is ERROR
 * @param {Object} props.result - Result object if phase is COMPLETE
 * @param {number} props.queueLength - Number of downloads remaining in queue
 * @param {Function} props.onClose - Callback when modal is dismissed
 * @param {Function} props.onProceedToNext - Callback to proceed to next download
 * @param {Function} props.onSlippiChoice - Callback for slippi safety choice
 * @param {Function} props.onDuplicateChoice - Callback for duplicate skin choice
 */
export default function DownloadModal({
  download,
  phase,
  error,
  result,
  queueLength,
  onClose,
  onProceedToNext,
  onRecoverFromError,
  onSlippiChoice,
  onDuplicateChoice
}) {
  const isProcessing = phase === DOWNLOAD_PHASES.DOWNLOADING || phase === DOWNLOAD_PHASES.IMPORTING
  const canClose = phase === DOWNLOAD_PHASES.COMPLETE || phase === DOWNLOAD_PHASES.ERROR
  const needsSlippiChoice = result?.needsSlippiChoice
  const needsDuplicateChoice = result?.needsDuplicateChoice
  const needsUserChoice = needsSlippiChoice || needsDuplicateChoice

  // Auto-proceed to next download if queue has more items
  useEffect(() => {
    if (phase === DOWNLOAD_PHASES.COMPLETE && !needsUserChoice && queueLength > 0) {
      onProceedToNext()
    }
  }, [phase, needsUserChoice, queueLength, onProceedToNext])

  // Hooks must run on every render, including the idle render.
  if (phase === DOWNLOAD_PHASES.IDLE || !download) {
    return null
  }

  const handleOverlayClick = () => {
    if (canClose && !needsUserChoice && queueLength === 0) {
      playSound('back')
      onClose()
    }
  }

  const handleContentClick = (e) => {
    e.stopPropagation()
  }

  const handleClose = () => {
    playSound('back')
    onClose()
  }

  const handleSlippiChoice = (choice) => {
    if (choice === 'cancel') {
      playSound('back')
      onClose()
    } else {
      onSlippiChoice(choice)
    }
  }

  const handleDuplicateChoice = (choice) => {
    if (choice === 'cancel') {
      playSound('back')
      onClose()
    } else {
      onDuplicateChoice(choice)
    }
  }

  const getStatusText = () => {
    switch (phase) {
      case DOWNLOAD_PHASES.DOWNLOADING:
        return 'Downloading...'
      case DOWNLOAD_PHASES.IMPORTING:
        return 'Importing...'
      case DOWNLOAD_PHASES.COMPLETE:
        if (needsDuplicateChoice) return 'Duplicate Detected'
        if (needsSlippiChoice) return 'Slippi Safety Warning'
        return 'Complete!'
      case DOWNLOAD_PHASES.ERROR:
        return 'Error'
      default:
        return ''
    }
  }

  const displayName = download.title || download.name || 'Mod'

  return (
    <div className="download-modal-overlay" onClick={handleOverlayClick}>
      <div className="download-modal-content" onClick={handleContentClick}>
        {/* Header */}
        <div className="download-modal-header">
          <h3>{needsDuplicateChoice ? 'Duplicate Skin' : needsSlippiChoice ? 'Slippi Safety Warning' : 'Importing Mod'}</h3>
        </div>

        {/* Mod name */}
        <div className="download-modal-name">{displayName}</div>

        {/* Status area */}
        <div className={`download-modal-status ${phase}`}>
          {isProcessing && (
            <HexagonLoader size={56} label="Importing" />
          )}

          {phase === DOWNLOAD_PHASES.COMPLETE && !needsUserChoice && (
            <div className="download-success-icon">&#x2713;</div>
          )}

          {phase === DOWNLOAD_PHASES.ERROR && (
            <div className="download-error-icon">!</div>
          )}

          <span className="download-status-text">{getStatusText()}</span>
        </div>

        {/* Error message */}
        {phase === DOWNLOAD_PHASES.ERROR && error && (
          <div className="download-error-message">{error}</div>
        )}

        {/* Slippi warning content */}
        {needsSlippiChoice && result?.unsafe_costumes && (
          <div className="download-slippi-warning">
            <p>This costume is not Slippi safe. Choose an action:</p>
            <div className="download-slippi-affected">
              <strong>Affected costumes:</strong>
              <ul>
                {result.unsafe_costumes.map((costume, idx) => (
                  <li key={idx}>{costume.character} - {costume.color}</li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {/* Duplicate warning content */}
        {needsDuplicateChoice && result?.duplicate_skins && (
          <div className="download-duplicate-warning">
            <p>You already have this skin!</p>
            {result.duplicate_skins.map((dup, idx) => (
              <div key={idx} className="download-duplicate-preview">
                {dup.existing_skin?.csp_url && (
                  <img
                    src={backendMediaUrl(dup.existing_skin.csp_url)}
                    alt="Existing skin"
                    className="download-duplicate-csp"
                  />
                )}
                <span className="download-duplicate-name">{dup.existing_skin?.name}</span>
              </div>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="download-modal-actions">
          {needsDuplicateChoice ? (
            <>
              <button
                className="download-btn download-btn-primary"
                onClick={() => handleDuplicateChoice('import_anyway')}
              >
                Import Anyway
              </button>
              <button
                className="download-btn download-btn-cancel"
                onClick={() => handleDuplicateChoice('cancel')}
              >
                Cancel
              </button>
            </>
          ) : needsSlippiChoice ? (
            <>
              <button
                className="download-btn download-btn-primary"
                onClick={() => handleSlippiChoice('fix')}
              >
                Fix & Import
              </button>
              <button
                className="download-btn download-btn-secondary"
                onClick={() => handleSlippiChoice('import_as_is')}
              >
                Import As-Is
              </button>
              <button
                className="download-btn download-btn-cancel"
                onClick={() => handleSlippiChoice('cancel')}
              >
                Cancel
              </button>
            </>
          ) : phase === DOWNLOAD_PHASES.ERROR ? (
            <>
              <button className="download-btn download-btn-primary" onClick={() => onRecoverFromError('retry')}>
                Retry
              </button>
              {queueLength > 0 && (
                <button className="download-btn download-btn-secondary" onClick={() => onRecoverFromError('skip')}>
                  Skip &amp; Continue
                </button>
              )}
              {queueLength > 0 ? (
                <button className="download-btn download-btn-cancel" onClick={() => onRecoverFromError('cancel')}>
                  Cancel Remaining
                </button>
              ) : (
                <button className="download-btn download-btn-cancel" onClick={handleClose}>Close</button>
              )}
            </>
          ) : canClose && queueLength === 0 ? (
            <button
              className="download-btn download-btn-close"
              onClick={handleClose}
            >
              Close
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
