import { useCallback, useRef } from 'react'
import { useCspManager } from './useCspManager'
import { useEditModal } from './useEditModal'
import { useSlippiSafety } from './useSlippiSafety'

// Editing one costume or stage variant from the Vault: the edit modal, the CSP
// manager (which keeps the item open in the modal in sync), netplay-safety
// retests and overrides, and re-syncing both after a costume's assets change.
export function useVaultItemEditing({ onRefresh, fetchStageVariants, setShowSlippiDialog, setSlippiDialogData }) {
  // Ref for setEditingItem - used by CSP manager callback (initialized after useEditModal)
  const setEditingItemRef = useRef(null)

  // CSP manager hook
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
    refreshManagedSkinState,
    handleUploadMainCsp,
    handleUploadAltCsp
  } = useCspManager({
    onRefresh,
    onUpdateEditingItemAlts: (updater) => {
      if (setEditingItemRef.current) {
        setEditingItemRef.current(prev => prev ? {
          ...prev,
          data: {
            ...prev.data,
            alternateCsps: typeof updater === 'function'
              ? updater(prev.data.alternateCsps || [])
              : updater
          }
        } : prev)
      }
    },
    onUpdateEditingItemActiveCsp: (activeCspId) => {
      if (setEditingItemRef.current) {
        setEditingItemRef.current(prev => prev ? {
          ...prev,
          data: {
            ...prev.data,
            active_csp_id: activeCspId
          }
        } : prev)
      }
    },
    onUpdateEditingItemData: (updatedData) => {
      if (setEditingItemRef.current) {
        setEditingItemRef.current(prev => (
          prev?.type === 'costume' &&
          prev.data.id === updatedData.id &&
          prev.data.character === updatedData.character
            ? {
                ...prev,
                data: {
                  ...prev.data,
                  ...updatedData
                }
              }
            : prev
        ))
      }
    }
  })

  // Edit modal hook
  const {
    showEditModal,
    setShowEditModal,
    editingItem,
    setEditingItem,
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
    replaceScreenshot,
    setStageSafety,
    replaceStageScreenshotWithCapture,
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
  } = useEditModal({
    onRefresh,
    fetchStageVariants,
    setLastImageUpdate,
    refreshCostumeData: refreshManagedSkinState
  })

  // Store setEditingItem in ref for CSP manager callback
  setEditingItemRef.current = setEditingItem

  const handleCostumeAssetsUpdated = useCallback(async ({ character, skinIds }) => {
    const targetIds = [...new Set((skinIds || []).filter(Boolean))]
    if (!character || targetIds.length === 0) return

    setLastImageUpdate(Date.now())

    if (onRefresh) {
      await onRefresh()
    }

    const shouldSyncEditingItem = editingItem?.type === 'costume' &&
      editingItem.data.character === character &&
      targetIds.includes(editingItem.data.id)

    const shouldSyncCspManager = cspManagerSkin?.character === character &&
      targetIds.includes(cspManagerSkin.id)

    if (!shouldSyncEditingItem && !shouldSyncCspManager) {
      return
    }

    const syncTargets = [
      shouldSyncEditingItem ? editingItem.data.id : null,
      shouldSyncCspManager ? cspManagerSkin.id : null
    ].filter((value, index, array) => value && array.indexOf(value) === index)

    for (const skinId of syncTargets) {
      await refreshManagedSkinState(character, skinId, { refreshParent: false })
    }
  }, [cspManagerSkin, editingItem, onRefresh, refreshManagedSkinState, setLastImageUpdate])

  // Netplay-safety actions for the costume open in the edit modal.
  const {
    retestingItem,
    setRetestingItem,
    handleSlippiRetest,
    handleRetestFixChoice,
    handleSlippiOverride,
    safetyBusy,
  } = useSlippiSafety({ editingItem, setEditingItem, onRefresh, setShowSlippiDialog, setSlippiDialogData })

  return {
    showEditModal, setShowEditModal, editingItem, setEditingItem, editName, setEditName,
    renaming, editBusy, deleting, exporting, show3DViewer, setShow3DViewer,
    showConfirmDialog, confirmDialogData, handleEditClick, renameItem, replaceStock, replaceScreenshot,
    setStageSafety, replaceStageScreenshotWithCapture, handleGenerateStock, confirmGeneratedStock, discardGeneratedStock, pendingGeneratedStock,
    generatingStock, handleRetakeCsp, confirmGeneratedCsp, discardGeneratedCsp, pendingGeneratedCsp, appliedCsp,
    generatingCsp, handleDelete, handleExport, handleCancel, confirmDelete, cancelDelete,
    showCspManager, cspManagerSkin, portraits, cspBusy, lastImageUpdate, setLastImageUpdate,
    openCspManager, closeCspManager, handleSetActivePortrait, handleRemovePortrait, handleUploadMainCsp, handleUploadAltCsp,
    retestingItem, handleSlippiRetest, handleRetestFixChoice, handleSlippiOverride, safetyBusy, handleCostumeAssetsUpdated,
  }
}
