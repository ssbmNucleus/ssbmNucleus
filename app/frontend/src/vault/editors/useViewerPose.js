import { useRef, useState } from 'react'
import { api } from '../../shared/transport/api'

// Poses for the paint viewer. Custom characters can start the viewer on a
// saved pose: this holds the pose list, the character's default and the
// selected pose, and resolves the scene file and animation to start on
// (activeStartPoseRef). Vanilla characters have no poses.
export function useViewerPose() {
  const [poseOptions, setPoseOptions] = useState([])
  const [selectedPoseName, setSelectedPoseName] = useState('')
  const [defaultPoseName, setDefaultPoseName] = useState('')
  const activeStartPoseRef = useRef(null)

  const customCharacterSlugFromKey = (key) => {
    const match = typeof key === 'string'
      ? key.match(/^custom_characters\/([^/]+)\/(?:skins|costumes)$/)
      : null
    return match?.[1] || null
  }

  const getPoseCharacterKey = (key) => {
    const slug = customCharacterSlugFromKey(key)
    return slug ? `custom_characters/${slug}/costumes` : key
  }

  const resolveViewerPose = async (characterKey, requestedPoseName) => {
    const slug = customCharacterSlugFromKey(characterKey)
    if (!slug) {
      activeStartPoseRef.current = null
      setPoseOptions([])
      setSelectedPoseName('')
      setDefaultPoseName('')
      return null
    }

    const poseCharacter = getPoseCharacterKey(characterKey)
    let defaultPose = ''
    let poses = []

    // Independent lookups: a failed detail read must not also drop the pose list.
    const [detail, posesRes] = await Promise.allSettled([
      api.get(`/custom-characters/${slug}/detail`),
      api.get(`/storage/poses/list/${encodeURIComponent(poseCharacter)}`)
    ])
    if (detail.status === 'fulfilled') defaultPose = detail.value.detail?.default_pose || ''
    else console.error('[SkinCreator] Failed to load custom character detail:', detail.reason)
    if (posesRes.status === 'fulfilled') poses = posesRes.value.poses || []
    else console.error('[SkinCreator] Failed to load custom character poses:', posesRes.reason)

    setDefaultPoseName(defaultPose)
    setPoseOptions(poses)

    const hasPose = (name) => Boolean(name) && poses.some(pose => pose.name === name)
    const poseName = requestedPoseName !== undefined
      ? requestedPoseName
      : (hasPose(selectedPoseName) ? selectedPoseName : defaultPose)
    setSelectedPoseName(poseName || '')

    if (!poseName) {
      activeStartPoseRef.current = null
      return null
    }

    try {
      const sceneData = await api.get(
        `/api/mex/storage/poses/scene-file/${encodeURIComponent(poseCharacter)}/${encodeURIComponent(poseName)}`
      )
      const pose = {
        name: poseName,
        sceneFile: sceneData.sceneFile,
        animSymbol: sceneData.animSymbol,
        frame: sceneData.frame || 0
      }
      activeStartPoseRef.current = pose
      return pose
    } catch (err) {
      console.error('[SkinCreator] Failed to apply pose:', err)
      activeStartPoseRef.current = null
      return null
    }
  }

  return { poseOptions, selectedPoseName, setSelectedPoseName, defaultPoseName, activeStartPoseRef, resolveViewerPose }
}
