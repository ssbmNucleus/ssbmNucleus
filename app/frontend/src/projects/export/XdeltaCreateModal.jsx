/**
 * XdeltaCreateModal - Create new XDelta patch
 *
 * Features:
 * - Name and description input
 * - Modded ISO selection
 * - Patch creation with progress tracking
 * - Success confirmation with download option
 */

import { playSound, playHoverSound } from '../../shared/audio/sounds'
import HexagonLoader from '../../shared/ui/HexagonLoader'
import { getProgressMessage } from '../../shared/ui/progressText'
import '../../shared/ui/ExportModal.css'
import '../../shared/ui/ProgressPanel.css'

export default function XdeltaCreateModal({
  show,
  xdeltaCreateState,
  xdeltaCreateData,
  setXdeltaCreateData,
  xdeltaCreateProgress,
  xdeltaCreateMessage,
  xdeltaCreateError,
  xdeltaCreateResult,
  onClose,
  onSelectModdedIso,
  onStartCreate,
  onDownloadPatch
}) {
  if (!show) return null

  return (
    <div className="iso-builder-overlay">
      <div className="iso-builder-modal">
        <div className="modal-header">
          <h2>Create New Patch</h2>
          {xdeltaCreateState !== 'creating' && (
            <button className="close-btn" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); onClose(); }}>×</button>
          )}
        </div>

        <div className="modal-body">
          {xdeltaCreateState === 'idle' && (
            <div className="create-patch-form">
              <p style={{ color: 'var(--color-text-secondary)', marginBottom: '1.5rem' }}>
                Create a patch by comparing a modded ISO against your vanilla ISO.
                The patch can then be shared and applied to recreate the modded ISO.
              </p>

              <div className="edit-field">
                <label>Patch Name:</label>
                <input
                  type="text"
                  value={xdeltaCreateData.name}
                  onChange={(e) => setXdeltaCreateData({ ...xdeltaCreateData, name: e.target.value })}
                  placeholder="My Awesome Mod Pack"
                />
              </div>

              <div className="edit-field">
                <label>Description (optional):</label>
                <textarea
                  value={xdeltaCreateData.description}
                  onChange={(e) => setXdeltaCreateData({ ...xdeltaCreateData, description: e.target.value })}
                  placeholder="Describe what's in this patch..."
                  rows={3}
                />
              </div>

              <div className="edit-field">
                <label>Modded ISO:</label>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <input
                    type="text"
                    value={xdeltaCreateData.moddedIsoPath}
                    onChange={(e) => setXdeltaCreateData({ ...xdeltaCreateData, moddedIsoPath: e.target.value })}
                    placeholder="Select a modded ISO file..."
                    readOnly
                    style={{ flex: 1 }}
                  />
                  <button
                    className="btn-secondary"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); onSelectModdedIso(); }}
                    style={{ whiteSpace: 'nowrap' }}
                  >
                    Browse...
                  </button>
                </div>
              </div>

              <div className="edit-buttons" style={{ marginTop: '1.5rem' }}>
                <button
                  className="btn-save"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('start'); onStartCreate(); }}
                  disabled={!xdeltaCreateData.moddedIsoPath || !xdeltaCreateData.name.trim()}
                >
                  Create Patch
                </button>
                <button className="btn-cancel" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); onClose(); }}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {xdeltaCreateState === 'creating' && (
            <div className="export-progress">
              <HexagonLoader
                className="progress-loader"
                size={120}
                label="Creating patch"
                progress={xdeltaCreateProgress > 0 ? xdeltaCreateProgress : null}
              />
              <div className="hexagon-progress-copy">
                <h3>Creating Patch...</h3>
                <p className="progress-message">
                  {getProgressMessage(xdeltaCreateMessage, 'Comparing ISOs...')}
                </p>
              </div>
            </div>
          )}

          {xdeltaCreateState === 'complete' && xdeltaCreateResult && (
            <div className="export-complete">
              <div className="success-icon">✓</div>
              <h3>Patch Created!</h3>
              <p>Your patch "{xdeltaCreateResult.name}" has been created.</p>
              <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9em' }}>
                Size: {xdeltaCreateResult.size_mb} MB
                {xdeltaCreateResult.size_mb < 25 && (
                  <span style={{ color: 'var(--color-success)', marginLeft: '0.5rem' }}>
                    (Discord-friendly!)
                  </span>
                )}
              </p>
              <div className="complete-actions">
                <button
                  className="btn-download"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); onDownloadPatch(xdeltaCreateResult.patch_id); }}
                >
                  Download Patch
                </button>
                <button className="btn-secondary" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); onClose(); }}>
                  Close
                </button>
              </div>
            </div>
          )}

          {xdeltaCreateState === 'error' && (
            <div className="export-error">
              <div className="error-icon">✕</div>
              <h3>Creation Failed</h3>
              <p className="error-message">{xdeltaCreateError}</p>
              <button className="btn-secondary" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); onClose(); }}>
                Close
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
