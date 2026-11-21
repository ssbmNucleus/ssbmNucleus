/**
 * SlippiPathSection - Slippi Dolphin path management
 *
 * Features:
 * - Browse for Slippi Dolphin netplay folder
 * - Verify path against expected structure
 * - Display derived Dump/Load paths
 * - Persist path to localStorage
 */
import { useState, useEffect } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { api } from '../shared/transport/api'

export default function SlippiPathSection({}) {
  const [slippiDolphinPath, setSlippiDolphinPath] = useState('')
  const [slippiMessage, setSlippiMessage] = useState({ text: '', type: '' })
  const [slippiVerified, setSlippiVerified] = useState(null)
  const [verifyingSlippi, setVerifyingSlippi] = useState(false)

  // Load Slippi Dolphin path from localStorage on mount and verify it
  useEffect(() => {
    const savedPath = localStorage.getItem('slippi_dolphin_path')
    if (savedPath) {
      setSlippiDolphinPath(savedPath)
      // Verify on load
      verifySlippiPath(savedPath)
    }
  }, [])

  const verifySlippiPath = async (slippiPath) => {
    setVerifyingSlippi(true)
    setSlippiVerified(null)

    try {
      const data = await api.post('/settings/slippi-path/verify', { slippiPath })

      setSlippiVerified(data.valid)
      if (!data.valid) {
        setSlippiMessage({
          text: data.error || 'Invalid Slippi Dolphin path',
          type: 'error'
        })
      }
    } catch (err) {
      setSlippiVerified(false)
      setSlippiMessage({ text: `Verification failed: ${err.message}`, type: 'error' })
    } finally {
      setVerifyingSlippi(false)
    }
  }

  const handleBrowseSlippi = async () => {
    if (!window.electron) {
      setSlippiMessage({ text: 'Electron API not available', type: 'error' })
      return
    }

    try {
      const selectedPath = await window.electron.selectDirectory()
      if (selectedPath) {
        setSlippiDolphinPath(selectedPath)
        setSlippiMessage({ text: 'Verifying path...', type: '' })

        // Verify the path
        setVerifyingSlippi(true)
        const data = await api.post('/settings/slippi-path/verify', { slippiPath: selectedPath })

        if (data.valid) {
          localStorage.setItem('slippi_dolphin_path', selectedPath)
          window.dispatchEvent(new Event('nucleus:slippi-dolphin-path'))  // the MCP mirror (randall/assistant/mcpAccount.js)
          setSlippiVerified(true)
          setSlippiMessage({ text: 'Valid Slippi Dolphin path!', type: 'success' })
          setTimeout(() => setSlippiMessage({ text: '', type: '' }), 3000)
        } else {
          setSlippiVerified(false)
          setSlippiMessage({
            text: data.error || 'Invalid path. Please select the Slippi netplay folder.',
            type: 'error'
          })
          // Don't save invalid path
          setSlippiDolphinPath('')
        }
        setVerifyingSlippi(false)
      }
    } catch (err) {
      if (err.data) {
        // backend answered success:false — the old code treated that like an
        // invalid path: report it and don't keep the path
        setSlippiVerified(false)
        setSlippiMessage({ text: err.message || 'Invalid path. Please select the Slippi netplay folder.', type: 'error' })
        setSlippiDolphinPath('')
      } else {
        setSlippiMessage({ text: `Error: ${err.message}`, type: 'error' })
      }
      setVerifyingSlippi(false)
    }
  }

  const handleClearSlippiPath = () => {
    localStorage.removeItem('slippi_dolphin_path')
    window.dispatchEvent(new Event('nucleus:slippi-dolphin-path'))  // the MCP mirror (randall/assistant/mcpAccount.js)
    setSlippiDolphinPath('')
    setSlippiVerified(null)
    setSlippiMessage({ text: 'Slippi Dolphin path cleared', type: 'success' })
    setTimeout(() => setSlippiMessage({ text: '', type: '' }), 3000)
  }

  return (
    <section className="settings-section">
      <h3>Slippi Dolphin</h3>
      <p className="section-description">
        Set the path to your Slippi Dolphin netplay folder for texture pack generation.
        <br />
        <span className="path-hint">
          {navigator.platform?.startsWith('Win')
            ? 'Example: C:\\Users\\[you]\\AppData\\Roaming\\Slippi Launcher\\netplay'
            : 'Example: ~/.config/Slippi Launcher/netplay'}
        </span>
      </p>

      <div className="iso-path-container">
        {slippiDolphinPath ? (
          <div className={`iso-path-display ${slippiVerified === true ? 'verified' : slippiVerified === false ? 'invalid' : ''}`}>
            <span className="iso-status-icon">
              {verifyingSlippi ? '...' : slippiVerified === true ? '✓' : slippiVerified === false ? '✕' : '?'}
            </span>
            <span className="iso-path-text" title={slippiDolphinPath}>{slippiDolphinPath}</span>
            <button
              className="iso-clear-button"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); handleClearSlippiPath(); }}
              title="Clear Slippi path"
            >
              ×
            </button>
          </div>
        ) : (
          <div className="iso-path-empty">No Slippi Dolphin path set</div>
        )}
        <button
          className="iso-browse-button"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); handleBrowseSlippi(); }}
          disabled={verifyingSlippi}
        >
          {verifyingSlippi ? 'Verifying...' : slippiDolphinPath ? 'Change' : 'Browse'}
        </button>
      </div>

      {slippiVerified && slippiDolphinPath && (
        <div className="derived-paths">
          <div className="derived-path">
            <span className="derived-label">Dump:</span>
            <span className="derived-value">{slippiDolphinPath}/User/Dump/Textures/GALE01</span>
          </div>
          <div className="derived-path">
            <span className="derived-label">Load:</span>
            <span className="derived-value">{slippiDolphinPath}/User/Load/Textures/GALE01</span>
          </div>
        </div>
      )}

      {slippiMessage.text && (
        <div className={`message ${slippiMessage.type}`}>
          {slippiMessage.text}
        </div>
      )}
    </section>
  )
}
