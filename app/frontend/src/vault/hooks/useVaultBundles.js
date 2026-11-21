import { useState } from 'react'
import { API_URL, backendMediaUrl } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'

/**
 * `.ssbm` bundle actions on the Patches grid: download, rename/describe,
 * re-image, delete, and install (build the ISO and hand it to Slippi).
 *
 * Owns only the edit-modal state. Install progress is NOT owned here: the
 * install is a `bundle_install` job that useXdeltaPatches follows, so the
 * shared import modal shows its progress and outcome.
 *
 * @param fetchBundles  refresh the grid after a mutation
 * @param openImportModal  show the shared progress modal
 * @param installBundle  start the install job (useXdeltaPatches)
 */
export function useVaultBundles({ fetchBundles, openImportModal, installBundle }) {
  const [showBundleEditModal, setShowBundleEditModal] = useState(false)
  const [editingBundle, setEditingBundle] = useState(null)

  const handleDownloadBundle = (bundleId) => {
    const link = document.createElement('a')
    link.href = backendMediaUrl(`${API_URL}/bundle/download/${bundleId}`)
    // Without `download` a click is a navigation, which the Electron shell
    // blocks for the backend origin (will-navigate), so nothing downloads.
    link.download = '' // keep the filename supplied by Content-Disposition
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const handleEditBundle = (bundle) => {
    setEditingBundle(bundle)
    setShowBundleEditModal(true)
  }

  const handleSaveBundleEdit = async () => {
    if (!editingBundle) return

    try {
      await api.post(`/bundle/update/${editingBundle.id}`, {
        name: editingBundle.name,
        description: editingBundle.description
      })
      fetchBundles()
      setShowBundleEditModal(false)
      setEditingBundle(null)
    } catch (err) {
      // err.data => the backend reported the failure itself (old else branch)
      alert(err.data ? `Failed to save bundle: ${err.message}` : `Error saving bundle: ${err.message}`)
    }
  }

  const handleUpdateBundleImage = async (e) => {
    const file = e.target.files?.[0]
    if (!file || !editingBundle) return

    const formData = new FormData()
    formData.append('image', file)

    try {
      const data = await api.post(`/bundle/update-image/${editingBundle.id}`, formData)
      setEditingBundle({ ...editingBundle, imageUrl: data.imageUrl })
      fetchBundles()
    } catch (err) {
      // err.data => the backend reported the failure itself (old else branch)
      alert(err.data ? `Failed to update image: ${err.message}` : `Error updating image: ${err.message}`)
    }
  }

  const handleDeleteBundle = async (bundleId) => {
    try {
      await api.post(`/bundle/delete/${bundleId}`)
      fetchBundles()
    } catch (err) {
      // err.data => the backend reported the failure itself (old else branch)
      alert(err.data ? `Failed to delete bundle: ${err.message}` : `Error deleting bundle: ${err.message}`)
    }
  }

  const handleInstallBundle = async (bundle) => {
    const slippiPath = localStorage.getItem('slippi_dolphin_path')
    const vanillaIsoPath = localStorage.getItem('vanilla_iso_path')

    if (!slippiPath) {
      alert('Slippi Dolphin path not set. Please configure it in Settings.')
      return
    }

    if (!vanillaIsoPath) {
      alert('Vanilla ISO path not set. Please configure it in Settings.')
      return
    }

    // Show the import modal for progress display
    openImportModal()
    await installBundle(bundle.id, { slippiPath, vanillaIsoPath })
  }

  return {
    showBundleEditModal,
    setShowBundleEditModal,
    editingBundle,
    setEditingBundle,
    handleDownloadBundle,
    handleEditBundle,
    handleSaveBundleEdit,
    handleUpdateBundleImage,
    handleDeleteBundle,
    handleInstallBundle,
  }
}

export default useVaultBundles
