import { useState, useEffect, useCallback } from 'react'
import { playSound } from '../../../shared/audio/sounds'
import { api } from '../../../shared/transport/api'

/**
 * Pose list management + save/delete API calls for the Pose Manager.
 */
export default function usePoseLibrary({ show, character, viewerRef }) {
  const [poseName, setPoseName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [poses, setPoses] = useState([])
  const [loadingPoses, setLoadingPoses] = useState(true)
  const [selectedPose, setSelectedPose] = useState(null) // For skin selector modal

  // Fetch saved poses
  const fetchPoses = useCallback(async () => {
    if (!character) return
    try {
      const data = await api.get(`/storage/poses/list/${character}`)
      setPoses(data.poses)
    } catch (err) {
      console.error('[PoseManager] Fetch poses error:', err)
    } finally {
      setLoadingPoses(false)
    }
  }, [character])

  useEffect(() => {
    if (show) {
      fetchPoses()
    }
  }, [show, fetchPoses])

  const handleSavePose = async () => {
    if (!poseName.trim()) {
      setSaveError('Please enter a pose name')
      return
    }

    if (!viewerRef.current) {
      setSaveError('Viewer not ready')
      return
    }

    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)

    try {
      // Export scene from viewer
      const sceneData = await viewerRef.current.exportScene()
      if (!sceneData) {
        throw new Error('Failed to export scene data')
      }
      // No client-side animation guard: a pose is valid either with a picked
      // AJ animation OR with a scene-mode character's baked pose (no symbol).
      // The backend decides and returns a clear error for the bind-pose case.

      // Save pose via API
      await api.post('/storage/poses/save', {
        character,
        poseName: poseName.trim(),
        sceneData
      })

      playSound('camera')
      setSaveSuccess(true)
      setPoseName('')

      // Refresh poses list to show new thumbnail
      await fetchPoses()

      // Clear success message after 3 seconds
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (err) {
      console.error('[PoseManager] Save error:', err)
      setSaveError(err.message || 'Failed to save pose')
    } finally {
      setSaving(false)
    }
  }

  const handleDeletePose = (poseName) => {
    setPoses(poses.filter(p => p.name !== poseName))
  }

  return {
    poseName,
    setPoseName,
    saving,
    saveError,
    saveSuccess,
    poses,
    loadingPoses,
    selectedPose,
    setSelectedPose,
    handleSavePose,
    handleDeletePose
  }
}
