import { playSound } from '../../shared/audio/sounds'

// Save-to-vault modal: name input + Save/Cancel buttons.
export default function SaveModal({
  itemLabel = "skin",
  skinName,
  setSkinName,
  isSaving,
  saveError,
  onSave,
  onClose
}) {
  return (
    <div className="skin-creator-save-overlay" onClick={() => !isSaving && onClose()}>
      <div className="skin-creator-save-modal" onClick={(e) => e.stopPropagation()}>
        <h2>Save to Vault</h2>
        <p>Enter a name for your custom {itemLabel}:</p>
        <input
          type="text"
          className="skin-name-input"
          value={skinName}
          onChange={(e) => setSkinName(e.target.value)}
          placeholder={`${itemLabel === "stage" ? "Stage" : "Skin"} name...`}
          disabled={isSaving}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !isSaving) onSave()
            if (e.key === 'Escape' && !isSaving) onClose()
          }}
        />
        {saveError && <div className="save-error">{saveError}</div>}
        <div className="save-modal-buttons">
          <button
            className="save-cancel"
            onClick={() => { playSound('back'); onClose(); }}
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            className="save-confirm"
            onClick={onSave}
            disabled={isSaving || !skinName.trim()}
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
