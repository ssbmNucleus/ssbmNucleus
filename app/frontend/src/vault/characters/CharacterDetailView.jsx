/**
 * CharacterDetailView - Character detail with skins/folders
 *
 * Features:
 * - Display character skins in grid with folder support
 * - Drag and drop reordering
 * - Folder management (create, rename, delete)
 * - Edit, CSP manager, context menu integration
 * - Skin creator integration
 */

import { useEffect, useState } from 'react'
import { useAutoAnimate } from '@formkit/auto-animate/react'
import { useInGameTest } from '../hooks/useInGameTest'
import { useFolderManagement } from '../hooks/useFolderManagement'
import { buildDisplayList, countSkinsInFolder } from '../lib/storageViewerUtils'
import { uniqueCostumeDisplayItems } from '../costumeDisplayIdentity'
import { SKIN_SORTS, isCustomSort } from '../lib/vaultSort'
import VaultSortControl from '../VaultSortControl'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import FolderCard from '../FolderCard'
import SkinCard from './SkinCard'
import EditModal from '../EditModal'
import CspManagerModal from '../CspManagerModal'
import SlippiSafetyDialog from '../import/SlippiSafetyDialog'
import ConfirmDialog from '../../shared/ui/ConfirmDialog'
import ContextMenu from '../ContextMenu'
import SkinCreator from '../editors/SkinCreator'
import EmbeddedModelViewer from '../../shared/viewer/EmbeddedModelViewer'
import PoseManagerModal from './poses/PoseManagerModal'
import { getDefaultCostumeCode } from './poses/animData'
import SoundPacksModal from '../sounds/SoundPacksModal'
import ExtrasPageView from '../extras/ExtrasPageView'
import AnimeleeDetectModal from './AnimeleeDetectModal'
import FolderActionsMenu from '../FolderActionsMenu'
import GawColorCreatorModal from './GawColorCreatorModal'
import { hasExtras } from '../../shared/data/extraTypes'
import { API_URL } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'

export default function CharacterDetailView({
  selectedCharacter,
  focusSkinRequest,
  onSkinFocused,
  allCharacters,
  onBack,
  // Folder expansion state — owned by StorageViewer so it persists across
  // character navigation; injected into the colocated useFolderManagement hook
  expandedFolders,
  setExpandedFolders,
  // Display-only sort — owned by StorageViewer, persisted in localStorage.
  // Custom = the stored metadata order; anything else disables reordering.
  sort,
  onSortChange,
  // Shared state clusters — these hooks live in StorageViewer because
  // StageDetailView and grid-level modals consume the same state
  dragDrop,
  editModal,
  cspManager,
  slippiDialog,
  safetyBusy,
  contextMenuApi,
  skinCreator,
  // Identity / data / callbacks
  onSkinCreatorChange,
  onRefresh,
  onCostumesUpdated,
  // Bumped by the vault when the Import button lands an effect in Extras
  extrasRefreshKey,
}) {
  // Drag and drop (shared useDragAndDrop instance)
  const {
    draggedItem,
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
    handleDragEnd,
    handleSkinDrop
  } = dragDrop

  // Edit modal (shared useEditModal instance, incl. confirm dialog state)
  const {
    showEditModal,
    editingItem,
    editName,
    setEditName,
    renaming,
    busy: editBusy,
    deleting,
    exporting,
    show3DViewer,
    setShow3DViewer,
    showConfirmDialog,
    confirmDialogData,
    handleEditClick,
    renameItem,
    replaceStock,
    handleGenerateStock,
    confirmGeneratedStock,
    discardGeneratedStock,
    pendingGeneratedStock,
    generatingStock,
    handleRetakeCsp,
    confirmGeneratedCsp,
    discardGeneratedCsp,
    pendingGeneratedCsp,
    appliedCsp,
    generatingCsp,
    handleDelete,
    handleExport,
    handleCancel,
    confirmDelete,
    cancelDelete
  } = editModal

  // CSP manager (shared useCspManager instance)
  const {
    showCspManager,
    cspManagerSkin,
    portraits,
    busy: cspBusy,
    lastImageUpdate,
    setLastImageUpdate,
    openCspManager,
    closeCspManager,
    handleSetActivePortrait,
    handleRemovePortrait,
    handleUploadMainCsp,
    handleUploadAltCsp
  } = cspManager

  // Slippi safety dialog / retest (shared with import flow at StorageViewer level)
  const {
    showSlippiDialog,
    slippiDialogData,
    retestingItem,
    handleRetestFixChoice,
    handleSlippiChoice,
    handleSlippiRetest,
    handleSlippiOverride
  } = slippiDialog

  // Context menu (state shared with StageDetailView's variant context menu)
  const {
    contextMenu,
    handleSkinContextMenu,
    handleMoveToTop,
    handleMoveToBottom
  } = contextMenuApi

  // Skin creator (state shared with "edit from vault" flow in StageDetailView)
  const {
    showSkinCreator,
    openSkinCreator,
    closeSkinCreator,
    startSkinCreatorFromVault,
    skinCreatorInitialCostume
  } = skinCreator

  // Folder management — exclusive to this view, so the hook lives here.
  // Expansion state is injected from StorageViewer to persist across navigation.
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
    selectedCharacter,
    onRefresh,
    expandedFolders,
    setExpandedFolders
  })

  const charData = allCharacters[selectedCharacter]
  const allSkins = charData?.skins || []
  const skinCount = allSkins.filter(s => s.type !== 'folder' && s.visible !== false).length
  const hasCharacterExtras = hasExtras(selectedCharacter)
  // Use previewOrder during drag for live reordering visual
  const itemsForDisplay = previewOrder || allSkins
  // Index-based drag-reorder addresses the RAW metadata array, so it is only
  // safe under Custom sort; any other sort is display-only and locks reorder.
  const sortIsCustom = isCustomSort(sort)
  const displayList = uniqueCostumeDisplayItems(buildDisplayList(itemsForDisplay, expandedFolders, sort))

  // A bulk deletion or character navigation can invalidate an open editor
  // independently of its own Delete button. Closing also retires its viewer
  // and pending preview work; it must never act on a removed costume.
  useEffect(() => {
    const exists = item => item?.character === selectedCharacter &&
      allSkins.some(skin => skin.type !== 'folder' && skin.id === item.id)
    if (editingItem?.type === 'costume' && !exists(editingItem.data)) handleCancel()
    if (cspManagerSkin && !exists(cspManagerSkin)) closeCspManager()
  }, [selectedCharacter, allSkins, editingItem, cspManagerSkin, handleCancel, closeCspManager])

  // Smooth reorder animations - disable during drag for performance
  const [animateRef, enableAnimations] = useAutoAnimate({ duration: 150 })

  // Disable animations during active drag to avoid lag with many items
  if (isDraggingActive) {
    enableAnimations(false)
  } else {
    enableAnimations(true)
  }

  // In-game test (per costume)
  const inGameTest = useInGameTest()

  // Pose manager state
  const [showPoseManager, setShowPoseManager] = useState(false)
  // The skin whose model a new pose starts on (the costume menu's "New pose"); null = the library.
  const [poseModel, setPoseModel] = useState(null)

  // Animelee auto-detect (geometry inverted-hull outline detector) state
  const [showAnimelee, setShowAnimelee] = useState(false)

  // Sound pack (vanilla character sound bank) state
  const [showSoundBank, setShowSoundBank] = useState(false)
  const isSharedSoundBank = selectedCharacter === 'Zelda' || selectedCharacter === 'Sheik'

  // Extras page state
  const [showExtrasPage, setShowExtrasPage] = useState(false)

  // G&W color creator — replaces the SkinCreator for Mr. Game & Watch, whose
  // colors are engine-side (m-ex GawColors table) rather than DAT textures.
  const isGaw = selectedCharacter === 'Mr. Game & Watch'
  const [showGawCreator, setShowGawCreator] = useState(false)

  // Helper to delete a folder
  const handleDeleteFolder = async (folderId) => {
    try {
      await api.post('/storage/folders/delete', {
        character: selectedCharacter,
        folderId
      })
      await onRefresh()
    } catch (err) {
      console.error('Delete folder error:', err)
      alert(`Failed to delete folder: ${err.message}`)
    }
  }

  // Show extras page if selected
  if (showExtrasPage) {
    return (
      <ExtrasPageView
        character={selectedCharacter}
        onBack={() => setShowExtrasPage(false)}
        onRefresh={onRefresh}
        refreshKey={extrasRefreshKey}
      />
    )
  }

  return (
    <div className="storage-viewer">
      <div className="character-detail">
        <div className="character-header">
          <button
            onClick={() => { playSound('back'); onBack(); }}
            className="back-button"
          >
            &larr; Back to Characters
          </button>
          <VaultSortControl sorts={SKIN_SORTS} sort={sort} onChange={onSortChange} />
          <div className="character-header-actions">
            <button
              className="character-action-button"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); setShowSoundBank(true); }}
              aria-label="Sounds"
              title="Customize this character's voice and sound effects — installed into every ISO you export"
            >
              🔊
            </button>
            <button
              className="character-action-button"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); setShowPoseManager(true); }}
              aria-label="Poses"
              title="Create and manage CSP / portrait poses for this character's costumes"
            >
              🎭
            </button>
            <FolderActionsMenu
              onNewFolder={handleCreateFolder}
              onDetectAnimelee={() => setShowAnimelee(true)}
            />
            {hasCharacterExtras && (
              <button
                className="character-action-button character-action-button--extras"
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setShowExtrasPage(true); }}
              >
                Extras
              </button>
            )}
          </div>
        </div>

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
                  folderSkinCount={countSkinsInFolder(folderId, allSkins)}
                  reordering={reordering}
                  canDrag={sortIsCustom}
                  onToggle={toggleFolder}
                  onDragStart={(e) => handleDragStart(e, itemsForDisplay.findIndex(s => s.id === folderId), itemsForDisplay)}
                  onDragOver={handleDragOver}
                  onDragEnter={(e) => handleDragEnter(e, itemsForDisplay.findIndex(s => s.id === folderId), itemsForDisplay)}
                  onDragLeave={handleDragLeave}
                  onDrop={handleSkinDrop}
                  onDragEnd={handleDragEnd}
                  onEditingFolderNameChange={setEditingFolderName}
                  onSaveFolderName={saveFolderName}
                  onCancelEdit={() => setEditingFolderId(null)}
                  onStartEditing={startEditingFolder}
                  onDelete={handleDeleteFolder}
                  justDraggedRef={justDraggedRef}
                />
              )
            } else {
              const skinId = item.skin.id
              return (
                <SkinCard
                  key={skinId}
                  focusRequest={focusSkinRequest?.skinId === skinId ? focusSkinRequest : null}
                  onFocused={onSkinFocused}
                  skin={item.skin}
                  selectedCharacter={selectedCharacter}
                  folderId={item.folderId}
                  displayIdx={idx}
                  arrayIdx={item.arrayIndex}
                  isDragging={draggedItem && skinId === draggedItem.id}
                  isDropTarget={false}
                  isJustDropped={justDroppedId === skinId}
                  reordering={reordering}
                  canDrag={sortIsCustom}
                  lastImageUpdate={lastImageUpdate}
                  onDragStart={(e) => handleDragStart(e, itemsForDisplay.findIndex(s => s.id === skinId), itemsForDisplay)}
                  onDragOver={handleDragOver}
                  onDragEnter={(e) => handleDragEnter(e, itemsForDisplay.findIndex(s => s.id === skinId), itemsForDisplay)}
                  onDragLeave={handleDragLeave}
                  onDrop={handleSkinDrop}
                  onDragEnd={handleDragEnd}
                  onContextMenu={sortIsCustom ? handleSkinContextMenu : null}
                  onEditClick={handleEditClick}
                  justDraggedRef={justDraggedRef}
                />
              )
            }
          })}
          <div
            className="create-mod-card"
            onMouseEnter={playHoverSound}
            onClick={() => {
              playSound('start')
              if (isGaw) setShowGawCreator(true)
              else openSkinCreator()
            }}
          >
            <div className="create-mod-image-area">
              <span className="create-mod-icon">+</span>
              <span className="create-mod-label">{isGaw ? 'Create New Color' : 'Create New Mod'}</span>
            </div>
          </div>
        </div>

      </div>
      <EditModal
        show={showEditModal}
        editingItem={editingItem}
        covered={Boolean(show3DViewer || showCspManager || showSlippiDialog || showConfirmDialog || showSkinCreator
          || showPoseManager)}
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
        onReplaceStock={replaceStock}
        onGenerateStock={handleGenerateStock}
        onConfirmGeneratedStock={confirmGeneratedStock}
        onDiscardGeneratedStock={discardGeneratedStock}
        pendingGeneratedStock={pendingGeneratedStock}
        generatingStock={generatingStock}
        onRetakeCsp={handleRetakeCsp}
        onNewPose={(skin) => { setPoseModel(skin.id); setShowPoseManager(true) }}
        onConfirmGeneratedCsp={confirmGeneratedCsp}
        onDiscardGeneratedCsp={discardGeneratedCsp}
        pendingGeneratedCsp={pendingGeneratedCsp}
        appliedCsp={appliedCsp}
        generatingCsp={generatingCsp}
        onSlippiRetest={handleSlippiRetest}
        onSlippiOverride={handleSlippiOverride}
        safetyBusy={safetyBusy}
        onOpenCspManager={openCspManager}
        onStartSkinCreator={startSkinCreatorFromVault}
        onView3D={() => setShow3DViewer(true)}
        onTestInGame={() => inGameTest.startCostumeTest({
          character: editingItem?.data?.character,
          skinId: editingItem?.data?.id,
          colorName: editingItem?.data?.color
        })}
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
          title={editingItem.data.color || editingItem.data.name}
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
        onOpenPoseManager={() => { closeCspManager(); setShowPoseManager(true); }}
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
      <SkinCreator
        isOpen={showSkinCreator}
        onClose={closeSkinCreator}
        selectedCharacter={selectedCharacter}
        onSkinCreatorChange={onSkinCreatorChange}
        onRefresh={onRefresh}
        initialCostume={skinCreatorInitialCostume}
      />
      <PoseManagerModal
        show={showPoseManager}
        character={selectedCharacter}
        models={(() => {
          const backendBase = API_URL.replace('/api/mex', '')
          const def = getDefaultCostumeCode(selectedCharacter)
          const list = allSkins
            .filter(s => s.type !== 'folder')
            .map(s => ({
              value: s.id,
              label: s.color || s.id,
              skinId: s.id,
              cspUrl: s.has_csp
                ? `${backendBase}/storage/${selectedCharacter}/${s.csp_filename || `${s.id}_csp.png`}`
                : null,
              stockUrl: s.has_stock ? `${backendBase}/storage/${selectedCharacter}/${s.id}_stc.png` : null
            }))
          return def ? [{ value: '__default__', label: 'Default', costumeCode: def }, ...list] : list
        })()}
        createWith={poseModel}
        onClose={() => { setShowPoseManager(false); setPoseModel(null) }}
        onRefresh={onRefresh}
        onCostumesUpdated={onCostumesUpdated}
      />
      <SoundPacksModal
        show={showSoundBank}
        character={selectedCharacter}
        displayName={isSharedSoundBank ? 'Zelda / Sheik' : selectedCharacter}
        onClose={() => setShowSoundBank(false)}
      />

      {showAnimelee && (
        <AnimeleeDetectModal
          character={selectedCharacter}
          onClose={() => setShowAnimelee(false)}
          onApplied={onRefresh}
        />
      )}

      <GawColorCreatorModal
        show={showGawCreator}
        onClose={() => setShowGawCreator(false)}
        onCreated={() => onRefresh && onRefresh()}
      />
    </div>
  )
}
