/**
 * useApplyPose - "Pose" button on the install page (CostumesPanel).
 *
 * Opens the pose manager for the selected fighter; picking a pose applies it
 * to EVERY in-ISO costume: the backend matches each costume back to its
 * vault skin, reuses that skin's existing render of the pose, or renders it
 * now (saving it to the vault as an alternate CSP), then overwrites the
 * project portrait. A final recompile pass refreshes the .tex files the ISO
 * export reads.
 */
import { useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'

export default function useApplyPose({ selectedFighter, refreshCostumes }) {
  const [showPoseModal, setShowPoseModal] = useState(false)
  // Vault character key for the modal/backend: the fighter name for
  // canonical characters, the custom-character pseudo key otherwise
  const [poseCharacter, setPoseCharacter] = useState(null)
  const [poseBaseSkinId, setPoseBaseSkinId] = useState(null)
  // The fighter the pose targets. Usually the selected fighter, but the
  // Zelda/Sheik split panel poses one half at a time, so it passes the
  // specific fighter to openPoseModal.
  const [poseFighter, setPoseFighter] = useState(null)
  const [pendingPose, setPendingPose] = useState(null)
  const [applying, setApplying] = useState(false)
  const [applyingPose, setApplyingPose] = useState(null)
  const [applyProgress, setApplyProgress] = useState({ current: 0, total: 0 })

  const openPoseModal = async (fighterArg) => {
    const fighter = fighterArg || selectedFighter
    if (!fighter) return
    let character = fighter.name
    let baseSkinId = null
    // Custom fighters keep their poses and skins under a pseudo vault key
    if (fighter.isMexFighter) {
      try {
        const data = await api.get('/custom-characters/list')
        const entry = (data.characters || []).find(c => c.name === fighter.name)
        if (entry) {
          character = `custom_characters/${entry.slug}/costumes`
          // The create-pose viewer needs a vault skin to load the model from
          const skinsData = await api.get('/storage/costumes', { query: { character } })
          baseSkinId = skinsData.costumes?.[0]?.folder || null
        }
      } catch (err) {
        console.warn('Custom character lookup failed, using fighter name:', err)
      }
    }
    setPoseFighter(fighter)
    setPoseCharacter(character)
    setPoseBaseSkinId(baseSkinId)
    setShowPoseModal(true)
  }

  // Pose picked in the manager -> close it and ask for confirmation
  const handlePoseSelected = (pose) => {
    playSound('boop')
    setShowPoseModal(false)
    setPendingPose(pose)
  }

  const confirmApplyPose = async () => {
    const pose = pendingPose
    const fighter = poseFighter || selectedFighter
    setPendingPose(null)
    if (!pose || !fighter) return

    setApplying(true)
    setApplyingPose(pose)
    setApplyProgress({ current: 0, total: 0 })
    let applied = 0
    let generatedCount = 0
    let skipped = 0
    let failed = 0

    try {
      // 1. Match in-ISO costumes to vault skins
      let mapData
      try {
        mapData = await api.post('/storage/poses/project-costume-map', {
          fighter: fighter.name,
          character: poseCharacter
        })
      } catch (err) {
        throw new Error(err.message || 'Failed to map costumes')
      }

      const entries = mapData.costumes || []
      setApplyProgress({ current: 0, total: entries.length })

      // 2. Apply per costume (one request each so progress is real — a
      //    missing render takes seconds to generate)
      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i]
        setApplyProgress({ current: i + 1, total: entries.length })
        if (!entry.skinId && !entry.vanillaCode) {
          console.warn(`No vault skin or vanilla costume matched for "${entry.name}" (${entry.fileName})`)
          skipped++
          continue
        }
        try {
          const data = await api.post('/storage/poses/apply-to-costume', {
            character: entry.skinCharacter,
            skinId: entry.skinId,
            vanillaCode: entry.vanillaCode,
            poseName: pose.name,
            cspAsset: entry.cspAsset,
            fileName: entry.fileName
          })
          if (data.status === 'no_csp_asset') {
            skipped++
          } else {
            applied++
            if (data.generated) generatedCount++
          }
        } catch (err) {
          console.error(`Apply pose error for "${entry.name}":`, err)
          failed++
        }
      }

      // 3. Recompile the .tex files the ISO export actually reads
      if (applied > 0) {
        try {
          await api.post('/storage/poses/apply-finish')
        } catch (err) {
          // was fire-and-forget: a backend error here must not void the
          // costumes already applied; only a transport failure propagates
          if (!err.data) throw err
          console.error('apply-finish failed:', err)
        }
      }

      playSound(applied > 0 ? 'camera' : 'error')
      console.log(`✓ Pose "${pose.name}": ${applied} applied (${generatedCount} rendered), ${skipped} skipped, ${failed} failed`)
      if (skipped > 0 || failed > 0) {
        alert(`Pose applied to ${applied} costume(s).` +
          (skipped > 0 ? `\n${skipped} skipped (no matching vault skin).` : '') +
          (failed > 0 ? `\n${failed} failed — see console.` : ''))
      }

      await refreshCostumes(fighter.name)
    } catch (err) {
      console.error('Apply pose error:', err)
      playSound('error')
      alert(`Apply pose failed: ${err.message}`)
    } finally {
      setApplying(false)
      setApplyingPose(null)
    }
  }

  return {
    showPoseModal,
    setShowPoseModal,
    poseCharacter,
    poseBaseSkinId,
    poseFighter,
    pendingPose,
    setPendingPose,
    applying,
    applyingPose,
    applyProgress,
    openPoseModal,
    handlePoseSelected,
    confirmApplyPose
  }
}
