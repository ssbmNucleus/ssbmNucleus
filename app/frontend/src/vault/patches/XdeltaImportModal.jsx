/**
 * XdeltaImportModal - Modal for importing XDelta patches and .ssbm bundles
 */
import { useState, useEffect } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import HexagonLoader from '../../shared/ui/HexagonLoader'
import { getProgressMessage } from '../../shared/ui/progressText'
import '../../shared/ui/ProgressPanel.css'

export default function XdeltaImportModal({
  show,
  importData,
  onImportDataChange,
  importing,
  onImport,
  onCancel,
  // Bundle-specific props
  bundlePreview,
  bundleImporting,
  bundleProgress,
  bundleMessage,
  bundleComplete,
  bundleError,
  bundleResult,
  onBundleImport,
  onBundlePreview,
  onBundleReset
}) {
  const [fileType, setFileType] = useState(null) // 'xdelta' or 'ssbm'

  // Reset file type when modal closes
  useEffect(() => {
    if (!show) {
      setFileType(null)
    }
  }, [show])

  if (!show) return null

  const handleOverlayClick = () => {
    if (!importing && !bundleImporting) {
      playSound('back')
      onCancel()
    }
  }

  const handleContentClick = (e) => {
    e.stopPropagation()
  }

  const handleFileChange = async (e) => {
    const file = e.target.files[0]
    if (!file) return

    const ext = file.name.toLowerCase().split('.').pop()

    if (ext === 'ssbm') {
      setFileType('ssbm')
      onImportDataChange({
        ...importData,
        file,
        name: file.name.replace('.ssbm', '')
      })
      // Preview the bundle
      if (onBundlePreview) {
        onBundlePreview(file)
      }
    } else if (ext === 'xdelta') {
      setFileType('xdelta')
      onImportDataChange({
        ...importData,
        file,
        name: importData.name || file.name.replace('.xdelta', '')
      })
      // Reset bundle preview if switching from ssbm
      if (onBundleReset) {
        onBundleReset()
      }
    }
  }

  const handleCancel = () => {
    playSound('back')
    if (onBundleReset) {
      onBundleReset()
    }
    onCancel()
  }

  const handleImport = () => {
    playSound('start')
    if (fileType === 'ssbm') {
      onBundleImport()
    } else {
      onImport()
    }
  }

  // Bundle import/install in progress
  if (bundleImporting) {
    const isInstalling = bundleProgress > 0 || bundleMessage?.includes('ISO') || bundleMessage?.includes('texture')
    return (
      <div className="edit-modal-overlay" onClick={handleOverlayClick}>
        <div className="edit-modal-content" onClick={handleContentClick}>
          <h2>{isInstalling ? 'Installing Mod Bundle' : 'Importing Bundle'}</h2>

          <div className="export-progress" style={{ paddingBottom: 0 }}>
            <HexagonLoader
              className="progress-loader"
              size={112}
              label={isInstalling ? 'Installing bundle' : 'Importing bundle'}
              progress={bundleProgress > 0 ? bundleProgress : null}
            />
            <div className="hexagon-progress-copy">
              <h3>{isInstalling ? 'Installing files...' : 'Importing bundle...'}</h3>
              <p className="progress-message">
                {getProgressMessage(bundleMessage, isInstalling ? 'Installing...' : 'Importing...')}
              </p>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Bundle import/install complete
  if (bundleComplete && bundleResult) {
    const isInstall = !bundleResult.saved
    return (
      <div className="edit-modal-overlay" onClick={handleOverlayClick}>
        <div className="edit-modal-content" onClick={handleContentClick}>
          <h2 style={{ color: 'var(--color-success)' }}>
            {isInstall ? 'Installation Complete!' : 'Bundle Imported!'}
          </h2>

          <div style={{ textAlign: 'center', padding: '1rem 0' }}>
            <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>✓</div>
            <p style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>
              <strong>{bundleResult.name}</strong> {isInstall ? 'is ready to play!' : 'saved to storage'}
            </p>
            {isInstall && bundleResult.texture_count > 0 && (
              <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem' }}>
                {bundleResult.texture_count} textures installed
              </p>
            )}
            <p style={{
              color: 'var(--color-text-secondary)',
              fontSize: '0.85rem',
              marginTop: '1rem',
              padding: '0.75rem',
              background: 'var(--color-bg-surface)',
              borderRadius: 'var(--radius-md)'
            }}>
              {isInstall
                ? 'Launch Slippi Dolphin and select the ISO to start playing!'
                : 'Click "Install" on the bundle to build the ISO and copy textures.'}
            </p>
          </div>

          <div className="edit-buttons">
            <button className="btn-save" onMouseEnter={playHoverSound} onClick={() => { playSound('boop'); if (onBundleReset) onBundleReset(); onCancel(); }}>
              Done
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Bundle import error
  if (bundleError) {
    return (
      <div className="edit-modal-overlay" onClick={handleOverlayClick}>
        <div className="edit-modal-content" onClick={handleContentClick}>
          <h2 style={{ color: 'var(--color-error)' }}>Installation Failed</h2>

          <div style={{ textAlign: 'center', padding: '1rem 0' }}>
            <div style={{ fontSize: '3rem', marginBottom: '1rem', color: 'var(--color-error)' }}>✕</div>
            <p style={{ color: 'var(--color-error)' }}>{bundleError}</p>
          </div>

          <div className="edit-buttons">
            <button className="btn-cancel" onMouseEnter={playHoverSound} onClick={handleCancel}>
              Close
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Bundle preview mode
  if (fileType === 'ssbm' && bundlePreview) {
    return (
      <div className="edit-modal-overlay" onClick={handleOverlayClick}>
        <div className="edit-modal-content" onClick={handleContentClick}>
          <h2>Import Mod Bundle</h2>

          <div className="bundle-preview" style={{
            background: 'var(--color-bg-surface)',
            padding: '1rem',
            borderRadius: 'var(--radius-md)',
            marginBottom: '1rem'
          }}>
            <h3 style={{ marginBottom: '0.5rem', color: 'var(--color-text-primary)' }}>
              {bundlePreview.manifest?.name || 'Unknown Bundle'}
            </h3>
            {bundlePreview.manifest?.description && (
              <p style={{ color: 'var(--color-text-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem' }}>
                {bundlePreview.manifest.description}
              </p>
            )}
            <div style={{ display: 'flex', gap: '1rem', fontSize: '0.85rem', color: 'var(--color-text-muted)' }}>
              <span>Textures: {bundlePreview.texture_count || 0}</span>
              {bundlePreview.manifest?.created && (
                <span>Created: {new Date(bundlePreview.manifest.created).toLocaleDateString()}</span>
              )}
            </div>
          </div>

          <p style={{
            color: 'var(--color-text-secondary)',
            fontSize: '0.9rem',
            marginBottom: '1rem',
            padding: '0.75rem',
            background: 'var(--color-bg-elevated)',
            borderRadius: 'var(--radius-md)'
          }}>
            This will save the bundle to your library. You can install it later by clicking "Install" on the bundle.
          </p>

          <div className="edit-buttons">
            <button
              className="btn-save"
              onMouseEnter={playHoverSound}
              onClick={handleImport}
              disabled={bundleImporting}
            >
              {bundleImporting ? 'Importing...' : 'Import'}
            </button>
            <button
              className="btn-cancel"
              onMouseEnter={playHoverSound}
              onClick={handleCancel}
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Default: file selection view
  return (
    <div className="edit-modal-overlay" onClick={handleOverlayClick}>
      <div className="edit-modal-content" onClick={handleContentClick}>
        <h2>Import Patch or Bundle</h2>

        <div className="edit-field">
          <label>Select File:</label>
          <input
            type="file"
            accept=".xdelta,.ssbm"
            onChange={handleFileChange}
          />
          <p style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', marginTop: '0.5rem' }}>
            Supports .xdelta patches and .ssbm mod bundles
          </p>
        </div>

        {fileType === 'xdelta' && (
          <>
            <div className="edit-field">
              <label>Name:</label>
              <input
                type="text"
                value={importData.name}
                onChange={(e) => onImportDataChange({ ...importData, name: e.target.value })}
                placeholder="Patch name..."
              />
            </div>

            <div className="edit-field">
              <label>Description (optional):</label>
              <textarea
                value={importData.description}
                onChange={(e) => onImportDataChange({ ...importData, description: e.target.value })}
                placeholder="Description..."
                rows={3}
              />
            </div>

            <div className="edit-field">
              <label>Image (optional):</label>
              <input
                type="file"
                accept="image/*"
                onChange={(e) => onImportDataChange({ ...importData, image: e.target.files[0] })}
              />
            </div>
          </>
        )}

        <div className="edit-buttons">
          <button
            className="btn-save"
            onMouseEnter={playHoverSound}
            onClick={handleImport}
            disabled={importing || !importData.file}
          >
            {importing ? 'Importing...' : 'Import'}
          </button>
          <button
            className="btn-cancel"
            onMouseEnter={playHoverSound}
            onClick={handleCancel}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
