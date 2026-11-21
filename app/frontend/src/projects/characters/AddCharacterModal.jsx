/**
 * AddCharacterModal - modal listing vault custom characters with
 * batch selection and install controls.
 *
 * Receives the useCustomCharacters hook result as `cc`.
 */
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import LargeRosterWarning from '../LargeRosterWarning'

export default function AddCharacterModal({ cc, fighters, fightersStatus, onReloadRoster }) {
  const {
    showAddCharacterModal,
    setShowAddCharacterModal,
    vaultCharacters,
    selectedVaultChars,
    setSelectedVaultChars,
    batchAddingChars,
    batchCharProgress,
    toggleVaultCharSelection,
    handleBatchAddCharacters
  } = cc

  if (!showAddCharacterModal) return null

  const handleClose = () => {
    if (!batchAddingChars) {
      playSound('back')
      setShowAddCharacterModal(false)
      setSelectedVaultChars(new Set())
    }
  }

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div className="modal-content add-character-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Add Custom Characters{selectedVaultChars.size > 0 ? ` (${selectedVaultChars.size} selected)` : ''}</h3>
          <button className="modal-close" onClick={handleClose}>&times;</button>
        </div>
        <div className="add-character-body">
        <LargeRosterWarning fighters={fighters} status={fightersStatus} additions={selectedVaultChars.size} showUnknown onRetry={onReloadRoster} />
        {vaultCharacters.length > 0 && (
          <div className="batch-controls" style={{ marginBottom: 'var(--space-2)' }}>
            {selectedVaultChars.size > 0 ? (
              <>
                <button
                  className="btn-batch-import"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('start'); handleBatchAddCharacters(); }}
                  disabled={batchAddingChars}
                >
                  {batchAddingChars
                    ? (batchCharProgress.message
                        || (batchCharProgress.total > 0
                              ? `Preparing ${batchCharProgress.current}/${batchCharProgress.total}…`
                              : 'Working…'))
                    : `Add Selected (${selectedVaultChars.size})`}
                </button>
                <button
                  className="btn-clear-selection"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); setSelectedVaultChars(new Set()); }}
                  disabled={batchAddingChars}
                >
                  Clear
                </button>
              </>
            ) : (
              <button
                className="btn-select-all"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setSelectedVaultChars(new Set(vaultCharacters.map(c => c.slug))); }}
              >
                Select All
              </button>
            )}
          </div>
        )}
        <div className="add-character-list">
          {vaultCharacters.length === 0 ? (
            <p style={{ color: 'var(--color-text-muted)', padding: '1rem' }}>
              No custom characters in vault. Scan an ISO from the Vault tab first.
            </p>
          ) : vaultCharacters.map(char => {
            const isSelected = selectedVaultChars.has(char.slug)
            return (
              <button
                key={char.slug}
                className={`add-character-item ${isSelected ? 'adding' : ''}`}
                disabled={batchAddingChars}
                onClick={() => { if (!batchAddingChars) { playSound('boop'); toggleVaultCharSelection(char.slug); } }}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => {}}
                  disabled={batchAddingChars}
                  style={{ flexShrink: 0 }}
                />
                {char.has_css_icon && (
                  <img
                    src={backendMediaUrl(char.icon_url)}
                    alt=""
                    className="add-character-icon"
                    onError={e => e.target.style.display = 'none'}
                  />
                )}
                <span className="add-character-name">{char.name}</span>
                <span className="add-character-costumes">{char.costume_count} costumes</span>
              </button>
            )
          })}
        </div>
        </div>
      </div>
    </div>
  )
}
