import { playSound } from '../audio/sounds'
import { createPortal } from 'react-dom'
import './ConfirmDialog.css'

/**
 * Reusable confirmation dialog component
 *
 * @param {boolean} show - Whether to show the dialog
 * @param {string} title - Dialog title
 * @param {string} message - Confirmation message
 * @param {string} confirmText - Text for confirm button (default: "Delete")
 * @param {string} cancelText - Text for cancel button (default: "Cancel")
 * @param {string} confirmStyle - Style variant for confirm button: 'danger' | 'primary' (default: 'danger')
 * @param {Function} onConfirm - Callback when user confirms
 * @param {Function} onCancel - Callback when user cancels
 */
export default function ConfirmDialog({
  show,
  title = 'Confirm',
  message,
  confirmText = 'Delete',
  cancelText = 'Cancel',
  confirmStyle = 'danger',
  closeOnOverlayClick = false,
  overlayClassName = '',
  onConfirm,
  onCancel
}) {
  if (!show) return null

  const handleOverlayClick = (e) => {
    if (!closeOnOverlayClick) {
      e.stopPropagation()
      return
    }
    playSound('back')
    onCancel()
  }

  const handleContentClick = (e) => {
    e.stopPropagation()
  }

  const handleConfirm = () => {
    playSound('back')
    onConfirm()
  }

  const handleCancel = () => {
    playSound('back')
    onCancel()
  }

  const dialog = (
    <div className={`edit-modal-overlay confirm-dialog-overlay ${overlayClassName}`} onClick={handleOverlayClick}>
      <div className="edit-modal-content confirm-dialog-content" onClick={handleContentClick}>
        <h2>{title}</h2>

        <div className="confirm-dialog-message">
          <p>{message}</p>
        </div>

        <div className="confirm-dialog-buttons">
          <button
            className="btn-cancel"
            onClick={handleCancel}
          >
            {cancelText}
          </button>
          <button
            className={confirmStyle === 'danger' ? 'btn-danger' : 'btn-save'}
            onClick={handleConfirm}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )

  return createPortal(dialog, document.body)
}
