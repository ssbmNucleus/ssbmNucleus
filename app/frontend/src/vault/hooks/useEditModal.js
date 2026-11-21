/**
 * useEditModal Hook
 *
 * State + actions for the costume / stage-variant edit modal. Every action
 * writes immediately and refreshes the vault -- there is no pending "Save":
 *   - renameItem(name)           rename (commits from the title field)
 *   - replaceStock(file)         costume stock icon
 *   - replaceScreenshot(file)    stage variant preview
 *   - setStageSafety(value)      stage Slippi status (true / false / null)
 *   - generate stock / retake CSP are render-then-confirm (preview held in
 *     pendingGeneratedStock / pendingGeneratedCsp until the user decides; an
 *     approved portrait then stays on screen as appliedCsp)
 *   - delete (confirm dialog) / export
 */

import { useRef, useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'
import { backendMediaUrl } from '../../shared/config/config.js'

export function useEditModal({ onRefresh, fetchStageVariants, setLastImageUpdate, refreshCostumeData }) {
  const editSession = useRef(0)
  const deletingSession = useRef(null)
  const session = editSession.current
  const isCurrent = () => editSession.current === session
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingItem, setEditingItem] = useState(null) // { type: 'costume'|'stage', data: {...} }
  const [editName, setEditName] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [busy, setBusy] = useState(false)           // an upload / safety write in flight
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [generatingStock, setGeneratingStock] = useState(false)
  const [pendingGeneratedStock, setPendingGeneratedStock] = useState(null) // { dataUri, method }
  const [generatingCsp, setGeneratingCsp] = useState(false)
  const [pendingGeneratedCsp, setPendingGeneratedCsp] = useState(null) // { dataUri, poseName, pose? (a picked pose; null = default) }
  // The portrait the user just approved, kept on screen after the write so the
  // hero image never drops back to the pre-retake render. `stamp` is the
  // cache-buster stamped with it; any later image write bumps that and retires
  // this preview in favour of the file on disk.
  const [appliedCsp, setAppliedCsp] = useState(null) // { dataUri, stamp }

  // Confirm dialog state
  const [showConfirmDialog, setShowConfirmDialog] = useState(false)
  const [confirmDialogData, setConfirmDialogData] = useState(null)

  // 3D viewer state
  const [show3DViewer, setShow3DViewer] = useState(false)

  const currentName = (item) => (item?.type === 'costume' ? item.data.color : item?.data?.name) || ''

  const patchItem = (patch) =>
    setEditingItem(prev => isCurrent() && prev ? { ...prev, data: { ...prev.data, ...patch } } : prev)

  // Refetch what the grids read (stage list + metadata) after a write.
  const refreshAfter = async (type) => {
    if (type === 'stage' && fetchStageVariants) await fetchStageVariants()
    if (onRefresh) await onRefresh()
  }

  const close = () => {
    editSession.current++
    setShowEditModal(false)
    setDeleting(false)
    setShow3DViewer(false)
    setShowConfirmDialog(false)
    setConfirmDialogData(null)
    setEditingItem(null)
    setEditName('')
    setPendingGeneratedStock(null)
    setPendingGeneratedCsp(null)
    setAppliedCsp(null)
  }

  // Open edit modal
  const handleEditClick = (type, data) => {
    editSession.current++
    const item = { type, data }
    setEditingItem(item)
    setEditName(currentName(item))
    setRenaming(false)
    setBusy(false)
    setDeleting(false)
    setGeneratingStock(false)
    setGeneratingCsp(false)
    setShow3DViewer(false)
    setShowConfirmDialog(false)
    setConfirmDialogData(null)
    setPendingGeneratedStock(null)
    setPendingGeneratedCsp(null)
    setAppliedCsp(null)
    setShowEditModal(true)
  }

  // Rename -- committed from the title field (Enter / blur). Returns true when
  // the name is now what the field shows (unchanged counts).
  const renameItem = async (name) => {
    if (!editingItem) return false
    const trimmed = (name ?? editName).trim()
    if (!trimmed) {
      playSound('error')
      setEditName(currentName(editingItem))
      return false
    }
    if (trimmed === currentName(editingItem)) {
      setEditName(trimmed)
      return true
    }
    setRenaming(true)
    try {
      if (editingItem.type === 'costume') {
        await api.post('/storage/costumes/rename', {
          character: editingItem.data.character,
          skinId: editingItem.data.id,
          newName: trimmed
        })
        patchItem({ color: trimmed })
      } else {
        await api.post('/storage/stages/rename', {
          stageFolder: editingItem.data.stageFolder,
          variantId: editingItem.data.id,
          newName: trimmed
        })
        patchItem({ name: trimmed })
      }
      setEditName(trimmed)
      await refreshAfter(editingItem.type)
      playSound('boop')
      return true
    } catch (err) {
      playSound('error')
      alert(`Rename failed: ${err.message}`)
      setEditName(currentName(editingItem))
      return false
    } finally {
      setRenaming(false)
    }
  }

  // Upload a replacement image and refresh; shared by stock + screenshot.
  const uploadImage = async (label, endpoint, fields, file, patch) => {
    if (!editingItem || !file) return
    if (!file.type.startsWith('image/')) { alert('Please select an image file'); return }
    setBusy(true)
    try {
      const formData = new FormData()
      for (const [k, v] of Object.entries(fields)) formData.append(k, v)
      formData.append(label, file)
      await api.post(endpoint, formData)
      patchItem(patch)
      await refreshAfter(editingItem.type)
      setLastImageUpdate(Date.now())
      playSound('camera')
    } catch (err) {
      playSound('error')
      alert(`${label === 'stock' ? 'Stock icon' : 'Screenshot'} upload failed: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  const replaceStock = (file) => uploadImage(
    'stock', '/storage/costumes/update-stock',
    { character: editingItem?.data?.character, skinId: editingItem?.data?.id },
    file, { has_stock: true, stock_source: 'uploaded' })

  const replaceScreenshot = (file) => uploadImage(
    'screenshot', '/storage/stages/update-screenshot',
    { stageFolder: editingItem?.data?.stageFolder, variantId: editingItem?.data?.id },
    file, { hasScreenshot: true })

  // Stage Slippi status: true (safe) / false (unsafe) / null (unknown).
  const setStageSafety = async (value) => {
    if (!editingItem || editingItem.type !== 'stage') return
    if (value === editingItem.data.slippi_safe) return
    setBusy(true)
    try {
      await api.post('/storage/stages/set-slippi', {
        stageName: editingItem.data.stageFolder,
        variantId: editingItem.data.id,
        slippiSafe: value
      })
      patchItem({ slippi_safe: value })
      await refreshAfter('stage')
      playSound('boop')
    } catch (err) {
      playSound('error')
      alert(`Slippi status update failed: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  // Replace a stage variant's screenshot with a freshly CAPTURED image (the
  // capture job's /shots URL). Saves immediately via the same endpoint + refresh
  // the manual upload uses, then closes the modal.
  const replaceStageScreenshotWithCapture = async (shot) => {
    if (!editingItem || editingItem.type !== 'stage' || !shot) return
    setBusy(true)
    try {
      const response = await fetch(backendMediaUrl(shot))
      if (!response.ok) throw new Error(`the captured image is gone (${response.status})`)
      const blob = await response.blob()
      const formData = new FormData()
      formData.append('stageFolder', editingItem.data.stageFolder)
      formData.append('variantId', editingItem.data.id)
      formData.append('screenshot', blob, `${editingItem.data.id}_screenshot.png`)

      await api.post('/storage/stages/update-screenshot', formData)

      await refreshAfter('stage')
      setLastImageUpdate(Date.now())
      playSound('camera')
      close()
    } catch (err) {
      playSound('error')
      alert(`Screenshot save error: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  // Derive a stock icon from the costume's DAT colors (vs vanilla) on the
  // backend. Nothing is written yet: the preview is held in
  // pendingGeneratedStock until the user confirms or discards it.
  // `style` is 'recolor' (palette-swap the vanilla pixel icon) or 'render'
  // (crop a head out of a render); omitted lets the backend pick.
  const handleGenerateStock = async (style) => {
    if (!editingItem || editingItem.type !== 'costume') return
    setGeneratingStock(style || true)
    try {
      const data = await api.post('/storage/costumes/generate-stock', {
        character: editingItem.data.character,
        skinId: editingItem.data.id,
        ...(style ? { style } : {})
      })
      if (!isCurrent()) return
      setPendingGeneratedStock({ dataUri: data.dataUri, method: data.method })
      playSound('boop')
    } catch (err) {
      if (!isCurrent()) return
      playSound('error')
      alert(`Stock generation error: ${err.message}`)
    } finally {
      if (isCurrent()) setGeneratingStock(false)
    }
  }

  // Write the previewed icon for real
  const confirmGeneratedStock = async () => {
    if (!editingItem || !pendingGeneratedStock) return
    setGeneratingStock(true)
    try {
      const data = await api.post('/storage/costumes/generate-stock', {
        character: editingItem.data.character,
        skinId: editingItem.data.id,
        apply: true,
        imageData: pendingGeneratedStock.dataUri
      })
      setPendingGeneratedStock(null)
      patchItem({ has_stock: true, stockUrl: data.stockUrl, stock_source: 'generated' })
      await onRefresh()
      setLastImageUpdate(Date.now())
      playSound('camera')
    } catch (err) {
      playSound('error')
      alert(`Stock save error: ${err.message}`)
    } finally {
      setGeneratingStock(false)
    }
  }

  const discardGeneratedStock = () => {
    setPendingGeneratedStock(null)
    playSound('back')
  }

  // Re-render ("retake") the costume's character-select portrait with the
  // headless renderer, using whichever pose is currently active (the default
  // pose unless a custom-pose alternate is active). Nothing is written yet --
  // the fresh render is held in pendingGeneratedCsp until confirm/discard.
  // `pose` picks another pose instead: a name from the character's pose
  // library, or null for the default pose. Keeping that render makes it the
  // portrait the costume shows.
  const handleRetakeCsp = async (pose) => {
    if (!editingItem || editingItem.type !== 'costume') return
    const picked = pose === null || typeof pose === 'string' // a click event is not a pose
    setGeneratingCsp(true)
    try {
      const data = await api.post('/storage/costumes/generate-csp', {
        character: editingItem.data.character,
        skinId: editingItem.data.id,
        ...(picked ? { poseName: pose } : {})
      })
      if (!isCurrent()) return
      setPendingGeneratedCsp({ dataUri: data.dataUri, poseName: data.poseName, ...(picked ? { pose } : {}) })
      playSound('boop')
    } catch (err) {
      if (!isCurrent()) return
      playSound('error')
      alert(`Portrait render error: ${err.message}`)
    } finally {
      if (isCurrent()) setGeneratingCsp(false)
    }
  }

  // Write the previewed portrait for real (replaces the active portrait -- the
  // original CSP, or the active pose alternate -- on the backend).
  const confirmGeneratedCsp = async () => {
    if (!editingItem || !pendingGeneratedCsp) return
    const { character, id } = editingItem.data
    const approved = pendingGeneratedCsp.dataUri
    setGeneratingCsp(true)
    try {
      await api.post('/storage/costumes/generate-csp', {
        character,
        skinId: id,
        apply: true,
        imageData: approved,
        // a picked pose is filed as that pose's portrait and shown from now on
        ...('pose' in pendingGeneratedCsp ? { poseName: pendingGeneratedCsp.pose } : {})
      })
      // Swap the reveal for the approved render itself (one batched update, so
      // the wipe lands on the new portrait instead of blinking through the old
      // file) and keep it up while the vault re-reads underneath.
      const stamp = Date.now()
      setPendingGeneratedCsp(null)
      setAppliedCsp({ dataUri: approved, stamp })
      setLastImageUpdate(stamp)
      patchItem({ has_csp: true })
      await onRefresh()
      // Re-read the skin: the hero <img> picks its file from has_hd_csp /
      // hdCspUrl / alternateCsps, and a retake can mint an HD member this
      // modal's snapshot has never seen.
      if (refreshCostumeData) {
        try {
          await refreshCostumeData(character, id, { refreshParent: false })
        } catch (err) {
          console.warn('Portrait saved, but re-reading the skin failed:', err)
        }
      }
      playSound('camera')
    } catch (err) {
      playSound('error')
      alert(`Portrait save error: ${err.message}`)
    } finally {
      setGeneratingCsp(false)
    }
  }

  const discardGeneratedCsp = () => {
    setPendingGeneratedCsp(null)
    playSound('back')
  }

  // Delete item - shows confirmation dialog
  const handleDelete = () => {
    if (!editingItem || !isCurrent() || deletingSession.current === session) return
    const itemName = editingItem.type === 'costume'
      ? `${editingItem.data.character} - ${editingItem.data.color}`
      : editingItem.data.name

    setConfirmDialogData({
      title: 'Delete Item',
      message: `Are you sure you want to delete "${itemName}"? This cannot be undone.`,
      confirmText: 'Delete',
      itemToDelete: editingItem
    })
    setShowConfirmDialog(true)
  }

  // Actually perform the delete after confirmation
  const confirmDelete = async () => {
    const itemToDelete = confirmDialogData?.itemToDelete
    if (!itemToDelete || !isCurrent() || deletingSession.current === session) return
    deletingSession.current = session
    setShowConfirmDialog(false)
    setConfirmDialogData(null)
    setDeleting(true)
    let deleted = false

    try {
      const endpoint = itemToDelete.type === 'costume'
        ? '/storage/costumes/delete'
        : '/storage/stages/delete'

      const body = itemToDelete.type === 'costume'
        ? {
            character: itemToDelete.data.character,
            skinId: itemToDelete.data.id
          }
        : {
            stageFolder: itemToDelete.data.stageFolder,
            variantId: itemToDelete.data.id
          }

      await api.post(endpoint, body)
      deleted = true
      // Retire the deleted selection immediately, even if refresh is slow or
      // fails. A newer modal (including a same-ID reimport) owns a new session.
      if (isCurrent()) close()
      await refreshAfter(itemToDelete.type)

      // Update cache-busting timestamp to force image reload after deletion
      if (itemToDelete.type === 'costume') {
        setLastImageUpdate(Date.now())
      }

    } catch (err) {
      if (!isCurrent() && !deleted) return
      if (err.status === 404 && isCurrent()) {
        close()
        await refreshAfter(itemToDelete.type).catch(() => {})
      }
      playSound('error')
      alert(deleted ? `Item deleted, but refreshing the vault failed: ${err.message}` : `Delete error: ${err.message}`)
    } finally {
      if (deletingSession.current === session) deletingSession.current = null
      if (isCurrent()) setDeleting(false)
    }
  }

  // Cancel delete confirmation
  const cancelDelete = () => {
    setShowConfirmDialog(false)
    setConfirmDialogData(null)
  }

  // Export item
  const handleExport = async () => {
    setExporting(true)

    try {
      const endpoint = editingItem.type === 'costume'
        ? '/storage/costumes/export'
        : '/storage/stages/export'

      const body = editingItem.type === 'costume'
        ? {
            character: editingItem.data.character,
            skinId: editingItem.data.id,
            colorName: editingItem.data.color
          }
        : {
            stageCode: editingItem.data.stageCode,
            stageName: editingItem.data.stageName,
            variantId: editingItem.data.id,
            variantName: editingItem.data.name
          }

      const data = await api.post(endpoint, body)

      // Trigger download
      const downloadUrl = backendMediaUrl(api.url(`/export/mod/${data.filename}`))
      const link = document.createElement('a')
      link.href = downloadUrl
      link.download = data.filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    } catch (err) {
      playSound('error')
      alert(`Export error: ${err.message}`)
    } finally {
      setExporting(false)
    }
  }

  // Close the modal (nothing is pending, so this is just close)
  const handleCancel = () => {
    playSound('back')
    close()
  }

  return {
    // State
    showEditModal,
    setShowEditModal,
    editingItem,
    setEditingItem,
    editName,
    setEditName,
    renaming,
    busy,
    saving: busy || renaming,   // back-compat alias: any write in flight
    deleting,
    exporting,
    generatingStock,
    pendingGeneratedStock,
    generatingCsp,
    pendingGeneratedCsp,
    appliedCsp,
    show3DViewer,
    setShow3DViewer,

    // Confirm dialog state
    showConfirmDialog,
    confirmDialogData,

    // Handlers
    handleEditClick,
    renameItem,
    replaceStock,
    replaceScreenshot,
    setStageSafety,
    replaceStageScreenshotWithCapture,
    handleGenerateStock,
    confirmGeneratedStock,
    discardGeneratedStock,
    handleRetakeCsp,
    confirmGeneratedCsp,
    discardGeneratedCsp,
    handleDelete,
    handleExport,
    handleCancel,

    // Confirm dialog handlers
    confirmDelete,
    cancelDelete
  }
}
