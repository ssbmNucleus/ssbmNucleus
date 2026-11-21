/**
 * useStageSlots - replace-slot stage state for StageMode.
 *
 * The six tournament stages use Dynamic Alternate Stages (useStageVariants).
 * Every other versus stage is a *replace slot*: one skin written over the
 * vanilla stage file in the open project, restorable from the user's ISO.
 * Skins are ordinary vault stage variants (storage/das/<folder>/), the same
 * items the Vault's stage pages manage.
 *
 * This hook loads the backend's stage catalog (the single source of which
 * stages exist), the per-stage slot overview for the Stages list rows, and
 * the detail (current slot content + vault skins + added stages) for the
 * selected stage.
 */
import { useState, useEffect, useCallback } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'

export default function useStageSlots({ onRefresh }) {
  const [catalog, setCatalog] = useState([])
  const [slots, setSlots] = useState({})
  const [slot, setSlot] = useState(null)
  const [slotLoading, setSlotLoading] = useState(false)
  const [busy, setBusy] = useState(null)

  const moreStages = catalog.filter(stage => !stage.legal)
  const installedCount = Object.values(slots).filter(s => s.state === 'installed').length
  const availableTotal = Object.values(slots).reduce((n, s) => n + (s.availableCount || 0), 0)

  const fetchCatalog = useCallback(async () => {
    try {
      const data = await api.get('/stages/catalog')
      setCatalog(data.stages || [])
    } catch (err) {
      console.error('Failed to fetch stage catalog:', err)
    }
  }, [])

  const fetchSlots = useCallback(async () => {
    try {
      const data = await api.get('/stages/slots')
      setSlots(data.slots || {})
    } catch (err) {
      console.error('Failed to fetch stage slots:', err)
    }
  }, [])

  const fetchSlot = useCallback(async (code) => {
    setSlotLoading(true)
    try {
      const data = await api.get(`/stages/${code}/slot`)
      setSlot(data)
    } catch (err) {
      console.error(`Failed to fetch stage slot ${code}:`, err)
      setSlot(null)
    } finally {
      setSlotLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCatalog()
    fetchSlots()
  }, [fetchCatalog, fetchSlots])

  const refreshAfterChange = async (code) => {
    await Promise.all([fetchSlot(code), fetchSlots()])
    if (onRefresh) await onRefresh()
  }

  const installSkin = async (code, skin) => {
    if (busy) return
    setBusy(`install:${skin.id}`)
    try {
      await api.post(`/stages/${code}/slot/install`, { variantId: skin.id })
      playSound('newSkin')
      await refreshAfterChange(code)
    } catch (err) {
      console.error('Stage slot install error:', err)
      playSound('error')
      alert(`Install failed: ${err.message}`)
    } finally {
      setBusy(null)
    }
  }

  const restoreVanilla = async (code) => {
    if (busy) return
    setBusy('restore')
    try {
      await api.post(`/stages/${code}/slot/restore-vanilla`)
      playSound('newSkin')
      await refreshAfterChange(code)
    } catch (err) {
      console.error('Stage slot restore error:', err)
      playSound('error')
      alert(`Restore failed: ${err.message}`)
    } finally {
      setBusy(null)
    }
  }

  /**
   * Wrap a vault skin as an ADDED custom-stage package (vanilla stage kept,
   * skin gets its own stage-select entry). Returns the new custom stage's
   * slug for the caller to install through the custom-stages flow, or null.
   */
  const wrapAsCustomStage = async (code, skin) => {
    if (busy) return null
    setBusy(`wrap:${skin.id}`)
    try {
      const data = await api.post(`/stages/${code}/slot/add-as-stage`, { variantId: skin.id })
      return data.slug || null
    } catch (err) {
      console.error('Stage slot add-as-stage error:', err)
      playSound('error')
      alert(`Could not add as a new stage: ${err.message}`)
      return null
    } finally {
      setBusy(null)
    }
  }

  return {
    catalog,
    moreStages,
    slots,
    slot,
    slotLoading,
    busy,
    installedCount,
    availableTotal,
    fetchCatalog,
    fetchSlots,
    fetchSlot,
    installSkin,
    restoreVanilla,
    wrapAsCustomStage,
  }
}
