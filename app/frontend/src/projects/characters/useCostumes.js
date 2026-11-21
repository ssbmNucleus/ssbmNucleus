/**
 * useCostumes - MEX costume management state and logic for CharacterMode
 *
 * Covers: MEX costume fetching, team colors, single/batch import,
 * removal (with Ice Climbers Popo/Nana pairing), drag-drop reordering,
 * and available-costume selection. Team colors live in useCostumeTeamColors
 * and the reorder queue in useCostumeReorder; this hook composes them.
 */
import { useState, useEffect, useRef } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'
import { appConfirm } from '../../shared/ui/appDialogs'
import {
  installedCostumeKey,
  parseInstalledCostumeKey,
  selectionAfterRemove,
} from './installedCostumeSelection'
import { EMPTY_TEAM, useCostumeTeamColors } from './useCostumeTeamColors'
import { useCostumeReorder } from './useCostumeReorder'

// Zelda and Sheik are one in-game pairing: slot N of one loads slot N of the
// other on transform. The panel therefore shows BOTH fighters together (Zelda
// on top, Sheik below, slot-paired) whenever either is selected.
export const ZS_PAIR = ['Zelda', 'Sheik']
export const isZeldaSheikName = (name) => ZS_PAIR.includes(name)

export default function useCostumes({ fighters, storageCostumes, selectedFighter, onRefresh }) {
  const [mexCostumes, setMexCostumes] = useState([])
  const [loadingFighter, setLoadingFighter] = useState(false)
  const [dataReady, setDataReady] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importingCostume, setImportingCostume] = useState(null)
  const [removing, setRemoving] = useState(false)
  const [removingCostume, setRemovingCostume] = useState(null)
  const [selectedCostumes, setSelectedCostumes] = useState(new Set())
  const [selectedInstalledCostumes, setSelectedInstalledCostumes] = useState(new Set())
  const [batchImporting, setBatchImporting] = useState(false)
  const [resettingVanilla, setResettingVanilla] = useState(false)
  const [replacement, setReplacement] = useState(null)
  const [replacementBusy, setReplacementBusy] = useState(false)
  const [replacementError, setReplacementError] = useState('')
  const replacementFlight = useRef(false)
  const replacementGeneration = useRef(0)

  const cancelReplacement = () => {
    if (replacementFlight.current) return
    replacementGeneration.current++
    setReplacement(null)
    setReplacementError('')
  }

  // Replacing is picked inline from the vault list rather than in a modal, so
  // Escape has to be wired up by hand to back out of it.
  useEffect(() => {
    if (!replacement) return
    const onKeyDown = (e) => { if (e.key === 'Escape') cancelReplacement() }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [replacement])

  const beginReplacement = async (fighter, index, costume) => {
    if (syncingOrder || importing || batchImporting || removing || resettingVanilla || replacementFlight.current) return
    const generation = ++replacementGeneration.current
    setReplacement({ fighter, index, costume, version: null })
    setReplacementError('')
    try {
      const context = await api.get(`/replace-vanilla/${encodeURIComponent(fighter)}/${index}`)
      if (generation === replacementGeneration.current) setReplacement({ fighter, index, costume, ...context })
    } catch (err) {
      if (generation === replacementGeneration.current) setReplacementError(err.message)
    }
  }

  const replaceWithCostume = async (costume) => {
    if (!replacement?.version || replacementFlight.current) return
    replacementFlight.current = true
    setReplacementBusy(true)
    setReplacementError('')
    try {
      const paired = costume.pairedNanaId ? storageCostumes.find(c => c.folder === costume.pairedNanaId) : null
      if (costume.pairedNanaId && !paired) throw new Error('The paired Nana costume is missing from the vault')
      await api.post(`/replace-vanilla/${encodeURIComponent(replacement.fighter)}/${replacement.index}`, {
        version: replacement.version, costumePath: costume.zipPath, pairedCostumePath: paired?.zipPath,
      })
      playSound('newSkin')
      await refreshMexCostumes(replacement.fighter)
      setReplacement(null)
      onRefresh?.()
    } catch (err) {
      setReplacementError(err.message || 'Could not replace costume')
    } finally {
      replacementFlight.current = false
      setReplacementBusy(false)
    }
  }
  const [batchProgress, setBatchProgress] = useState({ current: 0, total: 0 })

  // Zelda/Sheik combined view: both fighters' MEX costumes + team colors
  const [pairCostumes, setPairCostumes] = useState({ Zelda: [], Sheik: [] })
  const [pairTeamColors, setPairTeamColors] = useState({ Zelda: EMPTY_TEAM, Sheik: EMPTY_TEAM })
  const isZeldaSheik = !!selectedFighter && isZeldaSheikName(selectedFighter.name)

  // Confirm dialog state for removing costumes
  const [showConfirmDialog, setShowConfirmDialog] = useState(false)
  const [pendingRemoval, setPendingRemoval] = useState(null)

  // Ref for scrolling Available to Import list to top on character change
  const availableListRef = useRef(null)

  // setSelectedTeamColor / fetchTeamColors come from useCostumeTeamColors below;
  // effects run after render, so they are defined by the time this runs.
  useEffect(() => {
    cancelReplacement()
    if (selectedFighter) {
      // Clear old data immediately for clean transition
      setDataReady(false)
      setMexCostumes([])
      setSelectedTeamColor(null)
      if (isZeldaSheikName(selectedFighter.name)) {
        setPairCostumes({ Zelda: [], Sheik: [] })
        fetchPair(true)
      } else {
        fetchMexCostumes(selectedFighter.name, true)
        fetchTeamColors(selectedFighter.name)
      }
      // Reset scroll position of Available to Import list
      if (availableListRef.current) {
        availableListRef.current.scrollTop = 0
      }
    }
  }, [selectedFighter])

  // Fetch BOTH Zelda and Sheik costume lists + team colors for the combined view.
  const fetchPair = async (showLoading = false) => {
    if (showLoading) {
      setLoadingFighter(true)
    }
    try {
      const fetchOne = async (name, path, fallback) => {
        try {
          return await api.get(`/fighters/${encodeURIComponent(name)}/${path}`)
        } catch (err) {
          console.error(`Failed to fetch ${name} ${path}:`, err)
          return fallback
        }
      }
      // The costumes endpoint shells out to MexCLI, which opens the whole
      // workspace -- two CONCURRENT mexcli processes on the same project make
      // one of them fail (and that fighter shows 0 costumes). Fetch the two
      // costume lists SEQUENTIALLY; team colors are plain file reads, so those
      // can run in parallel.
      const zc = await fetchOne('Zelda', 'costumes', {})
      const sc = await fetchOne('Sheik', 'costumes', {})
      const [zt, st] = await Promise.all([
        fetchOne('Zelda', 'team-colors', EMPTY_TEAM),
        fetchOne('Sheik', 'team-colors', EMPTY_TEAM)
      ])
      setPairCostumes({ Zelda: zc.costumes || [], Sheik: sc.costumes || [] })
      setPairTeamColors({
        Zelda: { red: zt.red ?? null, blue: zt.blue ?? null, green: zt.green ?? null },
        Sheik: { red: st.red ?? null, blue: st.blue ?? null, green: st.green ?? null }
      })
    } catch (err) {
      console.error('Failed to fetch Zelda/Sheik pair:', err)
      setPairCostumes({ Zelda: [], Sheik: [] })
    } finally {
      if (showLoading) {
        setLoadingFighter(false)
        setTimeout(() => setDataReady(true), 50)
      }
    }
  }

  // Refresh the In-ISO list(s) after an import/remove/reorder, pair-aware.
  const refreshMexCostumes = async (fighterName) => {
    if (isZeldaSheikName(fighterName)) {
      await fetchPair()
    } else {
      await fetchMexCostumes(fighterName)
    }
  }

  const handleResetVanilla = async () => {
    if (!selectedFighter || selectedFighter.isMexFighter || resettingVanilla || syncingOrder) return

    const isPair = isZeldaSheikName(selectedFighter.name)
    const isIceClimbers = selectedFighter.name === 'Ice Climbers'
    const label = isPair
      ? 'Zelda and Sheik'
      : (isIceClimbers ? 'Ice Climbers (Popo and Nana)' : selectedFighter.name)
    const installedCount = isPair
      ? (pairCostumes.Zelda.length + pairCostumes.Sheik.length)
      : mexCostumes.length
    const noun = isIceClimbers
      ? (installedCount === 1 ? 'paired costume slot' : 'paired costume slots')
      : (installedCount === 1 ? 'costume' : 'costumes')
    const confirmed = await appConfirm(
      'Remove all ' + installedCount + ' installed ' + noun + ' for ' + label
        + ' and restore the complete vanilla costume set? Imported skins for '
        + label + ' will be removed from this build.',
      {
        title: 'Reset ' + label + ' to Vanilla',
        confirmText: 'Reset to Vanilla',
        confirmStyle: 'danger',
      }
    )
    if (!confirmed) return

    setResettingVanilla(true)
    try {
      await api.post('/restore-vanilla-costumes', {
        fighter: selectedFighter.name,
      })
      playSound('newSkin')
      setSelectedCostumes(new Set())
      setSelectedInstalledCostumes(new Set())
      await onRefresh()
      await refreshMexCostumes(selectedFighter.name)
    } catch (err) {
      console.error('Vanilla costume reset failed:', err)
      alert('Reset failed: ' + err.message)
    } finally {
      setResettingVanilla(false)
    }
  }

  const fetchMexCostumes = async (fighterName, showLoading = false) => {
    if (showLoading) {
      setLoadingFighter(true)
    }
    try {
      const data = await api.get(`/fighters/${encodeURIComponent(fighterName)}/costumes`)
      setMexCostumes(data.costumes || [])
    } catch (err) {
      console.error('Failed to fetch MEX costumes:', err)
      if (!err.data) setMexCostumes([])  // envelope errors keep the last good list
    } finally {
      if (showLoading) {
        setLoadingFighter(false)
        // Small delay to let React render, then trigger cascade
        setTimeout(() => setDataReady(true), 50)
      }
    }
  }

  const {
    teamColors, selectedTeamColor, setSelectedTeamColor, fetchTeamColors, handleTeamColorClick,
    handleCostumeTeamAssign, getCostumeTeamColor, getPairCostumeTeamColor, handlePairCostumeTeamAssign,
  } = useCostumeTeamColors({ selectedFighter, pairTeamColors, fetchPair })

  const handleImportCostume = async (costume) => {
    if (importing || importingCostume) {
      console.log('Import already in progress, ignoring click')
      return
    }

    console.log(`=== IMPORT REQUEST ===`)
    console.log(`Costume:`, costume)
    console.log(`Fighter: ${costume.character}`)
    console.log(`Zip Path: ${costume.zipPath}`)

    setImporting(true)
    setImportingCostume(costume.zipPath)

    try {
      // Custom-character added skin: route through the dedicated MexCLI
      // import-costume path instead of the vanilla /import endpoint
      if (costume.isCustomCharSkin) {
        await api.post('/custom-characters/install-skin', {
          slug: costume.customSlug,
          skinId: costume.skinId,
          fighterName: costume.character,
        })
        await onRefresh()
        await refreshMexCostumes(costume.character)
        return
      }

      // Ice Climbers: Auto-import paired Nana when Popo is selected
      if (costume.isPopo && costume.pairedNanaId) {
        console.log('Ice Climbers Popo detected - will auto-import paired Nana')

        // Find paired Nana costume in storage
        const nanaCostume = storageCostumes.find(c => c.folder === costume.pairedNanaId)

        if (!nanaCostume) {
          console.error('Paired Nana costume not found:', costume.pairedNanaId)
          alert('Paired Nana costume not found in storage')
          return
        }

        // Import Popo first (MEX calls it "Ice Climbers")
        try {
          const popoData = await api.post('/import', {
            fighter: 'Ice Climbers',
            costumePath: costume.zipPath
          })
          console.log('Popo import response:', popoData)
        } catch (popoErr) {
          alert(`Popo import failed: ${popoErr.message}`)
          return
        }

        // Import Nana second - find Nana fighter (ID 11, could be named "Nana" or "Popo")
        const nanaFighter = fighters.find(f => f.internalId === 11)

        if (!nanaFighter) {
          alert(`Popo imported but could not find Nana fighter (ID 11) in project`)
          return
        }

        console.log(`Importing Nana to fighter: ${nanaFighter.name}`)

        try {
          const nanaData = await api.post('/import', {
            fighter: nanaFighter.name,
            costumePath: nanaCostume.zipPath
          })
          console.log('Nana import response:', nanaData)
        } catch (nanaErr) {
          alert(`Nana import failed: ${nanaErr.message}`)
          return
        }

        console.log(`✓ Successfully imported Ice Climbers pair (Popo + Nana)`)

        // Refresh
        await onRefresh()
        await fetchMexCostumes('Ice Climbers')

      } else {
        // Normal single costume import
        const requestBody = {
          fighter: costume.character,
          costumePath: costume.zipPath
        }

        console.log('Sending import request:', requestBody)

        const data = await api.post('/import', requestBody)
        console.log('Import response:', data)

        console.log(`✓ Successfully imported ${data.result.costumesImported} costume(s) to ${costume.character}`)

        // Refresh
        await onRefresh()
        await refreshMexCostumes(costume.character)
      }
    } catch (err) {
      console.error('Import error:', err)
      alert(`Import failed: ${err.message}`)
    } finally {
      setImporting(false)
      setImportingCostume(null)
    }
  }

  const handleRemoveCostume = (fighterName, costumeIndex, costumeName) => {
    if (removing || removingCostume !== null) {
      console.log('Remove already in progress, ignoring click')
      return
    }

    const isIceClimbers = fighterName === 'Ice Climbers'

    // Show confirm dialog instead of native confirm()
    setPendingRemoval({ fighterName, costumeIndex, costumeName, isIceClimbers })
    setShowConfirmDialog(true)
  }

  const removeCostumeFromProject = async (fighterName, costumeIndex) => {
    const requestBody = {
      fighter: fighterName,
      costumeIndex: costumeIndex
    }

    console.log('Sending remove request:', requestBody)

    let data
    try {
      data = await api.post('/remove', requestBody)
    } catch (err) {
      throw new Error(err.message || 'Remove failed')
    }
    console.log('Remove response:', data)

    return data
  }

  const handleBatchRemoveCostumes = () => {
    if (removing || selectedInstalledCostumes.size === 0) return

    const items = Array.from(selectedInstalledCostumes)
      .map(parseInstalledCostumeKey)
      .filter(Boolean)

    if (items.length === 0) return

    setPendingRemoval({ bulk: true, items })
    setShowConfirmDialog(true)
  }

  const confirmRemoveCostume = async () => {
    if (!pendingRemoval) return

    const removal = pendingRemoval
    setShowConfirmDialog(false)
    setPendingRemoval(null)

    if (removal.bulk) {
      await confirmBatchRemoveCostumes(removal.items)
      return
    }

    const { fighterName, costumeIndex, costumeName, isIceClimbers } = removal

    console.log(`=== REMOVE REQUEST ===`)
    console.log(`Fighter: ${fighterName}`)
    console.log(`Costume Index: ${costumeIndex}`)
    console.log(`Costume Name: ${costumeName}`)
    if (isIceClimbers) {
      console.log(`Will also remove paired Nana at index ${costumeIndex}`)
    }

    setRemoving(true)
    setRemovingCostume(costumeIndex)

    // Fighters whose slot `costumeIndex` was actually removed. Their later
    // slots shift up by one, so the selection is renumbered to match (in
    // `finally`, so it happens even if the refresh below fails).
    const removedFrom = []

    try {
      await removeCostumeFromProject(fighterName, costumeIndex)
      removedFrom.push(fighterName)

      console.log(`✓ Successfully removed "${costumeName}" from ${fighterName}`)

      // Ice Climbers: Also remove paired Nana at same index
      if (isIceClimbers) {
        console.log(`Removing paired Nana at index ${costumeIndex}...`)

        const nanaFighter = fighters.find(f => f.internalId === 11)

        if (!nanaFighter) {
          console.warn('Nana fighter (ID 11) not found in project')
          alert(`Popo removed but could not find Nana fighter in project`)
        } else {
          console.log(`Found Nana fighter named: ${nanaFighter.name}`)

          const nanaRequestBody = {
            fighter: nanaFighter.name,
            costumeIndex: costumeIndex
          }

          try {
            const nanaData = await api.post('/remove', nanaRequestBody)
            removedFrom.push(nanaFighter.name)
            console.log('Nana remove response:', nanaData)
            console.log(`✓ Successfully removed paired Nana from ${nanaFighter.name}`)
          } catch (nanaErr) {
            alert(`Popo removed but Nana removal failed: ${nanaErr.message}`)
          }
        }
      }

      // Refresh
      await onRefresh()
      await refreshMexCostumes(fighterName)

    } catch (err) {
      console.error('Remove error:', err)
      alert(`Remove error: ${err.message}`)
    } finally {
      if (removedFrom.length > 0) {
        setSelectedInstalledCostumes(prev => removedFrom.reduce(
          (sel, name) => selectionAfterRemove(sel, name, costumeIndex), prev))
      }
      setRemoving(false)
      setRemovingCostume(null)
    }
  }

  const confirmBatchRemoveCostumes = async (items) => {
    const deduped = new Map()
    items.forEach(item => {
      deduped.set(installedCostumeKey(item.fighterName, item.costumeIndex), item)
      if (item.fighterName === 'Ice Climbers') {
        const nanaFighter = fighters.find(f => f.internalId === 11)
        if (nanaFighter) {
          deduped.set(installedCostumeKey(nanaFighter.name, item.costumeIndex), {
            fighterName: nanaFighter.name,
            costumeIndex: item.costumeIndex,
            costumeName: `Paired Nana slot ${item.costumeIndex + 1}`,
          })
        }
      }
    })

    const removalQueue = Array.from(deduped.values()).sort((a, b) => {
      const fighterCompare = a.fighterName.localeCompare(b.fighterName)
      return fighterCompare || b.costumeIndex - a.costumeIndex
    })

    setRemoving(true)
    let successCount = 0
    let failCount = 0

    // ONE batch call: the backend removes every selected costume in a single
    // workspace recompile (descending index per fighter, so indices stay valid) --
    // ~Nx faster than /remove per costume, same final costume set.
    try {
      const items = removalQueue.map(it => ({
        fighter: it.fighterName, costumeIndex: it.costumeIndex
      }))
      await api.post('/remove-batch', { items })
      successCount = items.length
    } catch (err) {
      failCount = removalQueue.length
      console.error('Batch remove error:', err)
    }

    try {
      await onRefresh()
      if (selectedFighter) {
        await refreshMexCostumes(selectedFighter.name)
      }
    } finally {
      setRemoving(false)
      setRemovingCostume(null)
      setSelectedInstalledCostumes(new Set())
    }

    if (failCount > 0) {
      playSound('error')
      alert(`Batch remove completed:\n${successCount} removed, ${failCount} failed`)
    } else {
      playSound('boop')
      console.log(`âœ“ Successfully removed ${successCount} costume(s)`)
    }
  }

  const handleBatchImport = async () => {
    if (selectedCostumes.size === 0 || batchImporting) return

    setBatchImporting(true)
    const costumesToImport = Array.from(selectedCostumes)
    const total = costumesToImport.length
    setBatchProgress({ current: 0, total })

    let successCount = 0
    let failCount = 0
    let completedCount = 0
    const importedNanas = new Set()
    const markBatchStepComplete = (n = 1) => {
      completedCount += n
      setBatchProgress({ current: completedCount, total })
    }

    // Partition the selection: ordinary costumes (incl. Ice Climbers pairs)
    // collapse into ONE /import-batch call (one workspace recompile + parallel
    // CSP decode -- ~7x faster than N /import calls). Custom-character skins use
    // a different endpoint (/custom-characters/install-skin) and aren't a plain
    // costume zip, so they stay individual.
    const batchItems = []        // { fighter, costumePath } in selection order
    const batchSelections = []   // selected zipPaths represented in batchItems
    const customSkins = []       // costumes needing install-skin

    for (const zipPath of costumesToImport) {
      const costume = storageCostumes.find(c => c.zipPath === zipPath)

      if (!costume) {
        failCount++
        markBatchStepComplete()
        continue
      }

      // Skip if this is a Nana that was already queued as part of a Popo pair
      if (importedNanas.has(zipPath)) {
        markBatchStepComplete()
        continue
      }

      if (costume.isCustomCharSkin) {
        customSkins.push(costume)
        continue
      }

      // Ice Climbers: queue the paired Nana alongside Popo. Two separate manifest
      // entries (Ice Climbers + Nana fighter) -- NOT one bundled zip -- keeps the
      // Popo/Nana slots aligned, same as two sequential /import calls.
      if (costume.isPopo && costume.pairedNanaId) {
        const nanaCostume = storageCostumes.find(c => c.folder === costume.pairedNanaId)
        const nanaFighter = fighters.find(f => f.internalId === 11)

        if (!nanaCostume) {
          console.error('Paired Nana costume not found:', costume.pairedNanaId)
          failCount++
          markBatchStepComplete()
          continue
        }
        if (!nanaFighter) {
          console.error('Nana fighter (ID 11) not found in project')
          failCount++
          markBatchStepComplete()
          continue
        }

        batchItems.push({ fighter: 'Ice Climbers', costumePath: costume.zipPath })
        batchItems.push({ fighter: nanaFighter.name, costumePath: nanaCostume.zipPath })
        importedNanas.add(nanaCostume.zipPath)
        batchSelections.push(zipPath)
      } else {
        batchItems.push({ fighter: costume.character, costumePath: costume.zipPath })
        batchSelections.push(zipPath)
      }
    }

    // 1) Custom-character skins -- sequential (separate endpoint, not batchable).
    for (const costume of customSkins) {
      try {
        await api.post('/custom-characters/install-skin', {
          slug: costume.customSlug,
          skinId: costume.skinId,
          fighterName: costume.character,
        })
        successCount++
      } catch (err) {
        console.error(`Import error for ${costume.name}:`, err)
        failCount++
      } finally {
        markBatchStepComplete()
      }
    }

    // 2) Everything else -- ONE batch call.
    if (batchItems.length > 0) {
      try {
        const data = await api.post('/import-batch', { items: batchItems })
        console.log(`✓ Batch-imported ${batchItems.length} file(s) for ${batchSelections.length} selection(s)`, data.result)
        successCount += batchSelections.length
      } catch (err) {
        console.error('Batch import error:', err)
        failCount += batchSelections.length
      } finally {
        markBatchStepComplete(batchSelections.length)
      }
    }

    // Refresh once at the end
    await onRefresh()
    if (selectedFighter) {
      await refreshMexCostumes(selectedFighter.name)
    }

    // Clear selections
    setSelectedCostumes(new Set())
    setBatchImporting(false)
    setBatchProgress({ current: 0, total: 0 })

    // Show summary
    if (failCount > 0) {
      playSound('error')
      alert(`Batch import completed:\n${successCount} succeeded, ${failCount} failed`)
    } else {
      playSound('newSkin')
      console.log(`✓ Successfully imported ${successCount} costume(s)`)
    }
  }

  // Is `name` the fighter currently on screen? (Zelda/Sheik share one panel, so
  // either counts as showing the other.)
  const isVisibleFighter = (name) => !!selectedFighter && (
    selectedFighter.name === name ||
    (isZeldaSheikName(selectedFighter.name) && isZeldaSheikName(name))
  )

  const {
    draggedIndex, dragOverIndex, syncingOrder, pendingOrderMoves, draggedRow,
    handleDragStart, handleDragOver, handleDragEnter, handleDragLeave, handleDrop,
    handleDragEnd, handlePairDragStart, handlePairDragEnter, handlePairDrop,
  } = useCostumeReorder({
    selectedFighter, setMexCostumes, setSelectedInstalledCostumes, setPairCostumes, refreshMexCostumes, isVisibleFighter,
  })

  const getCostumesForFighter = (fighterName) => {
    return storageCostumes.filter(c => c.character === fighterName && !c.isNana)
  }

  const toggleCostumeSelection = (zipPath) => {
    setSelectedCostumes(prev => {
      const newSet = new Set(prev)
      if (newSet.has(zipPath)) {
        newSet.delete(zipPath)
      } else {
        newSet.add(zipPath)
      }
      return newSet
    })
  }

  const selectAllCostumes = () => {
    if (!selectedFighter) return
    const names = isZeldaSheik ? ZS_PAIR : [selectedFighter.name]
    setSelectedCostumes(prev => {
      const newSet = new Set(prev)
      names.forEach(name => getCostumesForFighter(name).forEach(c => newSet.add(c.zipPath)))
      return newSet
    })
  }

  const clearSelection = () => {
    setSelectedCostumes(new Set())
  }

  const toggleInstalledCostumeSelection = (fighterName, costumeIndex) => {
    const key = installedCostumeKey(fighterName, costumeIndex)
    setSelectedInstalledCostumes(prev => {
      const newSet = new Set(prev)
      if (newSet.has(key)) {
        newSet.delete(key)
      } else {
        newSet.add(key)
      }
      return newSet
    })
  }

  const clearInstalledCostumeSelection = () => {
    setSelectedInstalledCostumes(new Set())
  }

  return {
    replacement, replacementBusy, replacementError, beginReplacement, cancelReplacement, replaceWithCostume,
    mexCostumes,
    refreshMexCostumes,
    loadingFighter,
    dataReady,
    importing,
    importingCostume,
    removing,
    removingCostume,
    selectedCostumes,
    selectedInstalledCostumes,
    batchImporting,
    resettingVanilla,
    batchProgress,
    draggedIndex,
    dragOverIndex,
    syncingOrder,
    pendingOrderMoves,
    isZeldaSheik,
    pairCostumes,
    draggedRow,
    getPairCostumeTeamColor,
    handlePairCostumeTeamAssign,
    handlePairDragStart,
    handlePairDragEnter,
    handlePairDrop,
    showConfirmDialog,
    setShowConfirmDialog,
    pendingRemoval,
    setPendingRemoval,
    teamColors,
    selectedTeamColor,
    availableListRef,
    handleTeamColorClick,
    handleCostumeTeamAssign,
    getCostumeTeamColor,
    handleImportCostume,
    handleResetVanilla,
    handleRemoveCostume,
    confirmRemoveCostume,
    handleBatchRemoveCostumes,
    handleBatchImport,
    handleDragStart,
    handleDragOver,
    handleDragEnter,
    handleDragLeave,
    handleDrop,
    handleDragEnd,
    getCostumesForFighter,
    toggleCostumeSelection,
    selectAllCostumes,
    clearSelection,
    installedCostumeKey,
    toggleInstalledCostumeSelection,
    clearInstalledCostumeSelection
  }
}
