/**
 * StageMode - MEX stage variant management with Dynamic Alternate Stages (DAS)
 *
 * Features:
 * - DAS framework installation
 * - Stage list with variant counts
 * - MEX variants panel with button token assignment
 * - Available variants panel with batch selection/import
 * - Button token UI for variant assignment
 *
 * Orchestrator component - state and UI live in ./stagemode/:
 * - useStageVariants: DAS install/fetch/import/remove/button-token logic
 * - useCustomStages: custom stage vault/project fetch/install/remove logic
 * - useStageSlots: the non-tournament stages (one replace slot each)
 * - StageList, VariantsPanel, CustomStagesPanel, SlotPanel: UI
 */
import ConfirmDialog from '../shared/ui/ConfirmDialog'
import HexagonLoader from '../shared/ui/HexagonLoader'
import useStageVariants from './stages/useStageVariants'
import useCustomStages from './stages/useCustomStages'
import useStageSlots from './stages/useStageSlots'
import StageList from './stages/StageList'
import VariantsPanel from './stages/VariantsPanel'
import CustomStagesPanel from './stages/CustomStagesPanel'
import SlotPanel from './stages/SlotPanel'

export default function StageMode({
  mode,
  onModeChange,
  onRefresh,
  refreshing,
  onOpenMenuMusic,
}) {
  const sm = useStageVariants({ onRefresh })
  const cs = useCustomStages({ onRefresh })
  const ss = useStageSlots({ onRefresh })

  const batchImportProgress = sm.batchImporting && sm.batchProgress.total > 0
    ? (sm.batchProgress.current / sm.batchProgress.total) * 100
    : null

  // The DAS framework only gates the six tournament stages. Custom Stages and
  // the other versus stages work without it, so the list always renders and
  // the install prompt lives in the right-hand panel (shown by default and
  // whenever a DAS stage is picked before the framework exists).
  const selected = sm.selectedStage
  const isDasStage = !!selected && !selected.isCustom && !selected.isSlot
  const showDasPrompt = !sm.dasInstalled && (!selected || isDasStage)

  const dasPrompt = (
    <div className="das-install-prompt">
      <h3>Dynamic Alternate Stages Not Installed</h3>
      <p>Install the DAS framework to manage alternate stage variants for your 6 competitive stages. The other stages and Custom Stages work without it.</p>
      <button
        className="btn-primary"
        onClick={sm.installDAS}
        disabled={sm.dasChecking}
      >
        {sm.dasChecking ? 'Installing...' : 'Install DAS Framework'}
      </button>
    </div>
  )

  return (
    <div className="mex-content">
      <StageList mode={mode} onModeChange={onModeChange} onOpenMenuMusic={onOpenMenuMusic} sm={sm} cs={cs} ss={ss} />

      <div className={`costumes-panel ${refreshing ? 'refreshing' : ''}`}>
        {showDasPrompt ? (
          dasPrompt
        ) : selected?.isCustom ? (
          <CustomStagesPanel cs={cs} />
        ) : selected?.isSlot ? (
          <SlotPanel stage={selected} ss={ss} cs={cs} />
        ) : selected ? (
          <VariantsPanel sm={sm} />
        ) : (
          <div className="no-selection">
            <p>Select a stage to view variants</p>
          </div>
        )}
      </div>

      {/* Import Loading Overlay */}
      {(sm.importing || sm.batchImporting) && (
        <div className="import-overlay">
          <div className="import-modal import-modal--hexagon">
            <HexagonLoader
              className="import-loader"
              size={112}
              label="Importing stage variants"
              progress={batchImportProgress}
              minimumVisibleProgress={6}
            />
            <h3>Importing...</h3>
            <p className="import-status">Installing selected variants...</p>
          </div>
        </div>
      )}

      {cs.batchInstallingStages && (
        <div className="import-overlay">
          <div className="import-modal import-modal--hexagon">
            {/* Indeterminate (see CharacterMode): the build step is the long,
                opaque part, so a count-based bar would lie. */}
            <HexagonLoader
              className="import-loader"
              size={112}
              label="Adding stages"
              progress={null}
            />
            <h3>Adding Stages...</h3>
            <p className="import-status">
              {cs.batchStageProgress.message
                || (cs.batchStageProgress.total > 0
                      ? `Preparing ${cs.batchStageProgress.current} / ${cs.batchStageProgress.total}…`
                      : 'Preparing…')}
            </p>
          </div>
        </div>
      )}

      <ConfirmDialog
        show={sm.showConfirmDialog}
        title={sm.pendingRemoval?.bulk ? 'Remove Selected Variants' : 'Remove Variant'}
        message={sm.pendingRemoval
          ? (sm.pendingRemoval.bulk
              ? `Remove ${sm.pendingRemoval.items.length} selected stage variant(s) from the project?`
              : `Are you sure you want to remove "${sm.pendingRemoval.variantName}"?`)
          : ''}
        confirmText="Remove"
        onConfirm={sm.confirmRemoveVariant}
        onCancel={() => { sm.setShowConfirmDialog(false); sm.setPendingRemoval(null); }}
      />
    </div>
  )
}
