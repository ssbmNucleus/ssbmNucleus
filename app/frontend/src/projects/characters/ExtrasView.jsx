/**
 * ExtrasView - the extras-mode UI of CharacterMode
 * (extra type list, current-in-MEX preview, available-to-import list)
 */
import { useEffect, useRef, useState } from 'react'
import { getExtraTypes, getUnitParts } from '../../shared/data/extraTypes'
import { backendMediaUrl } from '../../shared/config/config.js'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import HexagonLoader from '../../shared/ui/HexagonLoader'
import PaginationBar from '../../shared/ui/PaginationBar'
import usePagination from '../../shared/hooks/usePagination'
import { ExtraPreview, ModelPreview, currentColorsToMods } from '../../vault/extras/ExtraPreviews'
import {
  canRestoreCurrent,
  MODEL_CURRENT,
  currentLabel,
  currentNote,
  currentPartCards,
  currentPreviewColors,
  matchInstalledMod,
} from './currentExtraState'

// The image effect installed in the project, rendered by the backend from the
// project file itself (not from a vault mod). readId re-fetches it after an
// install; an unreadable image falls back to a plain label.
function CurrentImagePreview({ fighterName, typeId, readId }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => { setFailed(false) }, [fighterName, typeId, readId])
  const src = backendMediaUrl(
    `/api/mex/storage/extras/effect-image/${encodeURIComponent(fighterName)}/${encodeURIComponent(typeId)}`,
    readId)
  return (
    <div className="extras-current-image">
      {failed ? (
        <span>IMAGE EFFECT</span>
      ) : (
        <img src={src} alt="Installed image effect" onError={() => setFailed(true)} />
      )}
    </div>
  )
}

export default function ExtrasView({ selectedFighter, extras }) {
  const {
    setExtrasMode,
    selectedExtraType,
    setSelectedExtraType,
    extraMods,
    selectedExtraMod,
    setSelectedExtraMod,
    importingExtra,
    restoringExtra,
    extraImportError,
    setExtraImportError,
    current,
    getAllMods,
    handleImportExtra,
    handleRestoreVanilla
  } = extras
  const extraBusy = importingExtra || restoringExtra

  const previousCharacter = useRef(selectedFighter.name)
  useEffect(() => {
    if (previousCharacter.current === selectedFighter.name) return
    previousCharacter.current = selectedFighter.name
    setSelectedExtraType(null)
    setSelectedExtraMod(null)
    setExtraImportError(null)
  }, [selectedFighter.name, setSelectedExtraType, setSelectedExtraMod, setExtraImportError])

  // One entry per move: a move's parts ship inside its mods (getExtraTypes
  // hides the part types), so installing a mod installs the whole move.
  const extraTypes = getExtraTypes(selectedFighter.name)
  const selectType = type => {
    playSound('boop')
    setSelectedExtraType(type)
    setSelectedExtraMod(null)
    setExtraImportError(null)
  }
  const availableMods = selectedExtraType ? getAllMods(selectedExtraType.id) : []
  const currentColors = currentPreviewColors(current)
  const installedMod = matchInstalledMod(current, availableMods)
  const partCards = selectedExtraType
    ? currentPartCards(current, getUnitParts(selectedFighter.name, selectedExtraType.id))
    : []
  const modsPager = usePagination(availableMods.length, selectedExtraType?.id)
  console.log('[CharacterMode] Extras for', selectedFighter.name, ':', extraTypes.map(t => t.id))
  if (selectedExtraType) {
    console.log('[CharacterMode] Selected extra type:', selectedExtraType.id, selectedExtraType)
  }

  return (
    <div className="mex-content">
      <div className="fighters-list">
        <div className="extras-header">
          <h3>Extras</h3>
          <button
            className="btn-back-small"
            onMouseEnter={playHoverSound}
            onClick={() => {
              playSound('back')
              setExtrasMode(false)
              setSelectedExtraType(null)
              setSelectedExtraMod(null)
              setExtraImportError(null)
            }}
          >
            ← Back
          </button>
        </div>
        <div className="fighter-items">
          {extraTypes.map(type => (
            <div
              key={type.id}
              className={`fighter-item ${selectedExtraType?.id === type.id ? 'selected' : ''}`}
              onClick={() => selectType(type)}
            >
              <div className="fighter-content">
                <div className="fighter-name">{type.name}</div>
                <div className="fighter-info">
                  <span className="costume-count">
                    {(extraMods[type.id] || []).length} in vault
                  </span>
                  {type.shared && type.sharedWith && (
                    <span className="shared-note">
                      {type.sharedWith.length > 3
                        ? 'Shared with many characters'
                        : `Applies to ${type.owner} & ${type.sharedWith.join(', ')}`}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="costumes-panel">
        {selectedExtraType ? (
          <>
            <h2 className="extras-selected-heading">{selectedExtraType.name}</h2>
            {/* Currently in MEX section - shows actual colors from .dat (or model status) */}
            <div className="costumes-section">
              <h3>Currently in MEX</h3>
              <div className="costume-list existing">
                {selectedExtraType.type === 'model' ? (
                  // Model type - just show a placeholder, no color preview
                  <div className="costume-card existing-costume">
                    <div className="costume-preview" style={{ padding: '8px' }}>
                      <ModelPreview mod={{ name: 'Current' }} compact />
                      <button
                        className="btn-remove"
                        onClick={handleRestoreVanilla}
                        disabled={extraBusy}
                        title="Restore vanilla"
                      >
                        ×
                      </button>
                    </div>
                    <div className="costume-info">
                      <h4>{MODEL_CURRENT.label}</h4>
                      <span className="extras-current-note">{MODEL_CURRENT.note}</span>
                    </div>
                  </div>
                ) : (
                  // Color type - show current colors
                  <div className={`costume-card existing-costume ${current.phase === 'ready' && current.isVanilla ? 'vanilla-extra' : ''}`}>
                    <div className="costume-preview" style={{ padding: '8px' }}>
                      {current.sidebModel ? (
                        <ModelPreview mod={{ name: 'Current afterimage' }} compact />
                      ) : current.image ? (
                        <CurrentImagePreview
                          fighterName={selectedFighter.name}
                          typeId={selectedExtraType.id}
                          readId={current.readId}
                        />
                      ) : currentColors ? (
                        <ExtraPreview extraType={selectedExtraType} modifications={currentColorsToMods(currentColors)} compact />
                      ) : (
                        <div className="vanilla-preview">
                          <span>{current.phase === 'error' ? 'Unavailable'
                            : current.status === 'unknown' ? 'Unknown' : 'Loading...'}</span>
                        </div>
                      )}
                      {canRestoreCurrent(current) && (
                        <button
                          className="btn-remove"
                          onClick={handleRestoreVanilla}
                          disabled={extraBusy}
                          title="Restore vanilla"
                        >
                          ×
                        </button>
                      )}
                    </div>
                    <div className="costume-info">
                      <h4>{currentLabel(current)}</h4>
                      {currentNote(current) && (
                        <span
                          className="extras-current-note"
                          title={current.phase === 'error' ? current.error : undefined}
                        >
                          {currentNote(current)}
                        </span>
                      )}
                      {installedMod && (
                        <span className="extras-current-note" title={installedMod.name}>
                          Matches “{installedMod.name}”
                        </span>
                      )}
                    </div>
                  </div>
                )}
                {partCards.map(part => (
                  <div
                    key={part.id}
                    className={`costume-card existing-costume ${part.isVanilla ? 'vanilla-extra' : ''}`}
                  >
                    <div className="costume-preview" style={{ padding: '8px' }}>
                      {part.colors ? (
                        <ExtraPreview extraType={part.type} modifications={currentColorsToMods(part.colors)} compact />
                      ) : (
                        <div className="vanilla-preview"><span>Unknown</span></div>
                      )}
                    </div>
                    <div className="costume-info">
                      <h4>{part.label}</h4>
                      <span className="extras-current-note">{part.name}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Available to Import section - shows ALL mods */}
            <div className="costumes-section">
              <div className="costumes-section-header">
                <h3>Available to Import</h3>
                <div className="batch-controls">
                  {selectedExtraMod && (
                    <button
                      className="btn-batch-import"
                      onMouseEnter={playHoverSound}
                      onClick={() => { playSound('start'); handleImportExtra(); }}
                      disabled={extraBusy}
                    >
                      {importingExtra ? 'Importing...' : 'Import Selected'}
                    </button>
                  )}
                </div>
              </div>
              {extraImportError && (
                <div className="extras-import-error" role="alert">
                  Install failed: {extraImportError}
                </div>
              )}
              <div className="costume-list">
                {availableMods.slice(modsPager.start, modsPager.end).map(mod => (
                  <div
                    key={mod.id}
                    className={`costume-card ${selectedExtraMod?.id === mod.id ? 'selected' : ''}`}
                    onClick={() => { setSelectedExtraMod(mod); setExtraImportError(null); }}
                  >
                    <div className="costume-preview" style={{ padding: '8px' }}>
                      <ExtraPreview extraType={selectedExtraType} modifications={mod.modifications} mod={mod} compact />
                      <input
                        type="checkbox"
                        className="costume-checkbox"
                        checked={selectedExtraMod?.id === mod.id}
                        readOnly
                      />
                    </div>
                    <div className="costume-info">
                      <h4>{mod.name}</h4>
                    </div>
                  </div>
                ))}
                {availableMods.length === 0 && (
                  <div className="no-costumes">
                    <p>No extras in vault. Create some in Storage → {selectedFighter.name} → Extras.</p>
                  </div>
                )}
              </div>
              <PaginationBar pager={modsPager} />
            </div>
          </>
        ) : (
          <div className="no-selection">
            <p>Select an effect</p>
          </div>
        )}
      </div>

      {/* Import / restore loading overlay */}
      {extraBusy && (
        <div className="import-overlay">
          <div className="import-modal import-modal--hexagon">
            <HexagonLoader
              className="import-loader"
              size={104}
              label={restoringExtra ? 'Restoring vanilla extra' : 'Importing extra'}
            />
            <h3>{restoringExtra ? 'Restoring Vanilla...' : 'Importing...'}</h3>
            <p className="import-status">
              {restoringExtra
                ? `Putting the vanilla ${selectedExtraType?.name || 'effect'} back in this project...`
                : 'Please wait...'}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
