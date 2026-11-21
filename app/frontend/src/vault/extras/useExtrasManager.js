import { useState, useEffect, useCallback } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'

/**
 * useExtrasManager - State + API logic for the character extras page.
 * Owns the extras list fetch, type selection, editor modal state, and the
 * delete/save handlers. Importing an effect file is the vault's floating
 * Import button (auto-detected); `refreshKey` is bumped when one lands here.
 */
export default function useExtrasManager({ character, onRefresh, refreshKey = 0 }) {
  const [selectedType, setSelectedType] = useState(null)
  const [extras, setExtras] = useState({})
  const [loading, setLoading] = useState(true)
  const [showEditor, setShowEditor] = useState(false)
  const [editingMod, setEditingMod] = useState(null)

  // Fetch extras for this character
  const fetchExtras = useCallback(async () => {
    if (!character) return
    setLoading(true)

    try {
      const data = await api.get(`/storage/extras/list/${character}`)
      setExtras(data.extras || {})
    } catch (err) {
      console.error('[ExtrasPageView] Fetch error:', err)
      setExtras({})
    } finally {
      setLoading(false)
    }
  }, [character])

  useEffect(() => {
    fetchExtras()
  }, [fetchExtras, refreshKey])

  const handleRefresh = () => {
    fetchExtras()
    onRefresh?.()
  }

  const handleCreateNew = () => {
    setEditingMod(null)
    setShowEditor(true)
  }

  const handleEdit = (mod) => {
    setEditingMod(mod)
    setShowEditor(true)
  }

  const handleDelete = () => {
    handleRefresh()
  }

  const handleEditorClose = () => {
    playSound('back')
    setShowEditor(false)
    setEditingMod(null)
  }

  const handleSave = () => {
    handleRefresh()
  }

  return {
    selectedType,
    setSelectedType,
    extras,
    loading,
    showEditor,
    editingMod,
    handleCreateNew,
    handleEdit,
    handleDelete,
    handleEditorClose,
    handleSave
  }
}
