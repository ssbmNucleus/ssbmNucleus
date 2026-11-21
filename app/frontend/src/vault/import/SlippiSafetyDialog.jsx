import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { playSound } from '../../shared/audio/sounds'
import './ImportDialogs.css'

/**
 * Shared dialog component for Slippi safety warnings
 *
 * @param {boolean} show - Whether to show the dialog
 * @param {Object} data - Dialog data with unsafe_costumes array
 * @param {Function} onChoice - Callback for user choice ('fix', 'import_as_is', or 'cancel')
 * @param {boolean} isRetest - Whether this is a retest dialog (affects button labels)
 */
export default function SlippiSafetyDialog({ show, data, onChoice, isRetest = false }) {
  const cancel = () => {
    playSound('back')
    onChoice('cancel')
  }

  useEffect(() => {
    if (!show) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') cancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [show])

  if (!show || !data) return null

  // A zip can carry several costumes, so the old fixed "This costume is not
  // Slippi safe" was wrong as soon as more than one failed.
  const costumes = data.unsafe_costumes || []
  const many = costumes.length > 1

  const dialog = (
    <div className="edit-modal-overlay import-dialog-overlay" onClick={cancel}>
      <div className="edit-modal-content import-dialog" onClick={(e) => e.stopPropagation()}>
        <h2>Slippi Safety Warning</h2>

        <p className="import-dialog-intro">
          {many
            ? `${costumes.length} costumes are not Slippi safe. Choose an action:`
            : 'This costume is not Slippi safe. Choose an action:'}
        </p>

        {costumes.length > 0 && (
          <div className="import-dialog-callout import-dialog-callout-warning">
            <span className="import-dialog-callout-label">
              {many ? 'Affected costumes' : 'Affected costume'}
            </span>
            <ul className="import-dialog-list">
              {costumes.map((costume, idx) => (
                <li key={idx}>{costume.character} - {costume.color}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="import-dialog-actions">
          <button className="btn-save" onClick={() => onChoice('fix')}>
            {isRetest ? 'Fix' : 'Fix & Import'}
          </button>
          <button className="btn-secondary" onClick={() => onChoice('import_as_is')}>
            {isRetest ? 'Keep As-Is' : 'Import As-Is'}
          </button>
          <button className="btn-cancel import-dialog-dismiss" onClick={cancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )

  return createPortal(dialog, document.body)
}
