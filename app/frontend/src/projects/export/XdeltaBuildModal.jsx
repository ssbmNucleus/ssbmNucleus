/**
 * XdeltaBuildModal - Build ISO from XDelta patch
 *
 * Features:
 * - Progress tracking for build process
 * - Success state with download button
 * - Error handling
 */

import { playSound, playHoverSound } from '../../shared/audio/sounds'
import HexagonLoader from '../../shared/ui/HexagonLoader'
import { getProgressMessage } from '../../shared/ui/progressText'
import '../../shared/ui/ExportModal.css'
import '../../shared/ui/ProgressPanel.css'

export default function XdeltaBuildModal({
  show,
  xdeltaBuildState,
  xdeltaBuildPatch,
  xdeltaBuildProgress,
  xdeltaBuildMessage,
  xdeltaBuildFilename,
  xdeltaBuildError,
  onClose,
  onDownload
}) {
  if (!show) return null

  return (
    <div className="iso-builder-overlay">
      <div className="iso-builder-modal">
        <div className="modal-header">
          <h2>Build ISO</h2>
          {xdeltaBuildState !== 'building' && (
            <button className="close-btn" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); onClose(); }}>×</button>
          )}
        </div>

        <div className="modal-body">
          {xdeltaBuildState === 'building' && (
            <div className="export-progress">
              <HexagonLoader
                className="progress-loader"
                size={120}
                label="Building ISO"
                progress={xdeltaBuildProgress > 0 ? xdeltaBuildProgress : null}
              />
              <div className="hexagon-progress-copy">
                <h3>Building ISO...</h3>
                <p className="progress-message">
                  {getProgressMessage(xdeltaBuildMessage, `Applying patch: ${xdeltaBuildPatch?.name}`)}
                </p>
              </div>
            </div>
          )}

          {xdeltaBuildState === 'complete' && (
            <div className="export-complete">
              <div className="success-icon">✓</div>
              <h3>Build Complete!</h3>
              <p>Your patched ISO is ready to download.</p>
              <div className="complete-actions">
                <button className="btn-download" onMouseEnter={playHoverSound} onClick={() => { playSound('boop'); onDownload(); }}>
                  Download {xdeltaBuildFilename}
                </button>
                <button className="btn-secondary" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); onClose(); }}>
                  Close
                </button>
              </div>
            </div>
          )}

          {xdeltaBuildState === 'error' && (
            <div className="export-error">
              <div className="error-icon">✕</div>
              <h3>Build Failed</h3>
              <p className="error-message">{xdeltaBuildError}</p>
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
