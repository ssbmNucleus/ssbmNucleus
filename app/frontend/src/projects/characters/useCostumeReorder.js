import { useEffect, useRef, useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'
import { getProjectGeneration, isProjectChanged } from '../../shared/transport/projectGeneration'
import { appAlert } from '../../shared/ui/appDialogs'
import { selectionAfterMove } from './installedCostumeSelection'
import { orderSaveStarted, orderSaveSettled } from './orderSaves'

// Drag-and-drop reordering of installed costumes (one fighter, or within a
// Zelda/Sheik row). The panel updates at once; the moves queue up and save
// in the background as one batched MexCLI reorder.
export function useCostumeReorder({ selectedFighter, setMexCostumes, setSelectedInstalledCostumes, setPairCostumes, refreshMexCostumes, isVisibleFighter }) {
  const [draggedIndex, setDraggedIndex] = useState(null)
  const [dragOverIndex, setDragOverIndex] = useState(null)
  // True while costume order changes are being saved to the project in the
  // BACKGROUND. The UI updates optimistically on drop and never blocks on the
  // (slow) MexCLI reorder; this just flags that a save is still settling so the
  // panel can show a subtle indicator and disable conflicting actions.
  const [syncingOrder, setSyncingOrder] = useState(false)
  // How many drags are still unsaved (queued + in flight), so the badge can show
  // real progress instead of an indefinite spinner.
  const [pendingOrderMoves, setPendingOrderMoves] = useState(0)
  // Pending reorder moves ({ fighter, fromIndex, toIndex }) waiting to be saved,
  // and a single-flight guard so only one MexCLI reorder runs at a time.
  // The workspace is keyed by generation. Its queued drags keep that project
  // even if a switch unmounts this hook before the debounce or next batch runs.
  const projectGenerationRef = useRef(getProjectGeneration())
  const reorderQueueRef = useRef([])
  const reorderProcessingRef = useRef(false)
  // Drops arrive in bursts (a user rarely drags just once). Coalesce them for a
  // beat so a run of drags becomes ONE save instead of one save per drag.
  const reorderDebounceRef = useRef(null)
  const REORDER_DEBOUNCE_MS = 400
  const [draggedRow, setDraggedRow] = useState(null) // which ZS row a drag started in
  // Holds one orderSaves slot from the first queued drag until the drain that
  // saves it ends, so Switch/Close Project can wait for it.
  const holdingSaveRef = useRef(false)
  const holdSave = () => {
    if (holdingSaveRef.current) return
    holdingSaveRef.current = true
    orderSaveStarted()
  }
  const releaseSave = () => {
    if (!holdingSaveRef.current) return
    holdingSaveRef.current = false
    orderSaveSettled()
  }

  // Drag and Drop Handlers
  const handleDragStart = (e, index) => {
    setDraggedIndex(index)
    e.dataTransfer.effectAllowed = 'move'
    // Tell the window-wide import listener (ImportFab) this is an in-app
    // reorder, not an OS file drop -- same flag the vault reorder hook sets.
    document.documentElement.dataset.nucInternalDrag = '1'
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDragEnter = (e, index) => {
    e.preventDefault()
    setDragOverIndex(index)
  }

  const handleDragLeave = (e) => {
    if (e.currentTarget === e.target) {
      setDragOverIndex(null)
    }
  }

  // Drain the pending-reorder queue in the background as ONE /reorder-batch call:
  // every queued drag is a SPLICE move, and the backend applies them all inside a
  // single MexCLI workspace save. (The old path replayed each drag as a run of
  // adjacent /reorder SWAPS -- |to-from| full project recompiles, ~3s each, for a
  // SINGLE drag. Dragging the last of 16 costumes to the top cost ~45s.)
  //
  // Still single-flight: never two MexCLI processes on one project at once; the
  // backend also holds a workspace lock as a hard guard.
  const processReorderQueue = async () => {
    if (reorderProcessingRef.current) return
    if (reorderQueueRef.current.length === 0) { // nothing left; don't flash the badge
      releaseSave()
      return
    }
    reorderProcessingRef.current = true
    setSyncingOrder(true)
    try {
      while (reorderQueueRef.current.length > 0) {
        // Take the whole queue. Drags that land while this batch is in flight
        // queue up for the next pass rather than being lost.
        const batch = reorderQueueRef.current
        reorderQueueRef.current = []
        // Report what's still WAITING (0 right after a take) -- the in-flight
        // batch is already covered by the "Saving order…" badge itself.
        setPendingOrderMoves(0)

        let failed = false
        try {
          const generation = projectGenerationRef.current
          await api.post('/reorder-batch', { moves: batch }, generation === null ? undefined : {
            headers: { 'X-Nucleus-Project': String(generation) },
          })
        } catch (err) {
          if (isProjectChanged(err)) {
            // Another project was opened before these moves were saved (from
            // Randall, say; Switch Project waits for them). They belonged to
            // the old project, so they are dropped rather than applied here.
            reorderQueueRef.current = []
            appAlert('Some costume moves were not saved, because another project was opened first.')
            break
          }
          console.error('Background reorder error:', err)
          failed = true
        }

        // Drags that landed while this batch was in flight go out next pass.
        setPendingOrderMoves(reorderQueueRef.current.length)

        if (failed) {
          // The batch reported failure, but in practice the moves usually did
          // reach disk (the bridge just surfaced a non-fatal MexCLI result).
          // Don't alarm the user with an error sound + popup that contradicts
          // the order they can see — drop the rest of the queue and quietly
          // reconcile every affected fighter with the real on-disk order. The
          // console.error above keeps the diagnostic trail.
          const affected = new Set(batch.map(m => m.fighter))
          reorderQueueRef.current.forEach(m => affected.add(m.fighter))
          reorderQueueRef.current = []
          setPendingOrderMoves(0)
          // The on-disk order may not match the optimistic one the selection
          // was renumbered for, so slot-keyed selections can't be trusted.
          setSelectedInstalledCostumes(new Set())
          for (const fighter of affected) {
            if (isVisibleFighter(fighter)) {
              await refreshMexCostumes(fighter)
            }
          }
          break
        }
      }
    } finally {
      reorderProcessingRef.current = false
      setSyncingOrder(false)
      setPendingOrderMoves(0)
      if (reorderQueueRef.current.length === 0) releaseSave()
    }
  }

  // Queue a drag and kick the drainer after a short debounce, so a burst of drags
  // collapses into one save. Shared by the single-fighter and Zelda/Sheik panels.
  const queueReorder = (fighter, fromIndex, toIndex) => {
    reorderQueueRef.current.push({ fighter, fromIndex, toIndex })
    holdSave()
    setPendingOrderMoves(reorderQueueRef.current.length)
    // Fixed window from the FIRST queued drag, NOT a reset-on-every-drag debounce:
    // a user dragging steadily would keep pushing a resetting timer out forever and
    // nothing would ever save. Later drags in the window ride along for free, and
    // any that land after the batch is taken go out on the drainer's next pass.
    if (reorderDebounceRef.current) return
    reorderDebounceRef.current = setTimeout(() => {
      reorderDebounceRef.current = null
      processReorderQueue()
    }, REORDER_DEBOUNCE_MS)
  }

  // Costume order lives only in memory until the batch save lands. Closing the
  // app mid-save would drop the rest of the queue AND leave disk holding a
  // partial replay -- which is neither the old order nor the new one. Warn while
  // anything is unsaved.
  useEffect(() => {
    if (!syncingOrder && pendingOrderMoves === 0) return
    const warn = (e) => {
      e.preventDefault()
      e.returnValue = ''
      return ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [syncingOrder, pendingOrderMoves])

  const handleDrop = (e, toIndex) => {
    e.preventDefault()

    if (draggedIndex === null || draggedIndex === toIndex) {
      setDraggedIndex(null)
      setDragOverIndex(null)
      return
    }

    const fromIndex = draggedIndex

    // Optimistically update the visible order -- the user never waits on the
    // slow save.
    setMexCostumes(prev => {
      const next = [...prev]
      const [movedItem] = next.splice(fromIndex, 1)
      next.splice(toIndex, 0, movedItem)
      return next
    })
    // Selection is keyed by slot: follow the moved costumes to their new slots.
    setSelectedInstalledCostumes(prev => selectionAfterMove(prev, selectedFighter.name, fromIndex, toIndex))

    // Clear drag state
    setDraggedIndex(null)
    setDragOverIndex(null)
    playSound('boop')

    // Queue the save and kick the background drainer.
    queueReorder(selectedFighter.name, fromIndex, toIndex)
  }

  const handleDragEnd = () => {
    delete document.documentElement.dataset.nucInternalDrag
    setDraggedIndex(null)
    setDragOverIndex(null)
    setDraggedRow(null)
  }

  // Pair-view drag/drop: reorder WITHIN one row (Zelda or Sheik) only --
  // cross-row drops are ignored so a Zelda costume can't land in Sheik's list.
  const handlePairDragStart = (e, fighterName, index) => {
    setDraggedRow(fighterName)
    setDraggedIndex(index)
    e.dataTransfer.effectAllowed = 'move'
    document.documentElement.dataset.nucInternalDrag = '1'
  }

  const handlePairDragEnter = (e, fighterName, index) => {
    e.preventDefault()
    setDragOverIndex(fighterName === draggedRow ? index : null)
  }

  const handlePairDrop = (e, fighterName, toIndex) => {
    e.preventDefault()
    const fromIndex = draggedIndex
    const sameRow = draggedRow === fighterName
    setDraggedIndex(null)
    setDragOverIndex(null)
    setDraggedRow(null)
    if (!sameRow || fromIndex === null || fromIndex === toIndex) {
      return
    }

    // Optimistically reorder the row -- save happens in the background.
    setPairCostumes(prev => {
      const row = [...(prev[fighterName] || [])]
      const [moved] = row.splice(fromIndex, 1)
      row.splice(toIndex, 0, moved)
      return { ...prev, [fighterName]: row }
    })
    setSelectedInstalledCostumes(prev => selectionAfterMove(prev, fighterName, fromIndex, toIndex))
    playSound('boop')

    queueReorder(fighterName, fromIndex, toIndex)
  }

  return {
    draggedIndex, dragOverIndex, syncingOrder, pendingOrderMoves, draggedRow,
    handleDragStart, handleDragOver, handleDragEnter, handleDragLeave, handleDrop,
    handleDragEnd, handlePairDragStart, handlePairDragEnter, handlePairDrop,
  }
}
