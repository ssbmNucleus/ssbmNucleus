import { useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'

/**
 * Drag-and-drop between a custom character's two grids.
 *
 * It is bidirectional: the Costumes dropzone reacts to `draggingSkinId`
 * (promote an added skin to a bundled costume) while the Custom Skins dropzone
 * reacts to `draggingCostume` (demote a bundled costume to a removable skin).
 * Dragging within a grid reorders it.
 */
export function useCostumeSkinDnd({ slug, costumes, addedSkins, onRefresh, flashSkinMessage }) {
  const [draggingCostume, setDraggingCostume] = useState(null)  // bundled costume index being dragged
  const [skinDropActive, setSkinDropActive] = useState(false)
  const [draggingSkinId, setDraggingSkinId] = useState(null)    // added skin being reordered
  const [skinDragOverId, setSkinDragOverId] = useState(null)    // added skin currently hovered (insert-before)
  const [costumeDragOverId, setCostumeDragOverId] = useState(null) // bundled costume hovered (insert-before)
  const [costumesDropActive, setCostumesDropActive] = useState(false) // skin->costume promote highlight

  const handleCostumeToSkin = async (index) => {
    setSkinDropActive(false)
    setDraggingCostume(null)
    if (index == null) return
    try {
      const data = await api.post(
        `/custom-characters/${slug}/costumes/${index}/to-skin`
      )
      playSound('newSkin')
      flashSkinMessage(`Moved ${data.skin.name} to custom skins`)
      await onRefresh()
    } catch (err) {
      flashSkinMessage(`Move failed: ${err.message}`)
    }
  }

  // Reorder added skins by drag-and-drop: move draggedId to targetId's slot.
  const handleSkinReorder = async (draggedId, targetId) => {
    setSkinDragOverId(null)
    if (!draggedId || draggedId === targetId) return
    const order = addedSkins.map(s => s.id)
    const from = order.indexOf(draggedId)
    const to = order.indexOf(targetId)
    if (from === -1 || to === -1) return
    order.splice(to, 0, order.splice(from, 1)[0])
    try {
      await api.post(`/custom-characters/${slug}/skins/reorder`, { order })
      playSound('boop'); await onRefresh()
    } catch (err) {
      flashSkinMessage(`Reorder failed: ${err.message}`)
    }
  }

  // Reorder bundled costumes by drag-and-drop (insert dragged before target).
  const handleCostumeReorder = async (draggedIndex, targetCostume) => {
    setCostumeDragOverId(null)
    const draggedStem = costumes.find(c => c.index === draggedIndex)?.edit_id
    const targetStem = targetCostume?.edit_id
    if (!draggedStem || !targetStem || draggedStem === targetStem) return
    const order = costumes.map(c => c.edit_id)
    const from = order.indexOf(draggedStem)
    const to = order.indexOf(targetStem)
    if (from === -1 || to === -1) return
    order.splice(to, 0, order.splice(from, 1)[0])
    try {
      await api.post(`/custom-characters/${slug}/costumes/reorder`, { order })
      playSound('boop'); await onRefresh()
    } catch (err) {
      flashSkinMessage(`Reorder failed: ${err.message}`)
    }
  }

  // Promote an added skin to a bundled costume (drag a custom skin up into Costumes).
  const handleSkinToCostume = async (skinId) => {
    setCostumesDropActive(false)
    if (!skinId) return
    try {
      await api.post(
        `/custom-characters/${slug}/skins/${skinId}/to-costume`)
      playSound('newSkin')
      flashSkinMessage('Promoted skin to a costume')
      await onRefresh()
    } catch (err) {
      flashSkinMessage(`Promote failed: ${err.message}`)
    }
  }

  return {
    draggingCostume, setDraggingCostume,
    skinDropActive, setSkinDropActive,
    draggingSkinId, setDraggingSkinId,
    skinDragOverId, setSkinDragOverId,
    costumeDragOverId, setCostumeDragOverId,
    costumesDropActive, setCostumesDropActive,
    handleCostumeToSkin,
    handleSkinReorder,
    handleCostumeReorder,
    handleSkinToCostume,
  }
}
