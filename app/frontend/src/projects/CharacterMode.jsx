/**
 * CharacterMode - MEX character costume management
 *
 * Features:
 * - Fighter list with costume counts
 * - MEX costumes panel with drag-drop reordering
 * - Available costumes panel with batch selection/import
 * - Ice Climbers special handling (auto-pair Popo/Nana)
 * - Single and batch costume import/removal
 * - Extras mode for managing character extras (laser colors, etc.)
 *
 * Orchestrator component - state and UI live in ./charactermode/:
 * - useCostumes: costume fetch/import/remove/reorder/team-color logic
 * - useExtras: extras mode state and API logic
 * - useCustomCharacters: add/remove custom character logic
 * - FighterList, CostumesPanel, AddCharacterModal, ExtrasView: UI
 */
import ConfirmDialog from '../shared/ui/ConfirmDialog'
import HexagonLoader from '../shared/ui/HexagonLoader'
import PoseManagerModal from '../vault/characters/poses/PoseManagerModal'
import useCostumes from './characters/useCostumes'
import useExtras from './characters/useExtras'
import useCustomCharacters from './characters/useCustomCharacters'
import useApplyPose from './characters/useApplyPose'
import FighterList from './characters/FighterList'
import CostumesPanel from './characters/CostumesPanel'
import AddCharacterModal from './characters/AddCharacterModal'
import ExtrasView from './characters/ExtrasView'

export default function CharacterMode({
  mode,
  onModeChange,
  fighters,
  fightersStatus,
  onReloadRoster,
  selectedFighter,
  onSelectFighter,
  storageCostumes,
  onRefresh,
  refreshing,
  onOpenMenuMusic,
  vaultMetadata,
}) {
  const cm = useCostumes({ fighters, storageCostumes, selectedFighter, onRefresh })
  const extras = useExtras({ selectedFighter, vaultMetadata })
  const cc = useCustomCharacters({ onRefresh })
  const ap = useApplyPose({
    selectedFighter,
    // Pose can target a fighter other than the selected one (Zelda/Sheik split),
    // so refresh whichever fighter was actually posed.
    refreshCostumes: (name) => {
      const fighterName = name || selectedFighter?.name
      return fighterName ? cm.refreshMexCostumes(fighterName) : Promise.resolve()
    }
  })

  // The fighter a pose targets, and its in-ISO costume count, for the modal/
  // confirm text. For Zelda/Sheik the count comes from that half's pair list.
  const poseFighterName = ap.poseFighter?.name || selectedFighter?.name || ''
  const poseCostumeCount = ap.poseFighter && cm.isZeldaSheik
    ? (cm.pairCostumes[ap.poseFighter.name]?.length ?? 0)
    : cm.mexCostumes.length

  // Extras mode UI
  if (extras.extrasMode && selectedFighter) {
    return <ExtrasView selectedFighter={selectedFighter} extras={extras} />
  }

  // Character mode UI (default)
  // Hide non-playable characters
  const hiddenCharacters = ['Nana', 'Master Hand', 'Crazy Hand', 'Wireframe Male', 'Wireframe Female', 'Giga Bowser', 'Sandbag', 'NONE']
  // NONE is a placeholder fighter that blocks a broken slot — it is technically a
  // mex fighter but must never be shown, so hide it even when isMexFighter is true.
  const alwaysHidden = ['NONE']
  const playableFighters = fighters.filter(f =>
    !alwaysHidden.includes(f.name) && (f.isMexFighter || !hiddenCharacters.includes(f.name)))
  const batchImportProgress = cm.batchImporting && cm.batchProgress.total > 0
    ? (cm.batchProgress.current / cm.batchProgress.total) * 100
    : null

  return (
    <div className="mex-content">
      <FighterList
        mode={mode}
        onModeChange={onModeChange}
        playableFighters={playableFighters}
        selectedFighter={selectedFighter}
        onSelectFighter={onSelectFighter}
        getCostumesForFighter={cm.getCostumesForFighter}
        onRemoveFighter={cc.handleRemoveFighter}
        onAddCharacter={cc.openAddCharacterModal}
        onOpenMenuMusic={onOpenMenuMusic}
      />

      <AddCharacterModal cc={cc} fighters={fighters} fightersStatus={fightersStatus} onReloadRoster={onReloadRoster} />

      <CostumesPanel
        selectedFighter={selectedFighter}
        refreshing={refreshing}
        cm={cm}
        onEnterExtras={() => extras.setExtrasMode(true)}
        onApplyPose={ap.openPoseModal}
      />

      {/* Pose picker for "apply pose to all installed costumes" */}
      <PoseManagerModal
        show={ap.showPoseModal}
        character={ap.poseCharacter || poseFighterName}
        displayName={poseFighterName}
        baseSkinId={ap.poseBaseSkinId || undefined}
        onSelectPose={ap.handlePoseSelected}
        onClose={() => ap.setShowPoseModal(false)}
      />

      {/* Import Loading Overlay */}
      {(cm.importing || cm.batchImporting || cm.resettingVanilla) && (
        <div className="import-overlay">
          <div className="import-modal import-modal--hexagon">
            <HexagonLoader
              className="import-loader"
              size={112}
              label={cm.resettingVanilla ? 'Restoring vanilla costumes' : 'Importing costumes'}
              progress={cm.resettingVanilla ? null : batchImportProgress}
              minimumVisibleProgress={6}
            />
            <h3>{cm.resettingVanilla ? 'Resetting to Vanilla...' : 'Importing...'}</h3>
            <p className="import-status">
              {cm.resettingVanilla
                ? 'Removing installed skins and rebuilding the vanilla costume set...'
                : 'Please wait...'}
            </p>
          </div>
        </div>
      )}

      {/* Apply-pose progress overlay */}
      {ap.applying && (
        <div className="import-overlay">
          <div className="import-modal import-modal--hexagon">
            <HexagonLoader
              className="import-loader"
              size={112}
              label={ap.applyingPose?.isOriginal ? 'Restoring portraits' : 'Applying pose'}
              progress={ap.applyProgress.total > 0
                ? ((ap.applyProgress.current - 1) / ap.applyProgress.total) * 100
                : null}
              minimumVisibleProgress={6}
            />
            <h3>{ap.applyingPose?.isOriginal ? 'Restoring Portraits...' : 'Applying Pose...'}</h3>
            <p className="import-status">
              {ap.applyProgress.total > 0
                ? (ap.applyingPose?.isOriginal
                    ? `${ap.applyProgress.current} / ${ap.applyProgress.total}`
                    : `${ap.applyProgress.current} / ${ap.applyProgress.total} — missing portraits are rendered and saved to the vault`)
                : 'Matching costumes to vault skins...'}
            </p>
          </div>
        </div>
      )}

      <ConfirmDialog
        show={!!ap.pendingPose}
        title={ap.pendingPose?.isOriginal ? 'Restore Original Portraits' : 'Apply Pose'}
        message={ap.pendingPose
          ? (ap.pendingPose.isOriginal
              ? `Restore the original portraits for all ${poseCostumeCount} ${poseFighterName} costumes? Each one goes back to its vault skin's main CSP (or the vanilla portrait).`
              : `Apply pose "${ap.pendingPose.name}" to all ${poseCostumeCount} ${poseFighterName} portraits? Costumes without this pose will be rendered and the renders added to the vault.`)
          : ''}
        confirmText={ap.pendingPose?.isOriginal ? 'Restore' : 'Apply'}
        onConfirm={ap.confirmApplyPose}
        onCancel={() => ap.setPendingPose(null)}
      />

      {cc.removingFighter && (
        <div className="import-overlay">
          <div className="import-modal import-modal--hexagon">
            <HexagonLoader className="import-loader" size={112} label="Removing character" />
            <h3>Removing {cc.removingFighterName}...</h3>
            <p className="import-status">Please wait...</p>
          </div>
        </div>
      )}

      {cc.batchAddingChars && (
        <div className="import-overlay">
          <div className="import-modal import-modal--hexagon">
            {/* Indeterminate, NOT a count-based %: the per-fighter prepare is fast
                and the single project build is the long, opaque step — a count bar
                filled to 100% then sat there the whole build (a "lie"). */}
            <HexagonLoader
              className="import-loader"
              size={112}
              label="Adding characters"
              progress={null}
            />
            <h3>Adding Characters...</h3>
            <p className="import-status">
              {cc.batchCharProgress.message
                || (cc.batchCharProgress.total > 0
                      ? `Preparing ${cc.batchCharProgress.current} / ${cc.batchCharProgress.total}…`
                      : 'Preparing…')}
            </p>
          </div>
        </div>
      )}

      <ConfirmDialog
        show={cm.showConfirmDialog}
        title={cm.pendingRemoval?.bulk ? 'Remove Selected Costumes' : 'Remove Costume'}
        message={cm.pendingRemoval
          ? (cm.pendingRemoval.bulk
              ? `Remove ${cm.pendingRemoval.items.length} selected costume(s) from the project?`
              : cm.pendingRemoval.isIceClimbers
              ? `Are you sure you want to remove "${cm.pendingRemoval.costumeName}" (and paired Nana) from Ice Climbers?`
              : `Are you sure you want to remove "${cm.pendingRemoval.costumeName}" from ${cm.pendingRemoval.fighterName}?`)
          : ''}
        confirmText="Remove"
        onConfirm={cm.confirmRemoveCostume}
        onCancel={() => { cm.setShowConfirmDialog(false); cm.setPendingRemoval(null); }}
      />
    </div>
  )
}
