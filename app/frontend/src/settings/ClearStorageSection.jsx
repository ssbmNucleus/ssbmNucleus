/**
 * ClearStorageSection - Clear all vault storage functionality
 *
 * Features:
 * - Clear all character costumes and stage variants
 * - Confirmation modal with item counts
 * - Success/error messaging
 * - Page reload after successful clear
 */
import { useState } from 'react'
import { getStorageStats } from './StorageStatsSection'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { api } from '../shared/transport/api'
import { useActiveJob } from '../shared/jobs/useJobs'

export default function ClearStorageSection({ metadata }) {
  const [showConfirmModal, setShowConfirmModal] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [message, setMessage] = useState({ text: '', type: '' })
  // The backend refuses too; this just keeps the button honest.
  const restoring = Boolean(useActiveJob('vault_restore'))

  const stats = getStorageStats(metadata)

  const handleClearStorage = () => {
    setShowConfirmModal(true)
  }

  const confirmClear = async () => {
    setShowConfirmModal(false)
    setClearing(true)
    setMessage({ text: 'Clearing storage...', type: '' })

    try {
      await api.post('/storage/clear', {})

      setMessage({ text: 'Storage cleared successfully!', type: 'success' })
      // Reload page after 1.5 seconds to refresh metadata
      setTimeout(() => {
        window.location.reload()
      }, 1500)
    } catch (err) {
      setMessage({ text: `Failed to clear storage: ${err.message}`, type: 'error' })
      setClearing(false)
    }
  }

  const cancelClear = () => {
    setShowConfirmModal(false)
  }

  return (
    <>
      {/* Main Section */}
      <section className="settings-section clear-storage-section">
        <h3>Clear Storage</h3>
        <p className="section-description">
          Remove all character costumes and stage variants from storage. This action cannot be undone.
        </p>

        <button
          className="clear-button"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); handleClearStorage(); }}
          disabled={clearing || restoring}
          title={restoring ? 'A Vault restore is running' : undefined}
        >
          {clearing ? 'Clearing...' : 'Clear Storage'}
        </button>

        {message.text && (
          <div className={`message ${message.type}`}>
            {message.text}
          </div>
        )}
      </section>

      {/* Confirmation Modal */}
      {showConfirmModal && (
        <div className="modal-overlay" onClick={cancelClear}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Confirm Clear Storage</h3>
            <p>
              Are you sure you want to clear all storage? This will remove:
            </p>
            <ul>
              <li>All character costumes ({stats.costumeCount} items)</li>
              <li>All stage variants ({stats.stageCount} items)</li>
              <li>Storage metadata</li>
            </ul>
            <p className="warning-text">
              This action cannot be undone!
            </p>
            <div className="modal-actions">
              <button className="btn-cancel" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); cancelClear(); }}>
                Cancel
              </button>
              <button className="btn-confirm" onMouseEnter={playHoverSound} onClick={() => { playSound('boop'); confirmClear(); }}>
                Clear Storage
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
