import LaserEditorModal from './LaserEditorModal'
import SideBEditorModal from './SideBEditorModal'
import ShineEditorModal from './ShineEditorModal'
import SwordEditorModal from './SwordEditorModal'
import LaserRingEditorModal from './LaserRingEditorModal'
import GunEditorModal from './GunEditorModal'
import ShieldTextureEditorModal from './ShieldTextureEditorModal'

/**
 * ExtraEditorModals - the bespoke editor modals (laser, side-B, shine,
 * sword, blaster flash, gun, shield). Every other effect opens the full-page
 * EffectEditorPage instead (see isPageEditable). `editor` groups the modal
 * state and handlers from useExtrasManager.
 */
export default function ExtraEditorModals({ selectedType, character, editor }) {
  const { show, editingMod, onClose, onSave, onDelete } = editor

  return (
    <>
      {/* Laser Editor Modal */}
      {selectedType.id === 'laser' && (
        <LaserEditorModal
          show={show}
          character={character}
          extraType={selectedType}
          editingMod={editingMod}
          onClose={onClose}
          onSave={onSave}
          onDelete={onDelete}
        />
      )}

      {/* Side-B Editor Modal */}
      {selectedType.id === 'sideb' && (
        <SideBEditorModal
          show={show}
          character={character}
          extraType={selectedType}
          editingMod={editingMod}
          onClose={onClose}
          onSave={onSave}
          onDelete={onDelete}
        />
      )}


      {/* Shine Editor Modal */}
      {selectedType.id === 'shine' && (
        <ShineEditorModal
          show={show}
          character={character}
          extraType={selectedType}
          editingMod={editingMod}
          onClose={onClose}
          onSave={onSave}
          onDelete={onDelete}
        />
      )}

      {/* Laser Ring Editor Modal */}
      {selectedType.id === 'laser_ring' && (
        <LaserRingEditorModal
          show={show}
          character={character}
          extraType={selectedType}
          editingMod={editingMod}
          onClose={onClose}
          onSave={onSave}
          onDelete={onDelete}
        />
      )}

      {/* Sword Editor Modal */}
      {selectedType.id === 'sword' && (
        <SwordEditorModal
          show={show}
          character={character}
          extraType={selectedType}
          editingMod={editingMod}
          onClose={onClose}
          onSave={onSave}
          onDelete={onDelete}
        />
      )}


      {/* Shield Texture Editor Modal - for texture_region extras */}
      {selectedType.format === 'texture_region' && (
        <ShieldTextureEditorModal
          show={show}
          character={character}
          extraType={selectedType}
          editingMod={editingMod}
          onClose={onClose}
          onSave={onSave}
          onDelete={onDelete}
        />
      )}

      {/* Gun Editor Modal - for model type extras */}
      {selectedType.type === 'model' && (
        <GunEditorModal
          show={show}
          character={character}
          extraType={selectedType}
          editingMod={editingMod}
          onClose={onClose}
          onSave={onSave}
          onDelete={onDelete}
        />
      )}
    </>
  )
}
