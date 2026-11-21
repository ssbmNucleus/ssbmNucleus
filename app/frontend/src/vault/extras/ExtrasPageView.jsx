import { useEffect, useRef } from 'react'
import { getExtraTypes } from '../../shared/data/extraTypes'
import { playSound } from '../../shared/audio/sounds'
import useExtrasManager from './useExtrasManager'
import { ExtraTypeCard, ExtraModCard, CreateExtraModCard } from './ExtraCards'
import ExtraEditorModals from './ExtraEditorModals'
import EffectEditorPage, { isPageEditable } from './EffectEditorPage'

/**
 * ExtrasPageView - a character's Extras: the moves (one card each), then a
 * move's saved mods, then the editor.
 *
 * A move is one extra whose mod carries its parts (Up-B = rings, charge
 * flames, main flame, puffs + puff texture, sparkles), so there is exactly
 * one card per move and one editor per mod. Most moves open the full-page
 * row editor (EffectEditorPage); the bespoke effects with their own storage
 * formats (laser, side-B, shine, sword, blaster flash, gun, shield) keep
 * their modals.
 */
export default function ExtrasPageView({
  character,
  onBack,
  onRefresh,
  refreshKey,
}) {
  const {
    selectedType,
    setSelectedType,
    extras,
    loading,
    showEditor,
    editingMod,
    handleCreateNew,
    handleEdit,
    handleDelete,
    handleEditorClose,
    handleSave
  } = useExtrasManager({ character, onRefresh, refreshKey })

  const previousCharacter = useRef(character)
  useEffect(() => {
    if (previousCharacter.current === character) return
    previousCharacter.current = character
    setSelectedType(null)
    if (showEditor) handleEditorClose()
  }, [character, showEditor, handleEditorClose, setSelectedType])

  const extraTypes = getExtraTypes(character)

  // The full-page editor replaces the whole view while open.
  if (selectedType && showEditor && isPageEditable(selectedType)) {
    return (
      <div className="storage-viewer">
        <EffectEditorPage
          key={`${character}/${selectedType.id}/${editingMod?.id || 'new'}`}
          character={character}
          extraType={selectedType}
          editingMod={editingMod}
          onBack={handleEditorClose}
          onSaved={() => { handleSave(); handleEditorClose() }}
          onDeleted={() => { handleDelete(); handleEditorClose() }}
        />
      </div>
    )
  }

  // A move's saved mods
  if (selectedType) {
    const mods = extras[selectedType.id] || []

    return (
      <div className="storage-viewer">
        <div className="character-detail extras-page">
          <div className="character-header">
            <button onClick={() => { playSound('back'); setSelectedType(null) }} className="back-button">
              ← Back to Extras
            </button>
            <div className="character-title-area">
              <h2 className="character-name">{selectedType.name}</h2>
              <span className="character-skin-count">{mods.length} mod{mods.length !== 1 ? 's' : ''}</span>
            </div>
          </div>

          <div className="skins-grid">
            {mods.map(mod => (
              <ExtraModCard
                key={mod.id}
                mod={mod}
                character={character}
                extraType={selectedType}
                onEdit={handleEdit}
                onDelete={handleDelete}
              />
            ))}
            <CreateExtraModCard
              key={selectedType.id}
              extraType={selectedType}
              onCreateNew={handleCreateNew}
            />
          </div>
        </div>

        {!isPageEditable(selectedType) && (
          <ExtraEditorModals
            selectedType={selectedType}
            character={character}
            editor={{
              show: showEditor,
              editingMod,
              onClose: handleEditorClose,
              onSave: handleSave,
              onDelete: handleDelete
            }}
          />
        )}
      </div>
    )
  }

  // The moves
  return (
    <div className="storage-viewer">
      <div className="character-detail extras-page">
        <div className="character-header">
          <button onClick={() => { playSound('back'); onBack(); }} className="back-button">
            ← Back to {character}
          </button>
          <div className="character-title-area">
            <h2 className="character-name">Extras</h2>
            <span className="character-skin-count">{character}</span>
          </div>
        </div>

        {loading ? (
          <div className="extras-page-loading">Loading extras...</div>
        ) : extraTypes.length === 0 ? (
          <div className="extras-page-empty">
            <p>No extras available for {character}.</p>
            <p>Extra types will be added in future updates.</p>
          </div>
        ) : (
          <div className="skins-grid extras-type-grid">
            {extraTypes.map(type => (
              <ExtraTypeCard
                key={type.id}
                extraType={type}
                modCount={(extras[type.id] || []).length}
                onClick={() => { playSound('boop'); setSelectedType(type); }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
