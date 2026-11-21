import { useState } from 'react'
import { api } from '../../shared/transport/api'
import { playSound } from '../../shared/audio/sounds'

/**
 * Netplay-safety actions for the costume currently open in the edit modal:
 * re-run the validator, answer the "unsafe costume" dialog, or override the
 * verdict by hand. Every outcome is applied to the open item in place and the
 * vault is refreshed -- no page reloads.
 *
 * The dialog itself is owned by the import pipeline (useFileImport) because the
 * same dialog serves imports; this hook only drives it, and owns `retestingItem`
 * — the flag that tells the shared dialog it is answering a RETEST rather than
 * an import (StorageViewer picks the handler off it).
 */
export function useSlippiSafety({ editingItem, setEditingItem, onRefresh, setShowSlippiDialog, setSlippiDialogData }) {
  const [retestingItem, setRetestingItem] = useState(null)
  const [safetyBusy, setSafetyBusy] = useState(false)

  const patchItem = (patch) =>
    setEditingItem?.(prev => prev ? { ...prev, data: { ...prev.data, ...patch } } : prev)

  const handleSlippiRetest = async (autoFix = false) => {
    if (!editingItem || editingItem.type !== 'costume') return
    setSafetyBusy(true)
    try {
      const data = await api.post('/api/mex/storage/costumes/retest-slippi', {
        character: editingItem.data.character,
        skinId: editingItem.data.id,
        autoFix: autoFix
      })

      // If not safe and not auto-fixing, show dialog
      if (!data.slippi_safe && !autoFix) {
        setRetestingItem(editingItem.data)
        setSlippiDialogData({
          unsafe_costumes: [{
            character: editingItem.data.character,
            color: editingItem.data.color
          }]
        })
        setShowSlippiDialog(true)
      } else {
        // Safe, or just fixed: reflect the verdict in place
        patchItem({ slippi_safe: !!data.slippi_safe, slippi_tested: true, slippi_manual_override: null })
        await onRefresh?.()
        playSound('boop')
      }
    } catch (err) {
      playSound('error')
      alert(`Error: ${err.message}`)
    } finally {
      setSafetyBusy(false)
    }
  }

  const handleRetestFixChoice = async (choice) => {
    setShowSlippiDialog(false)
    if (choice === 'cancel') {
      setRetestingItem(null)
      setSlippiDialogData(null)
      return
    }
    if (choice === 'fix') {
      // Retest with auto-fix
      await handleSlippiRetest(true)
    } else if (choice === 'import_as_is') {
      // Keep it as-is: the retest already recorded the unsafe verdict
      patchItem({ slippi_safe: false, slippi_tested: true, slippi_manual_override: null })
      await onRefresh?.()
    }
    setRetestingItem(null)
  }

  // Force the verdict by hand. `slippiSafe` is the new value; omit it to flip.
  const handleSlippiOverride = async (slippiSafe) => {
    if (!editingItem || editingItem.type !== 'costume') return
    const newStatus = typeof slippiSafe === 'boolean' ? slippiSafe : !editingItem.data.slippi_safe
    setSafetyBusy(true)
    try {
      await api.post('/api/mex/storage/costumes/override-slippi', {
        character: editingItem.data.character,
        skinId: editingItem.data.id,
        slippiSafe: newStatus
      })
      patchItem({ slippi_safe: newStatus, slippi_manual_override: true })
      await onRefresh?.()
      playSound('boop')
    } catch (err) {
      playSound('error')
      alert(`Error: ${err.message}`)
    } finally {
      setSafetyBusy(false)
    }
  }

  return {
    retestingItem,
    setRetestingItem,
    safetyBusy,
    handleSlippiRetest,
    handleRetestFixChoice,
    handleSlippiOverride,
  }
}

export default useSlippiSafety
