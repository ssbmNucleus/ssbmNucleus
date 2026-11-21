import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'
import { requestExportDat, base64ToBlob } from './datUtils'
import { addPaintPairToZip } from './paintPair'
import { capturePaintPairExport, requireCompletePairSave } from './paintProtocol'

// Saving the edit: export the viewer's DAT, then save it to the vault (a
// custom character's skins go back to that character, a stage to its stage)
// or download it. Built each render from that render's state and refs.
export function createSaveActions({
  paintPairRef, connectionFailed, editorSessionRef, exportDatResolverRef, paintSessionRef,
  setConnectionFailed, selectedCharacter, setSkinName, setSaveError, setShowSaveModal,
  cancelHighlight, materialColors, skinName, hasElectron, savingRef,
  selectionRevisionRef, setIsSaving, palette, isStage, streamCanvasRef,
  stageWorkspaceRef, setIsDirty, onRefresh, initialCostume, sourceDatNameRef,
  selectedVanillaCostume, selectedPoseName, viewerWs,
}) {
  const exportPaintDat = async () => {
    if (paintPairRef.current && connectionFailed) {
      throw new Error('Reconnect the viewer before saving both climbers.')
    }
    const session = editorSessionRef.current
    try {
      return await requestExportDat(exportDatResolverRef, 30000, paintPairRef.current ?
        { type: 'exportPaintPair', sessionId: paintSessionRef.current } : {})
    } catch (error) {
      // Retain the edits and require a healthy pair before another save.
      if (session === editorSessionRef.current && paintPairRef.current) setConnectionFailed(true)
      throw error
    }
  }

  // Open save modal
  const openSaveModal = () => {
    const defaultName = `${selectedCharacter} Custom`
    setSkinName(defaultName)
    setSaveError(null)
    setShowSaveModal(true)
  }

  // Save to vault
  const handleSaveToVault = async () => {
    // Put the real pixels back before anything can export the viewer's DAT.
    cancelHighlight()
    if (materialColors.busy || materialColors.error) return
    if (!skinName.trim()) {
      setSaveError('Please enter a name')
      return
    }

    if (!hasElectron) {
      setSaveError('Electron environment required')
      return
    }

    const members = paintPairRef.current
    const session = editorSessionRef.current
    const isCurrent = () => session === editorSessionRef.current
    savingRef.current = true
    selectionRevisionRef.current += 1 // Cancel PNG imports still decoding before this snapshot.
    setIsSaving(true)
    setSaveError(null)

    try {
      await palette.flushColorAdjustments()
      // Use Electron IPC for export
      const base64Data = await exportPaintDat()
      if (!isCurrent()) return

      if (isStage) {
        const screenshot = streamCanvasRef.current?.toDataURL('image/png').split(',')[1]
        await api.post('/stage-editor/save', { workspaceId: stageWorkspaceRef.current.id, data: base64Data, name: skinName.trim(), screenshot })
        if (!isCurrent()) return
        setShowSaveModal(false); setIsDirty(false); setSkinName(''); onRefresh?.(); playSound('newSkin')
        return
      }
      const datBlob = members ? null : base64ToBlob(base64Data)

      // A skin from a custom character's library (pseudo key
      // custom_characters/<slug>/skins|costumes) saves back to that character's
      // Custom Skins — the generic intake would misfile its DAT under the donor
      // character. Keep the original Pl* DAT name: install keys costumes by it.
      const charKey = initialCostume?.character
      const customMatch = typeof charKey === 'string'
        ? charKey.match(/^custom_characters\/([^/]+)\//)
        : null

      const { default: JSZip } = await import('jszip')
      if (!isCurrent()) return
      const zip = new JSZip()
      // Keep the SOURCE costume's Pl* dat name (the intake only recognizes
      // Pl*-stemmed DATs; custom-character installs key costumes by it).
      // The skin title still becomes the display name via custom_title/name.
      let datName = initialCostume?.dat_name
        || sourceDatNameRef.current
        || (selectedVanillaCostume?.code ? `${selectedVanillaCostume.code}.dat` : '')
      if (!/^pl/i.test(datName)) {
        datName = `${skinName.trim()}.dat`
      }
      if (members) {
        paintPairRef.current = capturePaintPairExport(members, base64Data)
        addPaintPairToZip(zip, paintPairRef.current)
      } else {
        zip.file(datName, datBlob)
      }
      const zipBlob = await zip.generateAsync({ type: 'blob' })
      if (!isCurrent()) return

      const formData = new FormData()
      formData.append('file', new File([zipBlob], `${skinName.trim()}.zip`))
      // A new pair needs its own untouched partner too; duplicate skipping loses it.
      if (members) formData.append('duplicate_action', 'import_anyway')
      let saveUrl = '/import/file'
      if (customMatch) {
        formData.append('name', skinName.trim())
        if (selectedPoseName) {
          formData.append('poseName', selectedPoseName)
        }
        saveUrl = `/custom-characters/${customMatch[1]}/skins/add`
      } else {
        formData.append('custom_title', skinName.trim())
      }

      const result = await api.post(saveUrl, formData)
      if (!isCurrent()) return
      if (members && !customMatch) requireCompletePairSave(result)

      setShowSaveModal(false)
      setIsDirty(false)
      setSkinName('')

      onRefresh?.()

      playSound(result.camera_sound ? 'camera' : 'newSkin')
      alert(`Skin "${skinName}" saved to vault!`)
    } catch (error) {
      if (!isCurrent()) return
      console.error('Save error:', error)
      playSound('error')
      setSaveError(error.message)
    } finally {
      if (isCurrent()) { savingRef.current = false; setIsSaving(false) }
    }
  }

  // Download DAT file
  const handleDownloadDat = async () => {
    if (materialColors.busy || materialColors.error) return
    if (!hasElectron || !viewerWs) {
      alert('Not connected to viewer')
      return
    }

    const members = paintPairRef.current
    const session = editorSessionRef.current
    const isCurrent = () => session === editorSessionRef.current
    savingRef.current = true
    selectionRevisionRef.current += 1
    setIsSaving(true)
    try {
      await palette.flushColorAdjustments()
      // Use Electron IPC for export
      const base64Data = await exportPaintDat()
      if (!isCurrent()) return

      let blob = members ? null : base64ToBlob(base64Data)
      let filename = isStage ? sourceDatNameRef.current : `${selectedCharacter}_${selectedVanillaCostume?.colorName || 'custom'}.dat`
      if (members) {
        paintPairRef.current = capturePaintPairExport(members, base64Data)
        const { default: JSZip } = await import('jszip')
        if (!isCurrent()) return
        const zip = new JSZip()
        addPaintPairToZip(zip, paintPairRef.current)
        blob = await zip.generateAsync({ type: 'blob' })
        filename = `${selectedCharacter}_${selectedVanillaCostume?.colorName || 'custom'}.zip`
      }
      if (!isCurrent()) return
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (error) {
      if (!isCurrent()) return
      console.error('Download error:', error)
      alert('Failed to download: ' + error.message)
    } finally {
      if (isCurrent()) { savingRef.current = false; setIsSaving(false) }
    }
  }

  return { openSaveModal, handleSaveToVault, handleDownloadDat }
}
