/**
 * AdditionalDataSection - Texture pack folder management
 *
 * Features:
 * - Shows texture pack folder size and file count
 * - Clear texture pack button with confirmation dialog
 */
import { useState, useEffect } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { api } from '../shared/transport/api'

function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

export default function AdditionalDataSection() {
  const [textureStats, setTextureStats] = useState(null)
  const [showConfirmModal, setShowConfirmModal] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [message, setMessage] = useState({ text: '', type: '' })

  const slippiPath = localStorage.getItem('slippi_dolphin_path') || ''

  const fetchStats = () => {
    // Fetch texture pack stats
    if (slippiPath) {
      api.get('/texture-pack/stats', { query: { slippiPath } })
        .then(data => {
          setTextureStats(data.stats)
        })
        .catch(err => console.error('Failed to fetch texture pack stats:', err))
    }
  }

  useEffect(() => {
    fetchStats()

    // Poll for updates every 5 seconds
    const interval = setInterval(fetchStats, 5000)
    return () => clearInterval(interval)
  }, [slippiPath])

  const handleClearTexturePack = () => {
    setShowConfirmModal(true)
  }

  const confirmClear = async () => {
    setShowConfirmModal(false)
    setClearing(true)
    setMessage({ text: 'Clearing texture pack...', type: '' })

    try {
      const data = await api.post('/texture-pack/clear', { slippiPath })

      setMessage({ text: `Texture pack cleared! (${data.deletedCount} items removed)`, type: 'success' })
      // Refresh stats
      fetchStats()
      setClearing(false)
    } catch (err) {
      setMessage({ text: `Failed to clear: ${err.message}`, type: 'error' })
      setClearing(false)
    }
  }

  const cancelClear = () => {
    setShowConfirmModal(false)
  }

  return (
    <>
      {/* Main Section */}
      <section className="settings-section">
        <h3>Texture Pack</h3>
        <p className="section-description">
          Clear the texture pack folder when switching between different base ISOs, as texture offsets may not match.
        </p>

        <div className="texture-pack-row">
          <span className="texture-pack-size">
            {textureStats ? (
              textureStats.exists ? (
                <>
                  {formatBytes(textureStats.size)}
                  <span className="data-stat-detail">({textureStats.fileCount} files)</span>
                </>
              ) : (
                <span className="data-stat-empty">Not created yet</span>
              )
            ) : slippiPath ? (
              '...'
            ) : (
              <span className="data-stat-empty">Set Slippi path first</span>
            )}
          </span>
          <button
            className="clear-button"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); handleClearTexturePack(); }}
            disabled={clearing || !slippiPath || !textureStats?.exists}
          >
            {clearing ? 'Clearing...' : 'Clear'}
          </button>
        </div>

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
            <h3>Clear Texture Pack?</h3>
            <p>
              This will delete all Nucleus-managed textures ({textureStats?.fileCount || 0} files, {formatBytes(textureStats?.size || 0)}). Your other textures will not be affected.
            </p>
            <p className="warning-text">
              Clear this when switching to a different base ISO, as texture offsets may not match.
            </p>
            <div className="modal-actions">
              <button className="btn-cancel" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); cancelClear(); }}>
                Cancel
              </button>
              <button className="btn-confirm" onMouseEnter={playHoverSound} onClick={() => { playSound('boop'); confirmClear(); }}>
                Clear Texture Pack
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
