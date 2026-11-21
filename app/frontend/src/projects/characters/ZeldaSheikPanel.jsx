/**
 * ZeldaSheikPanel - the combined Zelda/Sheik costumes panel.
 *
 * Zelda and Sheik are one in-game pairing: costume slot N of one loads slot N
 * of the other on transform. So when either fighter is selected, this panel
 * replaces the normal CostumesPanel with:
 *   - "In ISO": a slot-paired ladder -- each column is one in-game slot with
 *     the Zelda costume on top, the Sheik costume below, and a connector line
 *     between them (dashed red when one half is missing).
 *   - "Available to Import": split vertically, Zelda's storage skins on top,
 *     Sheik's below, sharing one batch-selection toolbar.
 *
 * Receives the useCostumes hook result as `cm` (same contract as CostumesPanel).
 */
import { useEffect, useState } from 'react'
import { hasExtras } from '../../shared/data/extraTypes'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import PaginationBar from '../../shared/ui/PaginationBar'
import usePagination from '../../shared/hooks/usePagination'
import SoundPacksModal from '../../vault/sounds/SoundPacksModal'
import ReplacementBar from './ReplacementBar'
import { ZS_PAIR } from './useCostumes'
import { API_URL } from '../../shared/config/config.js'

const PoseIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
    <circle cx="12" cy="13" r="4"/>
  </svg>
)

const SoundIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
    <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
    <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
  </svg>
)

const PER_FIGHTER_COSTUME_CAP = 255

export default function ZeldaSheikPanel({ refreshing, cm, selectedFighter, onEnterExtras, onApplyPose }) {
  const {
    pairCostumes,
    loadingFighter,
    dataReady,
    removing,
    selectedCostumes,
    selectedInstalledCostumes,
    batchImporting,
    batchProgress,
    draggedIndex,
    dragOverIndex,
    draggedRow,
    syncingOrder,
    resettingVanilla,
    pendingOrderMoves,
    selectedTeamColor,
    availableListRef,
    handleTeamColorClick,
    handlePairCostumeTeamAssign,
    handleResetVanilla,
    getPairCostumeTeamColor,
    handleRemoveCostume,
    handleBatchRemoveCostumes,
    handleBatchImport,
    handlePairDragStart,
    handleDragOver,
    handlePairDragEnter,
    handleDragLeave,
    handlePairDrop,
    handleDragEnd,
    getCostumesForFighter,
    toggleCostumeSelection,
    selectAllCostumes,
    clearSelection,
    installedCostumeKey,
    toggleInstalledCostumeSelection,
    clearInstalledCostumeSelection,
    replacement,
    replacementBusy,
    replaceWithCostume
  } = cm

  const BASE_URL = API_URL.replace('/api/mex', '')
  // Zelda and Sheik share one sound bank (zs.ssm) — one pack covers both
  const [showSoundBank, setShowSoundBank] = useState(false)
  const zelda = pairCostumes.Zelda || []
  const sheik = pairCostumes.Sheik || []
  const slotCount = Math.max(zelda.length, sheik.length)
  const mismatch = dataReady && zelda.length !== sheik.length
  const isTeamAssignable = selectedTeamColor !== null
  const availableTotal = ZS_PAIR.reduce((n, name) => n + getCostumesForFighter(name).length, 0)
  // While replacing, the vault cards of the targeted half are click-to-pick
  // (no checkbox, no batching) instead of opening a picker over the page.
  const picking = !!replacement
  const canPick = picking && !!replacement.version && !replacementBusy

  // The replacement is picked from the vault list that is already on screen, so
  // bring it into view when one starts.
  useEffect(() => {
    if (replacement) availableListRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [replacement?.fighter, replacement?.index])

  // Pagination: the ladder pages by SLOT (each slot column = a Zelda/Sheik
  // pair), the two available sub-lists page independently. Hooks are called
  // unconditionally in a fixed order (never inside the ZS_PAIR.map loop).
  const ladderPager = usePagination(slotCount, 'zs-ladder')
  const availPagers = {
    Zelda: usePagination(getCostumesForFighter('Zelda').length, 'zs-avail-zelda'),
    Sheik: usePagination(getCostumesForFighter('Sheik').length, 'zs-avail-sheik')
  }

  // An unpaired slot doesn't crash in game (verified live): transforming there
  // just loads the fighter's FIRST costume instead. So instead of a bare "no
  // half" placeholder, show a ghosted preview of that actual fallback.
  const renderFallbackSlot = (fighterName, slotNum) => {
    const fallback = (pairCostumes[fighterName] || [])[0]
    const fbName = fallback?.name || 'Default'
    return (
      <div
        className="zs-empty-slot"
        title={`No ${fighterName} costume in slot ${slotNum} — transforming here loads ${fighterName}'s first costume (${fbName}) instead. Safe, no crash.`}
      >
        {fallback?.cspUrl ? (
          <>
            <img
              className="zs-fallback-csp"
              src={`${BASE_URL}${fallback.cspUrl}`}
              alt=""
              onError={(e) => e.target.style.display = 'none'}
            />
            <span className="zs-fallback-tag">transforms to</span>
            <span className="zs-fallback-name">{fbName}</span>
          </>
        ) : (
          <span>no {fighterName} half</span>
        )}
      </div>
    )
  }

  const renderInIsoTile = (fighterName, costume, idx, animDelay) => {
    const isDragging = draggedRow === fighterName && draggedIndex === idx
    const isDragOver = draggedRow === fighterName && dragOverIndex === idx
    const teamColorsOn = getPairCostumeTeamColor(fighterName, idx)
    const isDeleteSelected = selectedInstalledCostumes.has(installedCostumeKey(fighterName, idx))
    const isReplaceTarget = picking && replacement.fighter === fighterName && replacement.index === idx
    return (
      <div
        className={`costume-card existing-costume ${isDeleteSelected ? 'selected' : ''} ${isDragging ? 'dragging' : ''} ${isDragOver ? 'drag-over' : ''} ${dataReady ? 'card-visible' : 'card-hidden'} ${isTeamAssignable ? 'team-assignable' : ''} ${isReplaceTarget ? 'replacement-target' : ''}`}
        style={{ animationDelay: dataReady ? `${animDelay}ms` : '0ms' }}
        draggable={!removing && !isTeamAssignable}
        onMouseEnter={playHoverSound}
        onClick={(e) => {
          if (e.target.closest('button, input') || removing || syncingOrder) return
          if (isTeamAssignable) {
            handlePairCostumeTeamAssign(fighterName, idx)
          } else {
            playSound('boop')
            toggleInstalledCostumeSelection(fighterName, idx)
          }
        }}
        onDragStart={(e) => !isTeamAssignable && handlePairDragStart(e, fighterName, idx)}
        onDragOver={handleDragOver}
        onDragEnter={(e) => handlePairDragEnter(e, fighterName, idx)}
        onDragLeave={handleDragLeave}
        onDrop={(e) => handlePairDrop(e, fighterName, idx)}
        onDragEnd={handleDragEnd}
      >
        <div className="costume-preview">
          {costume.vanillaTarget && <button type="button" className="btn-replace-vanilla"
            disabled={removing || syncingOrder || batchImporting || loadingFighter || resettingVanilla || isTeamAssignable}
            onClick={e => { e.stopPropagation(); cm.beginReplacement(fighterName, idx, costume) }}>
            Replace
          </button>}
          <input
            type="checkbox"
            className="costume-checkbox"
            checked={isDeleteSelected}
            onClick={(e) => e.stopPropagation()}
            onChange={() => { playSound('boop'); toggleInstalledCostumeSelection(fighterName, idx); }}
            disabled={removing || syncingOrder || isTeamAssignable}
            title="Select for delete"
          />
          <span className={`zs-fighter-tag zs-${fighterName.toLowerCase()}`}>{fighterName}</span>
          {costume.cspUrl && (
            <img
              src={`${BASE_URL}${costume.cspUrl}`}
              alt={costume.name}
              onError={(e) => e.target.style.display = 'none'}
            />
          )}
          <button
            className="btn-remove"
            onClick={(e) => {
              e.stopPropagation()
              handleRemoveCostume(fighterName, idx, costume.name)
            }}
            disabled={removing || syncingOrder}
            title="Remove costume"
          >
            ×
          </button>
          {costume.iconUrl && (
            <div className="stock-icon-overlay">
              <img
                src={`${BASE_URL}${costume.iconUrl}`}
                alt="Stock"
                onError={(e) => e.target.style.display = 'none'}
              />
            </div>
          )}
          {teamColorsOn.length > 0 && (
            <div className="team-color-badges">
              {teamColorsOn.map(color => (
                <div
                  key={color}
                  className={`team-color-badge team-${color}`}
                  title={`${color.charAt(0).toUpperCase() + color.slice(1)} Team`}
                >
                  {color[0].toUpperCase()}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="costume-info">
          <h4>{costume.name}</h4>
        </div>
      </div>
    )
  }

  return (
    <div className={`costumes-panel ${refreshing || loadingFighter ? 'refreshing' : ''}`}>
      <div className="costumes-section">
        <div className="costumes-section-header">
          <h3>
            In ISO ({dataReady ? `${slotCount}/${PER_FIGHTER_COSTUME_CAP}` : 'Loading...'}) - Zelda ({dataReady ? zelda.length : '...'}) / Sheik ({dataReady ? sheik.length : '...'})
          </h3>
          {selectedInstalledCostumes.size > 0 && (
            <span className="selection-count-badge">{selectedInstalledCostumes.size} selected</span>
          )}
          {syncingOrder && (
            <span className="order-saving-badge" title="Saving the new costume order to the project — other actions are locked until this finishes.">
              Saving order…{pendingOrderMoves > 0 ? ` (${pendingOrderMoves} more queued)` : ''}
            </span>
          )}
          {mismatch && (
            <span
              className="zs-mismatch"
              title="Zelda and Sheik have different costume counts. Slot N of one transforms into slot N of the other; an unpaired slot still works (verified in-game, no crash) — the transform just appears as the default first costume, and transforming back returns to the correct skin."
            >
              ⚠ unpaired slots
            </span>
          )}
          <div className="iso-mod-actions">
            {selectedInstalledCostumes.size > 0 && (
              <>
                <button
                  className="btn-batch-import btn-batch-delete"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('start'); handleBatchRemoveCostumes(); }}
                  disabled={removing || syncingOrder || isTeamAssignable}
                >
                  Delete Selected ({selectedInstalledCostumes.size})
                </button>
                <button
                  className="btn-clear-selection"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); clearInstalledCostumeSelection(); }}
                  disabled={removing || syncingOrder}
                >
                  Clear
                </button>
              </>
            )}
            <button
              className="btn-extras-mode"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('start'); handleResetVanilla(); }}
              disabled={resettingVanilla || syncingOrder || removing}
              title="Remove both fighters' installed skins and restore their complete paired vanilla sets"
            >
              {resettingVanilla ? 'Resetting...' : 'Reset Zelda + Sheik'}
            </button>
            {/* Extras (laser/sword/etc.) act on whichever half is selected.
                Neither Zelda nor Sheik currently defines any, so this stays
                hidden until one does — kept here so the split panel matches
                the normal CostumesPanel action set. */}
            {selectedFighter && onEnterExtras && hasExtras(selectedFighter.name) && (
              <button
                className="btn-extras-mode"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); onEnterExtras(); }}
                disabled={syncingOrder}
              >
                Extras
              </button>
            )}
            {/* Poses are per-fighter: Zelda's and Sheik's portraits use
                different vault skins and pose libraries, so each half gets its
                own button that poses just that half's in-ISO costumes. */}
            {onApplyPose && ZS_PAIR.map((name) => {
              const count = (pairCostumes[name] || []).length
              return (
                <button
                  key={name}
                  className={`btn-pose-all btn-pose-zs zs-${name.toLowerCase()}`}
                  onClick={() => { playSound('boop'); onApplyPose({ name }); }}
                  onMouseEnter={playHoverSound}
                  disabled={!dataReady || count === 0 || syncingOrder}
                  title={`Apply a pose to all ${name} portraits`}
                >
                  <PoseIcon />
                  <span className="btn-pose-zs-label">{name}</span>
                </button>
              )
            })}
            <button
              className="btn-pose-all btn-sound-pack"
              onClick={() => { playSound('boop'); setShowSoundBank(true); }}
              onMouseEnter={playHoverSound}
              title="Sound packs — Zelda and Sheik share one sound bank; choose which pack this project uses"
            >
              <SoundIcon />
            </button>
          </div>
          <div className="team-color-tokens">
            {[
              { id: 'red', label: 'R', color: '#ff4757' },
              { id: 'blue', label: 'B', color: '#3742fa' },
              { id: 'green', label: 'G', color: '#2ed573' }
            ].map(c => (
              <div
                key={c.id}
                className={`team-color-token ${selectedTeamColor === c.id ? 'selected' : ''} ${syncingOrder ? 'disabled' : ''}`}
                style={{ '--token-color': c.color }}
                onClick={() => { if (!syncingOrder) handleTeamColorClick(c.id) }}
                onMouseEnter={playHoverSound}
                title={syncingOrder ? 'Saving order… team colors are locked until it finishes' : `${c.id.charAt(0).toUpperCase() + c.id.slice(1)} Team - click a Zelda or Sheik costume to assign`}
              >
                {c.label}
              </div>
            ))}
          </div>
        </div>
        <div className={`costume-list existing zs-ladder ${loadingFighter ? 'processing' : ''}`}>
          {Array.from({ length: ladderPager.end - ladderPager.start }, (_, col) => {
            const i = ladderPager.start + col
            const zc = zelda[i]
            const sc = sheik[i]
            const paired = !!(zc && sc)
            return (
              <div className="zs-pair-column" key={i}>
                {zc
                  ? renderInIsoTile('Zelda', zc, i, Math.min(col * 30, 990))
                  : renderFallbackSlot('Zelda', i + 1)}
                <div
                  className={`zs-pair-link ${paired ? '' : 'broken'}`}
                  title={paired
                    ? `Slot ${i + 1}: this Zelda and Sheik transform into each other`
                    : `Slot ${i + 1}: missing the ${zc ? 'Sheik' : 'Zelda'} half — the transform shows the default costume instead (safe, no crash)`}
                >
                  <span className="zs-slot-num">{i + 1}</span>
                </div>
                {sc
                  ? renderInIsoTile('Sheik', sc, i, Math.min(col * 30 + 15, 990))
                  : renderFallbackSlot('Sheik', i + 1)}
              </div>
            )
          })}
          {dataReady && slotCount === 0 && (
            <div className="no-costumes">
              <p>No costumes in MEX yet</p>
            </div>
          )}
        </div>
        <PaginationBar pager={ladderPager} />
      </div>

      <div className="costumes-section">
        <div className="costumes-section-header">
          {picking ? <ReplacementBar cm={cm} /> : <>
          <h3>
            Available to Import ({dataReady ? availableTotal : 'Loading...'})
            {selectedCostumes.size > 0 && ` - ${selectedCostumes.size} selected`}
          </h3>
          <div className="batch-controls">
            {availableTotal > 0 && (
              <button
                className="btn-select-all"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); selectAllCostumes(); }}
                disabled={loadingFighter || batchImporting || syncingOrder}
              >
                Select All
              </button>
            )}
            {selectedCostumes.size > 0 && (
              <>
                <button
                  className="btn-batch-import"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('start'); handleBatchImport(); }}
                  disabled={batchImporting || loadingFighter || syncingOrder}
                >
                  {batchImporting
                    ? `Importing ${batchProgress.current}/${batchProgress.total}...`
                    : `Import All Selected (${selectedCostumes.size})`}
                </button>
                <button
                  className="btn-clear-selection"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); clearSelection(); }}
                  disabled={batchImporting || loadingFighter}
                >
                  Clear
                </button>
              </>
            )}
          </div>
          </>}
        </div>
        <div className="zs-available-body" ref={availableListRef}>
          {ZS_PAIR.map((fighterName) => {
            const available = getCostumesForFighter(fighterName)
            const pager = availPagers[fighterName]
            return (
              <div className="zs-available-sub" key={fighterName}>
                <div className={`zs-sub-label zs-${fighterName.toLowerCase()}`}>
                  {fighterName} ({dataReady ? available.length : '…'})
                </div>
                <div className={`costume-list ${loadingFighter ? 'processing' : ''}`}>
                  {available.slice(pager.start, pager.end).map((costume, i) => {
                    const idx = pager.start + i
                    const isSelected = selectedCostumes.has(costume.zipPath)
                    // Only the half being replaced can be picked; the other
                    // half keeps its normal selection behaviour.
                    const isPickable = picking && replacement.fighter === fighterName
                    return (
                      <div
                        key={idx}
                        className={`costume-card ${isSelected && !isPickable ? 'selected' : ''} ${dataReady ? 'card-visible' : 'card-hidden'} ${isPickable ? 'replacement-pick' : ''}`}
                        style={{ animationDelay: dataReady ? `${Math.min(i * 30, 990)}ms` : '0ms' }}
                        onMouseEnter={playHoverSound}
                        onClick={() => {
                          if (isPickable) { if (canPick) { playSound('boop'); replaceWithCostume(costume) } return }
                          if (!batchImporting && !loadingFighter) { playSound('boop'); toggleCostumeSelection(costume.zipPath) }
                        }}
                      >
                        <div className="costume-preview">
                          {costume.cspUrl && (
                            <img
                              src={`${BASE_URL}${costume.cspUrl}`}
                              alt={costume.name}
                              onError={(e) => e.target.style.display = 'none'}
                            />
                          )}
                          {!isPickable && (
                            <input
                              type="checkbox"
                              className="costume-checkbox"
                              checked={isSelected}
                              onChange={() => {}}
                              disabled={batchImporting || loadingFighter}
                            />
                          )}
                          {costume.stockUrl && (
                            <div className="stock-icon-overlay">
                              <img
                                src={`${BASE_URL}${costume.stockUrl}`}
                                alt="Stock"
                                onError={(e) => e.target.style.display = 'none'}
                              />
                            </div>
                          )}
                          {costume.slippiSafe && (
                            <div className="slippi-badge slippi-badge-overlay" title="Slippi Safe">
                              ✓
                            </div>
                          )}
                        </div>
                        <div className="costume-info">
                          <h4>{costume.name?.includes(' - ') ? costume.name.split(' - ').slice(1).join(' - ') : costume.name}</h4>
                        </div>
                      </div>
                    )
                  })}
                  {dataReady && available.length === 0 && (
                    <div className="no-costumes">
                      <p>No costumes available in storage for {fighterName}</p>
                    </div>
                  )}
                </div>
                <PaginationBar pager={pager} />
              </div>
            )
          })}
        </div>
      </div>

      <SoundPacksModal
        show={showSoundBank}
        character="Zelda"
        displayName="Zelda / Sheik"
        installMode
        onClose={() => setShowSoundBank(false)}
      />
    </div>
  )
}
