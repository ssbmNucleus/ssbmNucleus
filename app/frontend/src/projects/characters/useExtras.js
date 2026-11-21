/**
 * useExtras - state and API logic for CharacterMode extras mode
 * (laser colors, sword trails, model swaps, etc.)
 */
import { useState, useEffect, useRef } from 'react'
import { api } from '../../shared/transport/api'
import {
  IDLE_CURRENT,
  createRequestGate,
  currentFromError,
  currentFromResponse,
  currentForSelection,
  currentKey,
  loadingCurrent,
} from './currentExtraState'

export default function useExtras({ selectedFighter, vaultMetadata }) {
  const [extrasMode, setExtrasMode] = useState(false)
  const [selectedExtraType, setSelectedExtraType] = useState(null)
  const [extraMods, setExtraMods] = useState({})
  const [selectedExtraMod, setSelectedExtraMod] = useState(null)
  const [importingExtra, setImportingExtra] = useState(false)
  const [restoringExtra, setRestoringExtra] = useState(false)
  const [extraImportError, setExtraImportError] = useState(null)
  // "Currently in MEX" reading (see currentExtraState.js). One object so the
  // colors and the verdict always describe the same fighter/effect.
  const [current, setCurrent] = useState(IDLE_CURRENT)
  const gateRef = useRef(null)
  if (!gateRef.current) gateRef.current = createRequestGate()

  // Fetch extras when entering extras mode or selecting a type
  useEffect(() => {
    if (extrasMode && selectedFighter) {
      fetchExtrasMods()
    }
  }, [extrasMode, selectedFighter])

  // The vault's own Extras page (and the user's AI over MCP) can add or delete
  // mods while this panel stays mounted on the hidden project tab. App reads
  // the vault again after every such change and hands down a new metadata
  // object, so read this fighter's list again too: the "N in vault" counts and
  // "Available to Import" used to stay stale until Back and reopen.
  const vaultFirstRef = useRef(true)
  useEffect(() => {
    if (vaultFirstRef.current) { vaultFirstRef.current = false; return }
    if (extrasMode && selectedFighter) fetchExtrasMods()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vaultMetadata])

  const selectionKey = extrasMode && selectedExtraType && selectedFighter
    ? currentKey(selectedFighter.name, selectedExtraType.id)
    : null

  useEffect(() => {
    const key = selectionKey
    // Invalidate every read in flight: its answer belongs to whatever was
    // selected before. A new selection starts from "Loading", never from the
    // previous effect's colors.
    const changed = gateRef.current.select(key)
    if (!key) {
      setCurrent(IDLE_CURRENT)
      return
    }
    if (changed) setCurrent(loadingCurrent(key))
    fetchCurrentColors()
  }, [extrasMode, selectedExtraType, selectedFighter])

  const fetchExtrasMods = async () => {
    // Fetch all mods from vault
    if (!selectedFighter) return
    try {
      const data = await api.get(`/storage/extras/list/${selectedFighter.name}`)
      setExtraMods(data.extras || {})
    } catch (err) {
      console.error('Failed to fetch extras:', err)
      if (!err.data) setExtraMods({})  // envelope errors keep the last good map
    }
  }

  const fetchCurrentColors = async () => {
    // Read actual colors from .dat file
    if (!selectedExtraType || !selectedFighter) return
    const key = currentKey(selectedFighter.name, selectedExtraType.id)
    const token = gateRef.current.begin(key)
    if (!token) return  // the selection moved on before this read started
    try {
      const data = await api.get(`/storage/extras/current/${selectedFighter.name}/${selectedExtraType.id}`)
      if (!gateRef.current.accepts(token)) return
      setCurrent(currentFromResponse(key, data, token.seq))
    } catch (err) {
      if (!gateRef.current.accepts(token)) return
      console.error('Failed to fetch current colors:', err)
      setCurrent(currentFromError(key, err))
    }
  }

  const getAllMods = (typeId) => {
    return extraMods[typeId] || []
  }

  const handleImportExtra = async () => {
    if (!selectedExtraMod || !selectedExtraType || importingExtra || restoringExtra || !selectedFighter) return

    setImportingExtra(true)
    setExtraImportError(null)
    try {
      // Use different endpoint for model types vs hex types
      const isModelType = selectedExtraType.type === 'model'
      const endpoint = isModelType
        ? '/storage/models/install'
        : '/storage/extras/install'

      const data = await api.post(endpoint, {
        character: selectedFighter.name,
        extraType: selectedExtraType.id,
        modId: selectedExtraMod.id
      })

      if (data.offsetSkips?.length) {
        // Some layers could not be safely written (offsets not found in
        // the current file) -- the rest installed fine. Don't pretend it
        // was a clean install.
        const layers = [...new Set(data.offsetSkips.map(s => s.layer_id))].join(', ')
        alert(`Installed ${selectedExtraMod.name}, but ${data.offsetSkips.length} layer(s) could not be safely written and kept their previous colors:\n${layers}`)
      }
      if (!isModelType) {
        await fetchCurrentColors()
      } else {
        // Only show alert for model types since we can't preview them
        alert(`Successfully installed ${selectedExtraMod.name}!`)
      }
      setSelectedExtraMod(null)
    } catch (err) {
      console.error('Failed to import extra:', err)
      const message = err.message || 'Unknown error'
      setExtraImportError(message)
      alert(`Install failed: ${message}`)
    } finally {
      setImportingExtra(false)
      fetchExtrasMods()
    }
  }

  const handleRestoreVanilla = async () => {
    if (!selectedExtraType || importingExtra || restoringExtra || !selectedFighter) return

    // Its own flag: the overlay says "Restoring", not "Importing".
    setRestoringExtra(true)
    try {
      await api.post('/storage/extras/restore-vanilla', {
        character: selectedFighter.name,
        extraType: selectedExtraType.id
      })
      if (selectedExtraType.type === 'model') {
        // The model card can't show what is installed, so say it worked.
        alert(`Restored the vanilla ${selectedExtraType.name}.`)
      } else {
        await fetchCurrentColors()
      }
    } catch (err) {
      console.error('Failed to restore vanilla:', err)
      alert(`Restore failed: ${err.message || 'Unknown error'}`)
    } finally {
      setRestoringExtra(false)
      // Read the vault list again with the effect, as Back and reopen did.
      fetchExtrasMods()
    }
  }

  return {
    extrasMode,
    setExtrasMode,
    selectedExtraType,
    setSelectedExtraType,
    extraMods,
    selectedExtraMod,
    setSelectedExtraMod,
    importingExtra,
    restoringExtra,
    extraImportError,
    setExtraImportError,
    // Guarded by key: in the render right after a switch (before the effect
    // above resets the state) the previous effect's reading must not show.
    current: currentForSelection(current, selectionKey),
    getAllMods,
    handleImportExtra,
    handleRestoreVanilla
  }
}
