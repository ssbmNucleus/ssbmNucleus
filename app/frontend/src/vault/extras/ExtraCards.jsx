import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { ICONS, EffectIcon, PlusIcon, ImportIcon } from './ExtrasIcons'
import { ExtraPreview } from './ExtraPreviews'

/**
 * ExtraTypeCard - Card for selecting an extra type category
 */
export function ExtraTypeCard({ extraType, modCount, onClick }) {
  const Icon = ICONS[extraType.icon] || EffectIcon

  // Build shared text based on sharedWith array
  const getSharedText = () => {
    if (!extraType.shared || !extraType.sharedWith) return null
    if (extraType.sharedWith.length > 3) return 'Shared with many characters'
    const chars = [extraType.owner, ...extraType.sharedWith].filter(Boolean)
    if (chars.length === 2) {
      return `Applies to both ${chars[0]} and ${chars[1]}`
    }
    return `Shared with ${extraType.sharedWith.join(', ')}`
  }

  return (
    <div className="extra-type-page-card" onMouseEnter={playHoverSound} onClick={onClick}>
      <div className="extra-type-page-icon">
        <Icon />
      </div>
      <div className="extra-type-page-info">
        <span className="extra-type-page-name">{extraType.name}</span>
        <span className="extra-type-page-count">
          {modCount} mod{modCount !== 1 ? 's' : ''}
        </span>
        {extraType.shared && (
          <span className="extra-type-shared">{getSharedText()}</span>
        )}
      </div>
    </div>
  )
}

/**
 * ExtraModCard - Individual extra mod card (same size as skin cards)
 */
export function ExtraModCard({ mod, character, extraType, onEdit, onDelete }) {
  const isModelType = extraType.type === 'model'

  return (
    <div className="extra-mod-card" onMouseEnter={playHoverSound} onClick={() => { playSound('boop'); onEdit?.(mod); }}>
      <div className="extra-mod-image-container">
        {/* Preview based on extra type */}
        <ExtraPreview extraType={extraType} modifications={mod.modifications} mod={mod} character={character} compact />
      </div>

      <div className="extra-mod-info">
        <div className="extra-mod-name">{mod.name}</div>
        {mod.source === 'imported' && (
          <div className="extra-mod-badge">Imported</div>
        )}
        {mod.source === 'uploaded' && (
          <div className="extra-mod-badge">Uploaded</div>
        )}
      </div>
    </div>
  )
}

/**
 * CreateExtraModCard - the "+" card matching skin card size. Opens the
 * type's editor: the color editor for color types, or the texture/model
 * editor (which takes a picture or model) for texture_region / model types.
 * Importing an effect .dat is the vault's floating Import button, which
 * auto-detects the effect and files it here.
 */
export function CreateExtraModCard({ extraType, onCreateNew }) {
  const isModelType = extraType?.type === 'model'
  const isTextureRegion = extraType?.format === 'texture_region'
  const opensEditorWithFile = isModelType || isTextureRegion

  return (
    <div className="extra-mod-card create-extra-mod-card" onMouseEnter={playHoverSound} onClick={() => { playSound('boop'); onCreateNew?.(); }}>
      <div className="extra-mod-image-container create-extra-mod-placeholder">
        <div className="create-extra-mod-icon">
          {opensEditorWithFile ? <ImportIcon /> : <PlusIcon />}
        </div>
      </div>
      <div className="extra-mod-info">
        <div className="extra-mod-name">
          {isTextureRegion ? 'New Texture' : isModelType ? 'New Model' : 'Create New Mod'}
        </div>
        {opensEditorWithFile && (
          <div className="extra-mod-hint">{isTextureRegion ? 'from an image' : 'from a .dae'}</div>
        )}
      </div>
    </div>
  )
}
