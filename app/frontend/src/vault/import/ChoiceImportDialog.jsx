import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import './ImportDialogs.css'

/**
 * Dialog shown when the unified importer cannot tell what an upload is (a
 * lone picture, a whole MnSlChr, an effect file with no vanilla ISO to diff
 * against). The backend lists the plausible kinds; picking one re-sends the
 * same file with that option's hints.
 *
 * @param {boolean} show
 * @param {Object} data - { filename, question, options: [{key, label, description, hints}], default }
 * @param {Function} onChoice - (optionKey | null) => void  (null = cancel)
 */
export default function ChoiceImportDialog({ show, data, onChoice }) {
  const cancel = () => {
    playSound('back')
    onChoice(null)
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

  const dialog = (
    <div className="edit-modal-overlay import-dialog-overlay" onClick={cancel}>
      <div className="edit-modal-content import-dialog" onClick={(e) => e.stopPropagation()}>
        <h2>What is this?</h2>

        {data.filename && <p className="import-dialog-filename">{data.filename}</p>}
        <p className="import-dialog-intro">{data.question}</p>

        <div className="import-dialog-actions">
          {(data.options || []).map((opt) => (
            <button
              key={opt.key}
              className={`${opt.key === data.default ? 'btn-save' : 'btn-secondary'} import-dialog-option`}
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); onChoice(opt.key) }}
            >
              <span>{opt.label}</span>
              {opt.description && (
                <span className="import-dialog-option-note">{opt.description}</span>
              )}
            </button>
          ))}

          <button className="btn-cancel import-dialog-dismiss" onClick={cancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )

  return createPortal(dialog, document.body)
}
