// Header bar for the edit step: title, character/costume labels, Save/Download/Close buttons. The edit step hides
// the app header, so the chip of a model import the user's AI is running (McpImportChip) shows here instead: after
// the labels and before the pose picker, so it takes the room between them and moves neither the picker nor the
// buttons.
import { ASSISTANT_ENABLED } from '../../shared/config/features'
import McpImportChip from '../../randall/assistant/McpImportChip'

export default function SkinCreatorHeader({
  title = "Skin Creator",
  selectedCharacter,
  selectedVanillaCostume,
  isDirty,
  paintMembers = [],
  busy = false,
  poseOptions = [],
  selectedPoseName = '',
  defaultPoseName = '',
  onPoseChange,
  onSave,
  onDownload,
  onClose,
  assistantAction
}) {
  const showPosePicker = paintMembers.length === 0 && (poseOptions.length > 0 || defaultPoseName)

  return (
    <div className="skin-creator-header">
      <div className="skin-creator-title">
        <h1>{title}</h1>
        <span className="skin-creator-character">{selectedCharacter}</span>
        {selectedVanillaCostume && (
          <span className="skin-creator-costume">{selectedVanillaCostume.colorName}</span>
        )}
        {isDirty && <span className="skin-creator-dirty">*</span>}
      </div>
      {paintMembers.length > 0 && (
        <span className="skin-creator-pair-label">Popo + Nana · saves both climbers</span>
      )}
      {ASSISTANT_ENABLED && <McpImportChip />}
      {showPosePicker && (
        <label className="skin-creator-pose-select">
          <span>Pose</span>
          <select
            value={selectedPoseName || ''}
            onChange={(e) => onPoseChange?.(e.target.value)}
            title="Choose the pose used by the 3D preview"
          >
            <option value="">Base Scene</option>
            {defaultPoseName && (
              <option value={defaultPoseName}>
                Default Pose ({defaultPoseName})
              </option>
            )}
            {poseOptions
              .filter(pose => pose.name !== defaultPoseName)
              .map(pose => (
                <option key={pose.name} value={pose.name}>
                  {pose.name}
                </option>
              ))}
          </select>
        </label>
      )}
      <div className="skin-creator-header-buttons">
        {assistantAction}
        <button
          className="skin-creator-save"
          onClick={onSave}
          disabled={busy}
          title="Save to Vault"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
            <polyline points="17 21 17 13 7 13 7 21"></polyline>
            <polyline points="7 3 7 8 15 8"></polyline>
          </svg>
          <span>Save</span>
        </button>
        <button
          className="skin-creator-export"
          onClick={onDownload}
          disabled={busy}
          title={paintMembers.length ? 'Download Popo and Nana ZIP' : 'Download DAT file'}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span>Download</span>
        </button>
        <button
          className="skin-creator-close"
          onClick={onClose}
          title="Close (Esc)"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
          <span>Close</span>
        </button>
      </div>
    </div>
  )
}
