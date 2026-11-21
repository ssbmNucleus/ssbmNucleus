import SkinCreator from '../editors/SkinCreator'
import { EditorContext } from '../../shared/lib/EditorContext'
/**
 * StageDetailView - Stage detail with variants
 *
 * Features:
 * - Display stage variants in grid
 * - Drag and drop reordering with smooth animations
 * - Edit, CSP manager, context menu integration
 */

import { useContext, useEffect, useMemo, useState } from 'react'
import { useAutoAnimate } from '@formkit/auto-animate/react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { useFolderManagement } from '../hooks/useFolderManagement'
import { buildDisplayList, countSkinsInFolder } from '../lib/storageViewerUtils'
import { STAGE_SORTS, isCustomSort } from '../lib/vaultSort'
import VaultSortControl from '../VaultSortControl'
import FolderCard from '../FolderCard'
import EditModal from '../EditModal'
import CspManagerModal from '../CspManagerModal'
import SlippiSafetyDialog from '../import/SlippiSafetyDialog'
import ConfirmDialog from '../../shared/ui/ConfirmDialog'
import ContextMenu from '../ContextMenu'
import EmbeddedModelViewer from '../../shared/viewer/EmbeddedModelViewer'
import { useInGameTest } from '../hooks/useInGameTest'
import { backendMediaUrl } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'
import { createCardActivation } from '../cardActivation'

// Stage variant folders reuse the costume folder UI/hook against the stage
// folder endpoints (see storage_stages.py).
const STAGE_FOLDER_ROUTES = {
  create: '/storage/stage-folders/create',
  rename: '/storage/stage-folders/rename',
  delete: '/storage/stage-folders/delete',
  toggle: '/storage/stage-folders/toggle'
}

export default function StageDetailView({
  onSkinCreatorChange,
  selectedStage,
  editorRequest,
  onEditorRequestHandled,
  stageVariants,
  onBack,
  // Folder expansion state (owned by StorageViewer so it persists across nav)
  expandedFolders,
  setExpandedFolders,
  // Display-only sort — Custom = the stored metadata order; anything else
  // disables index-based reordering
  sort,
  onSortChange,
  // Drag and drop
  draggedItem,
  dragOverIndex,
  previewOrder,
  reordering,
  isDraggingActive,
  justDroppedId,
  justDraggedRef,
  dragTargetFolder,
  handleDragStart,
  handleDragOver,
  handleDragEnter,
  handleDragLeave,
  handleVariantDrop,
  handleDragEnd,
  // Context menu
  handleVariantContextMenu,
  contextMenu,
  handleMoveToTop,
  handleMoveToBottom,
  // Edit modal
  showEditModal,
  editingItem,
  editName,
  setEditName,
  renameItem,
  renaming,
  editBusy,
  deleting,
  exporting,
  lastImageUpdate,
  handleCancel,
  handleDelete,
  handleExport,
  replaceScreenshot,
  setStageSafety,
  replaceStageScreenshotWithCapture,
  handleSlippiRetest,
  handleSlippiOverride,
  openCspManager,
  startSkinCreatorFromVault,
  show3DViewer,
  setShow3DViewer,
  handleEditClick,
  // CSP Manager
  showCspManager,
  cspManagerSkin,
  portraits,
  cspBusy,
  closeCspManager,
  handleSetActivePortrait,
  handleRemovePortrait,
  handleUploadMainCsp,
  handleUploadAltCsp,
  // Slippi dialog
  showSlippiDialog,
  slippiDialogData,
  retestingItem,
  handleRetestFixChoice,
  handleSlippiChoice,
  // Confirm dialog
  showConfirmDialog,
  confirmDialogData,
  confirmDelete,
  cancelDelete,
  // Refresh after a variant is saved
  onRefresh,
  // Refresh the stage variants list (folder ops change it, not metadata alone)
  onRefreshVariants,
  // API
}) {
  const activation = useMemo(() => createCardActivation(justDraggedRef), [justDraggedRef])
  // Folder ops and reorders need the variants list refetched AND metadata
  // refreshed; bundle both so the folder hook and delete handler stay in sync.
  const refreshAll = async () => {
    if (onRefreshVariants) await onRefreshVariants()
    if (onRefresh) await onRefresh()
  }
  const stageInfo = selectedStage
  // `variants` now includes inline folder entries (type:'folder') emitted by the
  // das variants endpoint, in metadata order — same shape as character skins.
  const editorContext = useContext(EditorContext)
  const [stageEditor, setStageEditor] = useState(null)
  const openStageEditor = (variant, withRandall = false) => {
    const item = { id: variant?.id || `vanilla-${selectedStage.code}`, variantId: variant?.id,
      name: variant?.name || selectedStage.name, character: selectedStage.name, stageCode: selectedStage.code }
    setStageEditor(item)
    if (withRandall) editorContext?.beginStageEditor(item)
  }
  useEffect(() => {
    if (!editorRequest || editorRequest.stageCode !== selectedStage.code) return
    openStageEditor(editorRequest, true)
    onEditorRequestHandled?.()
  }, [editorRequest, selectedStage.code])
  const variants = stageVariants[selectedStage.code] || []
  const variantCount = variants.filter(v => v.type !== 'folder').length

  // Folder management — stage routes, keyed by the stage's storage folder.
  const {
    editingFolderId,
    setEditingFolderId,
    editingFolderName,
    setEditingFolderName,
    toggleFolder,
    handleCreateFolder,
    startEditingFolder,
    saveFolderName
  } = useFolderManagement({
    idField: 'stageFolder',
    idValue: selectedStage.folder,
    routes: STAGE_FOLDER_ROUTES,
    onRefresh: refreshAll,
    expandedFolders,
    setExpandedFolders
  })

  // Use previewOrder during drag for live reordering visual
  const itemsForDisplay = previewOrder || variants
  const sortIsCustom = isCustomSort(sort)
  const displayList = buildDisplayList(itemsForDisplay, expandedFolders || {}, sort)

  const handleDeleteFolder = async (folderId) => {
    try {
      await api.post('/storage/stage-folders/delete', {
        stageFolder: selectedStage.folder,
        folderId
      })
      await refreshAll()
    } catch (err) {
      console.error('Delete folder error:', err)
      alert(`Failed to delete folder: ${err.message}`)
    }
  }

  // In-game test (per stage skin / DAS variant)
  const inGameTest = useInGameTest()

  // Smooth reorder animations
  const [animateRef] = useAutoAnimate({ duration: 200 })

  return (
    <div className="storage-viewer">
      <div className="character-detail">
        <div className="character-header">
          <button
            onClick={() => { playSound('back'); onBack(); }}
            className="back-button"
          >
            ← Back to Stages
          </button>
          <VaultSortControl sorts={STAGE_SORTS} sort={sort} onChange={onSortChange} />
          <div className="character-header-actions">
            <button
              className="character-action-button"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); handleCreateFolder(); }}
              aria-label="New folder"
              title="Create a folder to group this stage's variants"
            >
              📁
            </button>
          </div>
        </div>

        {variantCount === 0 && (
          <div className="no-skins-message">
            <p>No stage variants yet. Add some to your storage!</p>
          </div>
        )}
        <div className={`skins-grid${isDraggingActive ? ' is-dragging' : ''}`} ref={animateRef}>
            {displayList.map((item, idx) => {
              if (item.type === 'folder') {
                const folderId = item.folder.id
                return (
                  <FolderCard
                    key={folderId}
                    folder={item.folder}
                    isExpanded={item.isExpanded}
                    displayIdx={idx}
                    arrayIdx={item.arrayIndex}
                    isDragging={draggedItem && draggedItem.id === folderId}
                    isDropTarget={dragTargetFolder === folderId}
                    isJustDropped={justDroppedId === folderId}
                    isEditing={editingFolderId === folderId}
                    editingFolderName={editingFolderName}
                    folderSkinCount={countSkinsInFolder(folderId, variants)}
                    reordering={reordering}
                    canDrag={sortIsCustom}
                    onToggle={toggleFolder}
                    onDragStart={(e) => handleDragStart(e, itemsForDisplay.findIndex(s => s.id === folderId), itemsForDisplay)}
                    onDragOver={handleDragOver}
                    onDragEnter={(e) => handleDragEnter(e, itemsForDisplay.findIndex(s => s.id === folderId), itemsForDisplay)}
                    onDragLeave={handleDragLeave}
                    onDrop={handleVariantDrop}
                    onDragEnd={handleDragEnd}
                    onEditingFolderNameChange={setEditingFolderName}
                    onSaveFolderName={saveFolderName}
                    onCancelEdit={() => setEditingFolderId(null)}
                    onStartEditing={startEditingFolder}
                    onDelete={handleDeleteFolder}
                    justDraggedRef={justDraggedRef}
                    itemNoun="variant"
                  />
                )
              }
              const variant = item.skin
              const isDragging = draggedItem && variant.id === draggedItem.id
              const openEditor = () => {
                playSound('boop')
                handleEditClick('stage', {
                  id: variant.id,
                  name: variant.name,
                  stageCode: stageInfo?.code,
                  stageFolder: stageInfo?.folder,
                  stageName: stageInfo?.name,
                  screenshotUrl: variant.screenshotUrl,
                  hasScreenshot: variant.hasScreenshot,
                  slippi_safe: variant.slippi_safe,
                  slippi_tested: variant.slippi_tested,
                  transformationSkins: variant.transformationSkins
                })
              }
              return (
                <div
                  key={variant.id}
                  className={`skin-card ${isDragging ? 'dragging' : ''}`}
                  role="button"
                  tabIndex={0}
                  aria-label={`Edit ${variant.name || 'stage variant'}`}
                  draggable={!reordering && sortIsCustom}
                  onMouseEnter={playHoverSound}
                  onPointerDown={activation.onPointerDown}
                  onPointerMove={activation.onPointerMove}
                  onPointerCancel={activation.onPointerCancel}
                  onClick={(e) => activation.onClick(e, openEditor)}
                  onKeyDown={(e) => activation.onKeyDown(e, openEditor)}
                  onDragStart={(e) => {
                    activation.onDragStart()
                    handleDragStart(e, itemsForDisplay.findIndex(s => s.id === variant.id), itemsForDisplay)
                  }}
                  onDragOver={handleDragOver}
                  onDragEnter={(e) => handleDragEnter(e, itemsForDisplay.findIndex(s => s.id === variant.id), itemsForDisplay)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleVariantDrop(e)}
                  onDragEnd={handleDragEnd}
                  onContextMenu={sortIsCustom ? (e) => handleVariantContextMenu(e, variant, idx) : undefined}
                  style={{ opacity: isDragging ? 0.5 : 1 }}
                >
                <div className="skin-images">
                  <div className="skin-image-container">
                    {variant.hasScreenshot ? (
                      <img
                        src={backendMediaUrl(`${variant.screenshotUrl}?t=${lastImageUpdate}`)}
                        alt={variant.name}
                        className="skin-csp"
                        onError={(e) => {
                          e.target.style.display = 'none'
                          e.target.nextSibling.style.display = 'flex'
                        }}
                      />
                    ) : (
                      <div className="skin-placeholder" style={{ display: 'flex' }}>
                        <span className="skin-initial">{variant.name[0]}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
          <button type="button" className="create-mod-card" onMouseEnter={playHoverSound} onClick={() => { playSound('start'); openStageEditor(null) }}>
            <div className="create-mod-image-area"><span className="create-mod-icon">+</span><span className="create-mod-label">Create New Mod</span></div>
          </button>
        </div>
      </div>
      <EditModal
        show={showEditModal}
        editingItem={editingItem}
        covered={Boolean(show3DViewer || showCspManager || showSlippiDialog || showConfirmDialog)}
        editName={editName}
        onNameChange={setEditName}
        onRename={renameItem}
        renaming={renaming}
        busy={editBusy}
        deleting={deleting}
        exporting={exporting}
        lastImageUpdate={lastImageUpdate}
        onClose={() => { inGameTest.resetTest(); handleCancel(); }}
        onDelete={handleDelete}
        onExport={handleExport}
        onReplaceScreenshot={replaceScreenshot}
        onSetStageSafety={setStageSafety}
        onOpenCspManager={openCspManager}
        onStartSkinCreator={variant => { inGameTest.resetTest(); handleCancel(); openStageEditor(variant) }}
        onView3D={() => setShow3DViewer(true)}
        onTestInGame={() => inGameTest.startStageSkinTest({
          stageCode: editingItem?.data?.stageCode,
          stageFolder: editingItem?.data?.stageFolder,
          variantId: editingItem?.data?.id,
          name: editingItem?.data?.name
        })}
        onCaptureScreenshot={() => inGameTest.captureStageScreenshot({
          stageCode: editingItem?.data?.stageCode,
          stageFolder: editingItem?.data?.stageFolder,
          variantId: editingItem?.data?.id,
          name: editingItem?.data?.name
        })}
        onReplaceWithCapture={(shot) => {
          inGameTest.resetTest()
          replaceStageScreenshotWithCapture(shot)
        }}
        testingInGame={inGameTest.testingInGame}
        testStatus={inGameTest.testStatus}
        testResult={inGameTest.testResult}
        testError={inGameTest.testError}
        testMode={inGameTest.testMode}
        stoppingTest={inGameTest.stoppingTest}
        stopError={inGameTest.stopError}
        onStopTest={inGameTest.stopTest}
        onResetTest={inGameTest.resetTest}
      />
      {show3DViewer && editingItem && editingItem.type === 'costume' && (
        <EmbeddedModelViewer
          character={editingItem.data.character}
          skinId={editingItem.data.id}
          onClose={() => setShow3DViewer(false)}
        />
      )}
      <CspManagerModal
        show={showCspManager}
        skin={cspManagerSkin}
        portraits={portraits}
        lastImageUpdate={lastImageUpdate}
        busy={cspBusy}
        onClose={closeCspManager}
        onSetActive={handleSetActivePortrait}
        onRemove={handleRemovePortrait}
        onReplaceOriginal={handleUploadMainCsp}
        onAddPortrait={handleUploadAltCsp}
      />
      <SlippiSafetyDialog
        show={showSlippiDialog}
        data={slippiDialogData}
        onChoice={retestingItem !== null ? handleRetestFixChoice : handleSlippiChoice}
        isRetest={retestingItem !== null}
      />
      <ConfirmDialog
        show={showConfirmDialog}
        title={confirmDialogData?.title}
        message={confirmDialogData?.message}
        confirmText={confirmDialogData?.confirmText}
        onConfirm={confirmDelete}
        onCancel={cancelDelete}
      />
      <ContextMenu
        contextMenu={contextMenu}
        onMoveToTop={handleMoveToTop}
        onMoveToBottom={handleMoveToBottom}
      />
      {stageEditor && <SkinCreator onSkinCreatorChange={onSkinCreatorChange} isOpen selectedCharacter={stageEditor.character} initialCostume={stageEditor}
        onClose={() => { setStageEditor(null); editorContext?.closeEditor() }} onRefresh={refreshAll} />}
    </div>
  )
}
