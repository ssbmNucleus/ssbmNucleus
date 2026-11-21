import { useState, useEffect, useCallback } from 'react'
import './StorageViewer.css'
import { useContext } from 'react'
import { EditorContext } from '../shared/lib/EditorContext'
import './VaultGrids.css'
import './CustomDetailViews.css'
import './stages/StageCards.css'
import './characters/CharacterSkinCards.css'
import './patches/PatchesGrid.css'
import './extras/ExtrasPage.css'
import './extras/ExtraEditorModal.css'
import './FolderCards.css'
import './menus/VaultMenusView.css'
import '../shared/ui/ExportModal.css'
import '../shared/ui/ProgressPanel.css'
import { DEFAULT_CHARACTERS } from '../shared/data/defaultCharacters'
import EmbeddedModelViewer from '../shared/viewer/EmbeddedModelViewer'
import SlippiSafetyDialog from './import/SlippiSafetyDialog'
import DuplicateImportDialog from './import/DuplicateImportDialog'
import ChoiceImportDialog from './import/ChoiceImportDialog'
import ConfirmDialog from '../shared/ui/ConfirmDialog'
import EditModal from './EditModal'
import PatchModals from './patches/PatchModals'
import XdeltaBuildModal from '../projects/export/XdeltaBuildModal'
import ModeToolbar from './ModeToolbar'
import CharactersGrid from './characters/CharactersGrid'
import StagesGrid from './stages/StagesGrid'
import BulkStageCaptureModal from './stages/BulkStageCaptureModal'
import BulkCharacterCspModal from './characters/BulkCharacterCspModal'
import PatchesGrid from './patches/PatchesGrid'
import CharacterDetailView from './characters/CharacterDetailView'
import StageDetailView from './stages/StageDetailView'
import CustomStagesGrid from './stages/CustomStagesGrid'
import MoreStagesGrid from './stages/MoreStagesGrid'
import CustomStageDetailView from './stages/CustomStageDetailView'
import CustomCharactersGrid from './characters/CustomCharactersGrid'
import CustomCharacterDetailView from './characters/CustomCharacterDetailView'
import PlayOverlay from './PlayOverlay'
import VaultMenusView from './menus/VaultMenusView'
import { DEFAULT_MENU_KIND } from './menus/menuKinds'
import VaultImportSurface from './import/VaultImportSurface'
import { useDragAndDrop } from './hooks/useDragAndDrop'
import { useFileImport } from './import/useFileImport'
import { useVaultLists } from './hooks/useVaultLists'
import { useVaultPatches } from './hooks/useVaultPatches'
import { useVaultPlay } from './hooks/useVaultPlay'
import { useVaultContextMenu } from './hooks/useVaultContextMenu'
import { useVaultItemEditing } from './hooks/useVaultItemEditing'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { loadVaultSort, saveVaultSort } from './lib/vaultSort'
import { backendMediaUrl } from '../shared/config/config'

export default function StorageViewer({ metadata, onRefresh, onSkinCreatorChange, onAssistantContext, vaultNavigation, onVaultNavigationComplete }) {
  const assistantEditor = useContext(EditorContext)
  const [mode, setMode] = useState('characters') // 'characters', 'stages', 'patches', or 'menus'
  const [isLoading, setIsLoading] = useState(true)
  const [selectedCharacter, setSelectedCharacter] = useState(null)
  const [selectedStage, setSelectedStage] = useState(null)
  const [stageEditorRequest, setStageEditorRequest] = useState(null)
  useEffect(() => {
    onAssistantContext?.({ character: mode === 'characters' ? selectedCharacter : null,
      stage: mode === 'stages' ? selectedStage?.name || null : null })
  }, [mode, selectedCharacter, selectedStage, onAssistantContext])
  useEffect(() => {
    if (!vaultNavigation || !metadata) return
    if (vaultNavigation.kind === 'stage') {
      const { stage, variant, editor } = vaultNavigation
      setMode('stages'); setSelectedCharacter(null); setSelectedStage({ ...stage, vanillaImage: stage.artUrl ? backendMediaUrl(stage.artUrl) : undefined })
      setShowCustomStages(false); setShowMoreStages(false); setSelectedCustomStage(null)
      setShowCustomCharacters(false); setSelectedCustomCharacter(null)
      setStageVariants(previous => ({ ...previous, [stage.code]: [...(previous[stage.code] || []).filter(v => v.id !== variant.id), variant] }))
      if (editor) setStageEditorRequest({ ...variant, stageCode: stage.code })
      else handleEditClick('stage', { ...variant, stageCode: stage.code, stageFolder: stage.folder, stageName: stage.name })
      onVaultNavigationComplete?.()
      return
    }
    const { character, skinId } = vaultNavigation
    const info = metadata.characters?.[character]
    if (!info) { if (vaultNavigation.editor) assistantEditor?.closeEditor(); onVaultNavigationComplete?.(); return }
    setMode('characters'); setSelectedCharacter(character)
    setShowCustomCharacters(false); setSelectedCustomCharacter(null)
    const skin = info.skins?.find(item => item.id === skinId && item.type !== 'folder' && item.visible !== false)
    if (!skin) { if (vaultNavigation.editor) assistantEditor?.closeEditor(); onVaultNavigationComplete?.(); return }
    if (vaultNavigation.editor) {
      setSkinCreatorInitialCostume({ ...skin, character })
      setShowSkinCreator(true)
      onVaultNavigationComplete?.()
      return
    }
    if (skin.folder_id) setExpandedFolders(previous => previous[skin.folder_id] ? previous : { ...previous, [skin.folder_id]: true })
  }, [metadata, vaultNavigation, onVaultNavigationComplete])
  // Menus mode: the selected kind (see menus/menuKinds.js), whether one of
  // its editors is open (hides the sidebar), and a tick that re-fetches the
  // lists after the floating Import button lands a menu mod.
  const [selectedMenuKind, setSelectedMenuKind] = useState(DEFAULT_MENU_KIND)
  const [menuDetailOpen, setMenuDetailOpen] = useState(false)
  const [menuRefreshKey, setMenuRefreshKey] = useState(0)
  const refreshMenuMods = useCallback(() => setMenuRefreshKey((k) => k + 1), [])
  // Same tick for a character's Extras page after the Import button lands
  // an effect file there.
  const [extrasRefreshKey, setExtrasRefreshKey] = useState(0)
  const refreshExtras = useCallback(() => setExtrasRefreshKey((k) => k + 1), [])
  const {
    stageVariants, setStageVariants, bundles, customStages, customCharacters, pendingBuiltins,
    fetchStageVariants, fetchCustomStages, fetchCustomCharacters, fetchBundles,
  } = useVaultLists()
  const [showBulkCapture, setShowBulkCapture] = useState(false)
  // Vault-wide bulk CSP retake (the characters-mode twin of showBulkCapture)
  const [showBulkRetake, setShowBulkRetake] = useState(false)

  // "Play" (launch in real Slippi) state + handlers - shared by bundles and
  // patches. Each Play is a backend job the hook follows.
  const {
    playingId,
    playPercent,
    playMessage,
    playError,
    playLaunched,
    handlePlayBundle,
    handlePlayPatch,
    dismissPlay
  } = useVaultPlay()

  // Custom stages state (sub-page within stages mode)
  const [showCustomStages, setShowCustomStages] = useState(false)
  const [showMoreStages, setShowMoreStages] = useState(false)
  const [selectedCustomStage, setSelectedCustomStage] = useState(null)

  // Custom characters state (sub-page within characters mode)
  const [showCustomCharacters, setShowCustomCharacters] = useState(false)
  const [selectedCustomCharacter, setSelectedCustomCharacter] = useState(null)

  // Slippi retest dialog state (for retest from edit modal)

  const [showSkinCreator, setShowSkinCreator] = useState(false) // Skin creator modal
  const [skinCreatorInitialCostume, setSkinCreatorInitialCostume] = useState(null) // For "edit from vault" flow

  // Drag and drop hook
  const {
    draggedItem,
    dragOverIndex,
    previewOrder,
    reordering,
    setReordering,
    justDraggedRef,
    isDraggingActive,
    justDroppedId,
    dragTargetFolder,
    handleDragStart,
    handleDragOver,
    handleDragEnter,
    handleDragLeave,
    handleSkinDrop,
    handleVariantDrop,
    handleDragEnd
  } = useDragAndDrop({
    mode,
    selectedCharacter,
    selectedStage,
    onRefresh,
    fetchStageVariants
  })

  // Right-click menu for skins / stage variants (needs setReordering above)
  const {
    contextMenu,
    handleSkinContextMenu,
    handleVariantContextMenu,
    handleMoveToTop,
    handleMoveToBottom
  } = useVaultContextMenu({
    selectedCharacter,
    selectedStage,
    onRefresh,
    fetchStageVariants,
    setReordering
  })

  // Folder expansion state — owned here so it persists when CharacterDetailView
  // unmounts on Back. The rest of folder management (useFolderManagement) now
  // lives inside CharacterDetailView, which this state is injected into.
  const [expandedFolders, setExpandedFolders] = useState({})

  // Vault sort ({skins: {key,dir}, stages: {key,dir}}) — display-only; the
  // stored metadata order stays the "Custom" sort. Persisted in localStorage.
  const [vaultSort, setVaultSort] = useState(loadVaultSort)
  const changeVaultSort = (kind, next) => {
    setVaultSort((prev) => {
      const updated = { ...prev, [kind]: next }
      saveVaultSort(updated)
      return updated
    })
  }

  // Patches mode: xdelta patches and `.ssbm` bundles, whose builds and
  // installs are backend jobs (see useVaultPatches). The dialogs render in
  // PatchModals.
  const patches = useVaultPatches({ fetchBundles })
  const {
    xdeltaPatches, fetchXdeltaPatches, handleEditXdelta, handleBuildXdeltaIso, setShowXdeltaCreateModal,
    handleEditBundle, handleInstallBundle, showXdeltaBuildModal, xdeltaBuildState, xdeltaBuildPatch,
    xdeltaBuildProgress, xdeltaBuildMessage, xdeltaBuildFilename, xdeltaBuildError, closeXdeltaBuildModal,
    handleDownloadXdeltaIso,
  } = patches

  // Unified file import — one pipeline for everything the backend can
  // auto-detect (costumes, stages, custom characters/stages, bundles,
  // patches, menu mods). Fed by the floating Import button and window-wide
  // drag-and-drop; refreshes whichever vault list each import lands in.
  // (Declared after the xdelta/bundle hooks so their fetchers exist.)
  const {
    importing,
    importMessage,
    showSlippiDialog,
    setShowSlippiDialog,
    slippiDialogData,
    setSlippiDialogData,
    pendingFile,
    setPendingFile,
    showDuplicateDialog,
    duplicateDialogData,
    showChoiceDialog,
    choiceDialogData,
    handleFileImport,
    handleSlippiChoice,
    handleDuplicateChoice,
    handleChoice
  } = useFileImport({
    refreshers: {
      metadata: onRefresh,
      stageVariants: fetchStageVariants,
      customCharacters: fetchCustomCharacters,
      customStages: fetchCustomStages,
      patches: fetchXdeltaPatches,
      bundles: fetchBundles,
      menuMods: refreshMenuMods,
      extras: refreshExtras
    }
  })

  // Editing one costume or stage variant: edit modal, CSP manager and netplay
  // safety, kept in sync with each other (see useVaultItemEditing).
  const {
    showEditModal, setShowEditModal, editingItem, setEditingItem, editName, setEditName,
    renaming, editBusy, deleting, exporting, show3DViewer, setShow3DViewer,
    showConfirmDialog, confirmDialogData, handleEditClick, renameItem, replaceStock, replaceScreenshot,
    setStageSafety, replaceStageScreenshotWithCapture, handleGenerateStock, confirmGeneratedStock, discardGeneratedStock, pendingGeneratedStock,
    generatingStock, handleRetakeCsp, confirmGeneratedCsp, discardGeneratedCsp, pendingGeneratedCsp, appliedCsp,
    generatingCsp, handleDelete, handleExport, handleCancel, confirmDelete, cancelDelete,
    showCspManager, cspManagerSkin, portraits, cspBusy, lastImageUpdate, setLastImageUpdate,
    openCspManager, closeCspManager, handleSetActivePortrait, handleRemovePortrait, handleUploadMainCsp, handleUploadAltCsp,
    retestingItem, handleSlippiRetest, handleRetestFixChoice, handleSlippiOverride, safetyBusy, handleCostumeAssetsUpdated,
  } = useVaultItemEditing({ onRefresh, fetchStageVariants, setShowSlippiDialog, setSlippiDialogData })

  // Fetch stage variants and custom stages when in stages mode
  useEffect(() => {
    if (mode === 'stages') {
      fetchStageVariants()
      fetchCustomStages()
    }
  }, [mode, metadata])

  // Fetch custom characters when in characters mode
  useEffect(() => {
    if (mode === 'characters') {
      fetchCustomCharacters()
    }
  }, [mode, metadata])

  // Bundle handlers

  // Fetch xdelta patches and bundles when in patches mode
  useEffect(() => {
    if (mode === 'patches') {
      fetchXdeltaPatches()
      fetchBundles()
    }
  }, [mode])

  // Set loading to false when metadata is available
  useEffect(() => {
    if (metadata) {
      setIsLoading(false)
    }
  }, [metadata])

  // Merge default characters with metadata
  // Always show all 26 vanilla characters, even if they don't have custom skins
  const allCharacters = { ...metadata?.characters }

  // Add any missing default characters with 0 skins
  Object.keys(DEFAULT_CHARACTERS).forEach(charName => {
    if (!allCharacters[charName]) {
      allCharacters[charName] = { skins: [] }
    }
  })

  const characters = Object.keys(allCharacters).sort()

  // Skin Creator - Open fresh
  const openSkinCreator = () => {
    setSkinCreatorInitialCostume(null)
    setShowSkinCreator(true)
  }

  // Skin Creator - Edit existing costume from vault
  const startSkinCreatorFromVault = (costume) => {
    setShowEditModal(false) // Close edit modal if open
    setSkinCreatorInitialCostume(costume)
    setShowSkinCreator(true)
  }

  // Skin Creator - Close handler
  const closeSkinCreator = () => {
    setShowSkinCreator(false)
    setSkinCreatorInitialCostume(null)
    assistantEditor?.closeEditor()
  }




  // Switching vault mode from the toolbar. Each ModeToolbar call site adds
  // its own sub-page resets around this.
  const applyModeChange = (newMode) => {
    setMode(newMode)
    if (newMode === 'characters') {
      setSelectedStage(null)
    } else if (newMode === 'stages') {
      setSelectedCharacter(null)
    } else if (newMode === 'patches') {
      setSelectedCharacter(null)
      setSelectedStage(null)
    } else if (newMode === 'menus') {
      setSelectedCharacter(null)
      setSelectedStage(null)
    }
  }

  // The one import affordance — floating button (bottom-right) + drop-anywhere
  // overlay. Rendered in EVERY view of the vault; the sub-views below return
  // early, so each includes these elements. The slippi/duplicate dialogs ride
  // along for views that don't already render their own instance.
  // ISO-scan modal state is owned HERE, not by VaultImportSurface: that element
  // is mounted in a different slot per branch, so child-owned state would be
  // lost (modal closed, paths dropped) if the branch changed while it's open.
  const [showIsoScanModal, setShowIsoScanModal] = useState(false)
  const [scanInitialPaths, setScanInitialPaths] = useState([])
  const importFab = (
    <VaultImportSurface
      importing={importing}
      importMessage={importMessage}
      onFileImport={handleFileImport}
      onRefresh={onRefresh}
      onCustomCharactersChanged={fetchCustomCharacters}
      onCustomStagesChanged={fetchCustomStages}
      showIsoScanModal={showIsoScanModal}
      scanInitialPaths={scanInitialPaths}
      onScanOpen={(paths) => { setScanInitialPaths(paths); setShowIsoScanModal(true) }}
      onScanClose={() => { setShowIsoScanModal(false); setScanInitialPaths([]) }}
    />
  )
  const importSlippiDialog = (
    <SlippiSafetyDialog
      show={showSlippiDialog}
      data={slippiDialogData}
      onChoice={handleSlippiChoice}
      isRetest={false}
    />
  )
  // The duplicate dialog and the "What is this?" choice dialog ride together
  // so every branch that renders one renders both.
  const importDuplicateDialog = (
    <>
      <DuplicateImportDialog
        show={showDuplicateDialog}
        data={duplicateDialogData}
        onChoice={handleDuplicateChoice}
      />
      <ChoiceImportDialog
        show={showChoiceDialog}
        data={choiceDialogData}
        onChoice={handleChoice}
      />
    </>
  )

  // If a custom character is selected, show its detail view
  if (selectedCustomCharacter) {
    return (
      <>
        <CustomCharacterDetailView
          character={selectedCustomCharacter}
          onBack={() => setSelectedCustomCharacter(null)}
          onDelete={() => { setSelectedCustomCharacter(null); fetchCustomCharacters(); }}
          onRename={(updated) => {
            setSelectedCustomCharacter(updated)
            fetchCustomCharacters()
          }}
          onSkinCreatorChange={onSkinCreatorChange}
        />
        {importFab}
        {importSlippiDialog}
        {importDuplicateDialog}
      </>
    )
  }

  // If custom characters sub-page is open, show the grid
  if (showCustomCharacters) {
    return (
      <div className="storage-viewer">
        <ModeToolbar
          mode={mode}
          onModeChange={(newMode) => {
            applyModeChange(newMode)
            setShowCustomCharacters(false)
            setSelectedCustomCharacter(null)
          }}
        />
        <CustomCharactersGrid
          customCharacters={customCharacters}
          pendingBuiltins={pendingBuiltins}
          isLoading={isLoading}
          onSelectCharacter={setSelectedCustomCharacter}
          onBack={() => setShowCustomCharacters(false)}
          onRefresh={fetchCustomCharacters}
        />
        {importFab}
        {importSlippiDialog}
        {importDuplicateDialog}
      </div>
    )
  }

  // If a custom stage is selected, show its detail view
  if (selectedCustomStage) {
    return (
      <>
        <CustomStageDetailView
          stage={selectedCustomStage}
          onBack={() => setSelectedCustomStage(null)}
          onDelete={() => { setSelectedCustomStage(null); fetchCustomStages(); }}
          onRename={(updatedStage) => {
            setSelectedCustomStage(updatedStage)
            fetchCustomStages()
          }}
        />
        {importFab}
        {importSlippiDialog}
        {importDuplicateDialog}
      </>
    )
  }

  // If the More Stages sub-page is open (the non-DAS versus stages), show its
  // grid. Picking a stage sets selectedStage, which renders the ordinary
  // StageDetailView (same variants page as the six DAS stages) further down.
  if (showMoreStages && !selectedStage) {
    return (
      <div className="storage-viewer">
        <ModeToolbar
          mode={mode}
          onModeChange={(newMode) => {
            applyModeChange(newMode)
            setShowMoreStages(false)
            setSelectedCustomStage(null)
          }}
        />
        <MoreStagesGrid
          stageVariants={stageVariants}
          isLoading={isLoading}
          onSelectStage={setSelectedStage}
          onBack={() => setShowMoreStages(false)}
        />
        {importFab}
        {importSlippiDialog}
        {importDuplicateDialog}
      </div>
    )
  }

  // If custom stages sub-page is open, show the grid
  if (showCustomStages) {
    return (
      <div className="storage-viewer">
        <ModeToolbar
          mode={mode}
          onModeChange={(newMode) => {
            applyModeChange(newMode)
            setShowCustomStages(false)
            setSelectedCustomStage(null)
          }}
        />
        <CustomStagesGrid
          customStages={customStages}
          isLoading={isLoading}
          onSelectStage={setSelectedCustomStage}
          onBack={() => setShowCustomStages(false)}
          onRefresh={fetchCustomStages}
        />
        {importFab}
        {importSlippiDialog}
        {importDuplicateDialog}
      </div>
    )
  }

  // If a stage is selected, show its variants
  if (selectedStage) {
    return (
      <>
      <StageDetailView
        editorRequest={stageEditorRequest}
        onEditorRequestHandled={() => setStageEditorRequest(null)}
        onSkinCreatorChange={onSkinCreatorChange}
        selectedStage={selectedStage}
        stageVariants={stageVariants}
        onBack={() => setSelectedStage(null)}
        onRefresh={onRefresh}
        onRefreshVariants={fetchStageVariants}
        // Folder expansion state (persists here across stage navigation)
        expandedFolders={expandedFolders}
        setExpandedFolders={setExpandedFolders}
        // Display-only sort (Custom = stored order)
        sort={vaultSort.stages}
        onSortChange={(next) => changeVaultSort('stages', next)}
        // Drag and drop
        draggedItem={draggedItem}
        dragOverIndex={dragOverIndex}
        previewOrder={previewOrder}
        reordering={reordering}
        isDraggingActive={isDraggingActive}
        justDroppedId={justDroppedId}
        justDraggedRef={justDraggedRef}
        dragTargetFolder={dragTargetFolder}
        handleDragStart={handleDragStart}
        handleDragOver={handleDragOver}
        handleDragEnter={handleDragEnter}
        handleDragLeave={handleDragLeave}
        handleVariantDrop={handleVariantDrop}
        handleDragEnd={handleDragEnd}
        // Context menu
        handleVariantContextMenu={handleVariantContextMenu}
        contextMenu={contextMenu}
        handleMoveToTop={handleMoveToTop}
        handleMoveToBottom={handleMoveToBottom}
        // Edit modal
        showEditModal={showEditModal}
        editingItem={editingItem}
        editName={editName}
        setEditName={setEditName}
        renameItem={renameItem}
        renaming={renaming}
        editBusy={editBusy}
        deleting={deleting}
        exporting={exporting}
        lastImageUpdate={lastImageUpdate}
        handleCancel={handleCancel}
        handleDelete={handleDelete}
        handleExport={handleExport}
        replaceScreenshot={replaceScreenshot}
        setStageSafety={setStageSafety}
        handleSlippiRetest={handleSlippiRetest}
        handleSlippiOverride={handleSlippiOverride}
        openCspManager={openCspManager}
        startSkinCreatorFromVault={startSkinCreatorFromVault}
        show3DViewer={show3DViewer}
        setShow3DViewer={setShow3DViewer}
        handleEditClick={handleEditClick}
        replaceStageScreenshotWithCapture={replaceStageScreenshotWithCapture}
        // CSP Manager
        showCspManager={showCspManager}
        cspManagerSkin={cspManagerSkin}
        portraits={portraits}
        cspBusy={cspBusy}
        closeCspManager={closeCspManager}
        handleSetActivePortrait={handleSetActivePortrait}
        handleRemovePortrait={handleRemovePortrait}
        handleUploadMainCsp={handleUploadMainCsp}
        handleUploadAltCsp={handleUploadAltCsp}
        // Slippi dialog
        showSlippiDialog={showSlippiDialog}
        slippiDialogData={slippiDialogData}
        retestingItem={retestingItem}
        handleRetestFixChoice={handleRetestFixChoice}
        handleSlippiChoice={handleSlippiChoice}
        // Confirm dialog
        showConfirmDialog={showConfirmDialog}
        confirmDialogData={confirmDialogData}
        confirmDelete={confirmDelete}
        cancelDelete={cancelDelete}
        // API
      />
      {importFab}
      {importDuplicateDialog}
      </>
    )
  }

  // If a character is selected, show their skins
  if (selectedCharacter) {
    return (
      <>
      <CharacterDetailView
        selectedCharacter={selectedCharacter}
        focusSkinRequest={!vaultNavigation?.editor && vaultNavigation?.character === selectedCharacter ? vaultNavigation : null}
        onSkinFocused={onVaultNavigationComplete}
        allCharacters={allCharacters}
        onBack={() => setSelectedCharacter(null)}
        // Folder expansion state (persists here across character navigation)
        expandedFolders={expandedFolders}
        setExpandedFolders={setExpandedFolders}
        // Display-only sort (Custom = stored order)
        sort={vaultSort.skins}
        onSortChange={(next) => changeVaultSort('skins', next)}
        // Shared state clusters (same hook instances also feed StageDetailView
        // and the grid-level modals below)
        dragDrop={{
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
        }}
        editModal={{
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
          generatingCsp,
          handleDelete,
          handleExport,
          handleCancel,
          confirmDelete,
          cancelDelete
        }}
        safetyBusy={safetyBusy}
        cspManager={{
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
        }}
        slippiDialog={{
          showSlippiDialog,
          slippiDialogData,
          retestingItem,
          handleRetestFixChoice,
          handleSlippiChoice,
          handleSlippiRetest,
          handleSlippiOverride
        }}
        contextMenuApi={{
          contextMenu,
          handleSkinContextMenu,
          handleMoveToTop,
          handleMoveToBottom
        }}
        skinCreator={{
          showSkinCreator,
          openSkinCreator,
          closeSkinCreator,
          startSkinCreatorFromVault,
          skinCreatorInitialCostume
        }}
        // Identity / data / callbacks
        onSkinCreatorChange={onSkinCreatorChange}
        onRefresh={onRefresh}
        onCostumesUpdated={handleCostumeAssetsUpdated}
        extrasRefreshKey={extrasRefreshKey}
      />
      {importFab}
      {importDuplicateDialog}
      </>
    )
  }

  // Character or Stage selection grid. Mode homes center their grid
  // vertically in the leftover space so they line up; the Menus page is a
  // sidebar + list and keeps the normal top-anchored flow.
  const atModeHome = mode !== 'menus'
  return (
    <div className={`storage-viewer${atModeHome ? ' storage-viewer--home' : ''}`}>
      <ModeToolbar
        mode={mode}
        onModeChange={(newMode) => {
          applyModeChange(newMode)
          setShowCustomStages(false)
          setSelectedCustomStage(null)
          setShowCustomCharacters(false)
          setSelectedCustomCharacter(null)
        }}
      />

      {importFab}

      {mode === 'characters' ? (
        <>
          <div className="bulk-capture-row">
            <button
              className="mode-btn"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); setShowBulkRetake(true) }}
              title="Re-render CSP portraits for many costumes at once (each with its active pose, SD + HD)"
            >
              📸 Bulk Retake CSPs
            </button>
          </div>
          <CharactersGrid
            characters={characters}
            allCharacters={allCharacters}
            isLoading={isLoading}
            onSelectCharacter={setSelectedCharacter}
            customCharacterCount={customCharacters.length}
            onOpenCustomCharacters={() => setShowCustomCharacters(true)}
            iconRetryKey={metadata}
          />
        </>
      ) : mode === 'stages' ? (
        <>
          <div className="bulk-capture-row">
            <button
              className="mode-btn"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); setShowBulkCapture(true) }}
              title="Render preview screenshots for many stage variants at once (offline — no ISO or Dolphin)"
            >
              📸 Bulk Render Screenshots
            </button>
          </div>
          <StagesGrid
            stageVariants={stageVariants}
            isLoading={isLoading}
            onSelectStage={setSelectedStage}
            customStageCount={customStages.length}
            onOpenCustomStages={() => setShowCustomStages(true)}
            onOpenMoreStages={() => setShowMoreStages(true)}
          />
        </>
      ) : mode === 'patches' ? (
        <PatchesGrid
          xdeltaPatches={xdeltaPatches}
          bundles={bundles}
          onEditPatch={handleEditXdelta}
          onBuildIso={handleBuildXdeltaIso}
          onShowCreateModal={() => setShowXdeltaCreateModal(true)}
          onEditBundle={handleEditBundle}
          onInstallBundle={handleInstallBundle}
          onPlayBundle={handlePlayBundle}
          onPlayPatch={handlePlayPatch}
          playingId={playingId}
          playPercent={playPercent}
        />
      ) : (
        <VaultMenusView
          selectedKind={selectedMenuKind}
          onSelectKind={setSelectedMenuKind}
          refreshKey={menuRefreshKey}
          detailOpen={menuDetailOpen}
          onDetailChange={setMenuDetailOpen}
        />
      )}

      <PatchModals patches={patches} />

      <EditModal
        show={showEditModal}
        editingItem={editingItem}
        covered={Boolean(show3DViewer || showCspManager || showSkinCreator || showConfirmDialog || showSlippiDialog
          || showDuplicateDialog)}
        editName={editName}
        onNameChange={setEditName}
        onRename={renameItem}
        renaming={renaming}
        busy={editBusy}
        deleting={deleting}
        exporting={exporting}
        lastImageUpdate={lastImageUpdate}
        onClose={handleCancel}
        onDelete={handleDelete}
        onExport={handleExport}
        onReplaceStock={replaceStock}
        onGenerateStock={handleGenerateStock}
        onConfirmGeneratedStock={confirmGeneratedStock}
        onDiscardGeneratedStock={discardGeneratedStock}
        pendingGeneratedStock={pendingGeneratedStock}
        generatingStock={generatingStock}
        onRetakeCsp={handleRetakeCsp}
        onConfirmGeneratedCsp={confirmGeneratedCsp}
        onDiscardGeneratedCsp={discardGeneratedCsp}
        pendingGeneratedCsp={pendingGeneratedCsp}
        appliedCsp={appliedCsp}
        generatingCsp={generatingCsp}
        onReplaceScreenshot={replaceScreenshot}
        onSetStageSafety={setStageSafety}
        onSlippiRetest={handleSlippiRetest}
        onSlippiOverride={handleSlippiOverride}
        safetyBusy={safetyBusy}
        onOpenCspManager={openCspManager}
        onStartSkinCreator={startSkinCreatorFromVault}
        onView3D={() => setShow3DViewer(true)}
      />
      {show3DViewer && editingItem && editingItem.type === 'costume' && (
        <EmbeddedModelViewer
      character={editingItem.data.character}
      skinId={editingItem.data.id}
      title={editingItem.data.color || editingItem.data.name}
      onClose={() => setShow3DViewer(false)}
        />
      )}
      <SlippiSafetyDialog
        show={showSlippiDialog}
        data={slippiDialogData}
        onChoice={retestingItem !== null ? handleRetestFixChoice : handleSlippiChoice}
        isRetest={retestingItem !== null}
      />

      <DuplicateImportDialog
        show={showDuplicateDialog}
        data={duplicateDialogData}
        onChoice={handleDuplicateChoice}
      />

      <ConfirmDialog
        show={showConfirmDialog}
        title={confirmDialogData?.title}
        message={confirmDialogData?.message}
        confirmText={confirmDialogData?.confirmText}
        onConfirm={confirmDelete}
        onCancel={cancelDelete}
      />

      {/* XDelta Build Modal */}
      <XdeltaBuildModal
        show={showXdeltaBuildModal}
        xdeltaBuildState={xdeltaBuildState}
        xdeltaBuildPatch={xdeltaBuildPatch}
        xdeltaBuildProgress={xdeltaBuildProgress}
        xdeltaBuildMessage={xdeltaBuildMessage}
        xdeltaBuildFilename={xdeltaBuildFilename}
        xdeltaBuildError={xdeltaBuildError}
        onClose={closeXdeltaBuildModal}
        onDownload={handleDownloadXdeltaIso}
      />

      {playingId && (
        <PlayOverlay
          playPercent={playPercent}
          playMessage={playMessage}
          playError={playError}
          playLaunched={playLaunched}
          dismissPlay={dismissPlay}
        />
      )}

      <BulkStageCaptureModal
        show={showBulkCapture}
        onClose={() => setShowBulkCapture(false)}
        onSaved={() => { fetchStageVariants(); setLastImageUpdate(Date.now()) }}
      />
      <BulkCharacterCspModal
        show={showBulkRetake}
        characters={allCharacters}
        onApplied={(applied) => {
          if (applied) { setLastImageUpdate(Date.now()); onRefresh && onRefresh() }
        }}
        onClose={() => setShowBulkRetake(false)}
      />
    </div>
  )
}

