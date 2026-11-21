/**
 * useCustomCharacters - add-character modal state and custom fighter
 * install/remove logic for CharacterMode.
 */
import { useState } from 'react'
import { channel } from '../../shared/transport/socket'
import { computeAutoCssLayout } from '../menus/cssGridLayout'
import { appConfirm } from '../../shared/ui/appDialogs'
import { api } from '../../shared/transport/api'


export default function useCustomCharacters({ onRefresh }) {
  // Add character modal state
  const [showAddCharacterModal, setShowAddCharacterModal] = useState(false)
  const [vaultCharacters, setVaultCharacters] = useState([])
  const [addingCharacter, setAddingCharacter] = useState(null)
  const [selectedVaultChars, setSelectedVaultChars] = useState(new Set())
  const [batchAddingChars, setBatchAddingChars] = useState(false)
  const [batchCharProgress, setBatchCharProgress] = useState({ current: 0, total: 0 })

  const [removingFighter, setRemovingFighter] = useState(false)
  const [removingFighterName, setRemovingFighterName] = useState('')

  const openAddCharacterModal = async () => {
    setShowAddCharacterModal(true)
    try {
      const data = await api.get('/custom-characters/list')
      setVaultCharacters(data.characters || [])
    } catch (err) {
      console.error('Failed to fetch vault characters:', err)
    }
  }

  const toggleVaultCharSelection = (slug) => {
    setSelectedVaultChars(prev => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  // Re-fit the character select grid to the new roster: auto-pick
  // columns/rows for the icon count and re-center every row (the old inline
  // version kept the column count fixed and left partial rows off-center).
  // L-load alternates' tucked icons take no slot; the backend re-tucks them.
  const autoApplyCssGrid = async () => {
    try {
      const data = await api.get('/menus/css/layout')
      const { icons, template } = data
      if (!icons || !template || icons.length === 0) return
      await api.post('/menus/css/layout',
        computeAutoCssLayout(icons, template, data.lload?.altExternalIds || []))
    } catch (err) {
      console.error('Auto CSS grid failed:', err)
    }
  }

  const handleBatchAddCharacters = async () => {
    const slugs = [...selectedVaultChars]
    if (slugs.length === 0) return
    setBatchAddingChars(true)
    setBatchCharProgress({ current: 0, total: slugs.length })
    // Live progress: the backend streams 'custom_char_install_progress' as it
    // prepares each fighter and then compiles, so the bar moves instead of
    // sitting at 0/N (it's a single synchronous request otherwise).
    const socket = channel()
    socket.on('custom_char_install_progress', (d) => {
      setBatchCharProgress({
        current: d.current ?? 0,
        total: d.total ?? slugs.length,
        message: d.message || null,
        name: d.name || null,
      })
    })
    // ONE batch call: the backend folds add-fighter + victory + announcer for every
    // selected character into a single workspace recompile (~Nx faster than calling
    // /install per char, which re-recompiled ~4x each).
    try {
      const data = await api.post('/custom-characters/install-batch', { slugs })
      if (data.failed?.length) console.warn('Some characters failed to install:', data.failed)
      if (data.warnings?.length) console.warn('Install warnings:', data.warnings)
      setBatchCharProgress({ current: slugs.length, total: slugs.length })
    } catch (err) {
      console.error('Batch character install error:', err)
      alert(err.message || 'Failed to add characters')
    } finally {
      socket.disconnect()
    }
    // Re-fit the CSS grid to the new roster -- this is what places the newly added
    // fighters on the character-select grid (same step the per-char path ran).
    await autoApplyCssGrid()
    setBatchAddingChars(false)
    setSelectedVaultChars(new Set())
    setShowAddCharacterModal(false)
    onRefresh()
  }

  const handleRemoveFighter = async (fighterName) => {
    if (!await appConfirm(`Remove "${fighterName}" from the project?`, {
      title: 'Remove Character',
      confirmText: 'Remove',
    })) return
    setRemovingFighter(true)
    setRemovingFighterName(fighterName)
    try {
      await api.post('/custom-characters/remove-from-project', { name: fighterName })
      // Removing a fighter leaves a gap in the select-screen grid; re-fit it
      await autoApplyCssGrid()
      onRefresh()
    } catch (err) {
      alert(err.message || 'Failed to remove fighter')
    } finally {
      setRemovingFighter(false)
      setRemovingFighterName('')
    }
  }

  return {
    showAddCharacterModal,
    setShowAddCharacterModal,
    vaultCharacters,
    addingCharacter,
    setAddingCharacter,
    selectedVaultChars,
    setSelectedVaultChars,
    batchAddingChars,
    batchCharProgress,
    removingFighter,
    removingFighterName,
    openAddCharacterModal,
    toggleVaultCharSelection,
    handleBatchAddCharacters,
    handleRemoveFighter
  }
}
