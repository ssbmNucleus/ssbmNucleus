import { useState, useEffect } from 'react'
import { api } from '../../shared/transport/api'

/**
 * useVaultContextMenu - right-click menu for vault skins / stage variants,
 * plus the move-to-top / move-to-bottom reorder actions it offers.
 *
 * `setReordering` comes from useDragAndDrop, so this hook has to be called
 * after it.
 */
export function useVaultContextMenu({ selectedCharacter, selectedStage, onRefresh, fetchStageVariants, setReordering }) {
  const [contextMenu, setContextMenu] = useState(null) // { x, y, type: 'skin'/'variant', item, index }

  // Context menu handlers
  const handleSkinContextMenu = (e, skin, index) => {
    e.preventDefault()
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      type: 'skin',
      item: skin,
      index
    })
  }

  const handleVariantContextMenu = (e, variant, index) => {
    e.preventDefault()
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      type: 'variant',
      item: variant,
      index
    })
  }

  const handleMoveToTop = async () => {
    if (!contextMenu) return

    setReordering(true)

    try {
      const endpoint = contextMenu.type === 'skin'
        ? '/api/mex/storage/costumes/move-to-top'
        : '/api/mex/storage/stages/move-to-top'

      const body = contextMenu.type === 'skin'
        ? {
            character: selectedCharacter,
            skinId: contextMenu.item.id
          }
        : {
            stageFolder: selectedStage.folder,
            variantId: contextMenu.item.id
          }

      await api.post(endpoint, body)

      // Refresh data
      if (contextMenu.type === 'skin') {
        await onRefresh()
      } else {
        await fetchStageVariants()
        await onRefresh()
      }
    } catch (err) {
      console.error('Move to top error:', err)
      // err.data => the backend reported the failure itself (old else branch)
      alert(err.data ? `Move to top failed: ${err.message}` : `Move to top error: ${err.message}`)
    } finally {
      setReordering(false)
      setContextMenu(null)
    }
  }

  const handleMoveToBottom = async () => {
    if (!contextMenu) return

    setReordering(true)

    try {
      const endpoint = contextMenu.type === 'skin'
        ? '/api/mex/storage/costumes/move-to-bottom'
        : '/api/mex/storage/stages/move-to-bottom'

      const body = contextMenu.type === 'skin'
        ? {
            character: selectedCharacter,
            skinId: contextMenu.item.id
          }
        : {
            stageFolder: selectedStage.folder,
            variantId: contextMenu.item.id
          }

      await api.post(endpoint, body)

      // Refresh data
      if (contextMenu.type === 'skin') {
        await onRefresh()
      } else {
        await fetchStageVariants()
        await onRefresh()
      }
    } catch (err) {
      console.error('Move to bottom error:', err)
      // err.data => the backend reported the failure itself (old else branch)
      alert(err.data ? `Move to bottom failed: ${err.message}` : `Move to bottom error: ${err.message}`)
    } finally {
      setReordering(false)
      setContextMenu(null)
    }
  }

  const closeContextMenu = () => {
    setContextMenu(null)
  }

  // Click-outside listener for context menu
  useEffect(() => {
    if (contextMenu) {
      const handleClick = () => closeContextMenu()
      document.addEventListener('click', handleClick)
      return () => document.removeEventListener('click', handleClick)
    }
  }, [contextMenu])

  return {
    contextMenu,
    handleSkinContextMenu,
    handleVariantContextMenu,
    handleMoveToTop,
    handleMoveToBottom,
    closeContextMenu
  }
}
