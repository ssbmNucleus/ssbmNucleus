import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { playSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import './ImportDialogs.css'

/**
 * Dialog shown when an imported skin already exists in the library.
 *
 * @param {boolean} show - Whether to show the dialog
 * @param {Object} data - Response data with duplicate_skins array
 * @param {Function} onChoice - Callback for user choice ('import_anyway' or 'skip')
 */
export default function DuplicateImportDialog({ show, data, onChoice }) {
  const isSkippedSummary = data?.type === 'skipped_summary'

  const dismiss = () => {
    playSound('back')
    onChoice(isSkippedSummary ? 'close' : 'skip')
  }

  useEffect(() => {
    if (!show) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') dismiss()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [show, isSkippedSummary])

  if (!show || !data) return null

  const duplicates = data.duplicate_skins || []
  const title = isSkippedSummary ? 'Skipped Duplicates'
    : data.mod_type === 'stage' ? 'Duplicate Stage'
    : data.mod_type === 'patch' ? 'Duplicate Patch'
    : data.mod_type === 'effect' ? 'Duplicate Effect'
    : 'Duplicate Skin'

  const intro = isSkippedSummary
    ? `${data.skipped_count || duplicates.length} item(s) matched these existing vault entries and were skipped.`
    : (data.mod_type === 'stage' ? 'You already have this stage.'
      : data.mod_type === 'patch' ? 'You already have this patch.'
      : data.mod_type === 'effect' ? 'You already have this effect.'
      : 'You already own this skin.') + ' What would you like to do?'

  const dialog = (
    <div className="edit-modal-overlay import-dialog-overlay" onClick={dismiss}>
      <div className="edit-modal-content import-dialog" onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>

        <p className="import-dialog-intro">{intro}</p>

        {duplicates.length > 0 && (
          <div className="import-dialog-callout">
            <span className="import-dialog-callout-label">Already in your vault</span>
            <ul className="import-dialog-list">
              {duplicates.map((dup, idx) => (
                <li key={idx} className="import-dialog-entry">
                  <img
                    src={backendMediaUrl(dup.existing_skin.csp_url)}
                    alt=""
                    onError={(e) => { e.target.style.display = 'none' }}
                  />
                  <span>{dup.existing_skin.name}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {isSkippedSummary ? (
          <div className="import-dialog-actions">
            <button className="btn-cancel" onClick={dismiss}>Close</button>
          </div>
        ) : (
          <div className="import-dialog-actions import-dialog-actions-inline">
            <button className="btn-cancel" onClick={dismiss}>Skip</button>
            <button className="btn-save" onClick={() => onChoice('import_anyway')}>Add Anyway</button>
          </div>
        )}
      </div>
    </div>
  )

  return createPortal(dialog, document.body)
}
