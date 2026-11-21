/**
 * useCustomStages - custom stage vault/project state and logic for StageMode
 *
 * Covers: vault + in-project custom stage fetching, batch selection,
 * batch install (with auto SSS grid layout), and removal from project.
 */
import { useState, useEffect } from 'react'
import { channel } from '../../shared/transport/socket'
import { appConfirm } from '../../shared/ui/appDialogs'
import { api } from '../../shared/transport/api'
import { pruneSelection } from './pruneSelection'


export default function useCustomStages({ onRefresh }) {
  const [vaultStages, setVaultStages] = useState([])
  const [projectCustomStages, setProjectCustomStages] = useState([])
  const [addingStage, setAddingStage] = useState(null)
  const [selectedCustomStages, setSelectedCustomStages] = useState(new Set())
  const [selectedInstalledCustomStages, setSelectedInstalledCustomStages] = useState(new Set())
  const [batchInstallingStages, setBatchInstallingStages] = useState(false)
  const [removingCustomStages, setRemovingCustomStages] = useState(false)
  const [batchStageProgress, setBatchStageProgress] = useState({ current: 0, total: 0 })

  useEffect(() => {
    fetchCustomStagesData()
  }, [])

  const fetchCustomStagesData = async () => {
    // Each list is independent: one endpoint failing must not blank the other.
    const [vault, project] = await Promise.allSettled([
      api.get('/custom-stages/list'),
      api.get('/custom-stages/in-project')
    ])
    // On success, also drop selections for stages that no longer exist.
    if (vault.status === 'fulfilled') {
      const stages = vault.value.stages || []
      setVaultStages(stages)
      const slugs = new Set(stages.map(stage => stage.slug))
      setSelectedCustomStages(prev => pruneSelection(prev, slug => slugs.has(slug)))
    } else console.error('Failed to fetch custom stages:', vault.reason)
    if (project.status === 'fulfilled') {
      const stages = project.value.stages || []
      setProjectCustomStages(stages)
      const names = new Set(stages.map(stage => stage.name))
      setSelectedInstalledCustomStages(prev => pruneSelection(prev, name => names.has(name)))
    } else console.error('Failed to fetch custom stages:', project.reason)
  }

  const toggleCustomStageSelection = (slug) => {
    setSelectedCustomStages(prev => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  const selectAllCustomStages = () => {
    setSelectedCustomStages(prev => {
      const next = new Set(prev)
      vaultStages.forEach(stage => next.add(stage.slug))
      return next
    })
  }

  const clearCustomStageSelection = () => {
    setSelectedCustomStages(new Set())
  }

  const toggleInstalledCustomStageSelection = (stageName) => {
    setSelectedInstalledCustomStages(prev => {
      const next = new Set(prev)
      if (next.has(stageName)) next.delete(stageName)
      else next.add(stageName)
      return next
    })
  }

  const selectAllInstalledCustomStages = () => {
    setSelectedInstalledCustomStages(prev => {
      const next = new Set(prev)
      projectCustomStages.forEach(stage => next.add(stage.name))
      return next
    })
  }

  const clearInstalledCustomStageSelection = () => {
    setSelectedInstalledCustomStages(new Set())
  }

  const autoApplySssGrid = async () => {
    try {
      const data = await api.get('/menus/sss/layout')
      if (!data.pages) return
      // Apply grid to each page that has icons
      const cols = 6
      const baseW = 5.95, baseH = 5.21, spacingX = 0.8, spacingY = 0.6, centerX = 0, centerY = 5.5
      const updatedPages = data.pages.map((page, pageIdx) => {
        if (pageIdx === 0) return page // leave vanilla page untouched
        const icons = page.icons || []
        if (icons.length === 0) return page
        const rows = Math.ceil(icons.length / cols)
        const sx = 1.0, sy = 1.0
        const iw = baseW + spacingX, ih = baseH + spacingY
        const totalW = Math.min(icons.length, cols) * iw - spacingX, totalH = rows * ih - spacingY
        const gridIcons = icons.map((icon, i) => {
          const col = i % cols, row = Math.floor(i / cols)
          return { ...icon, x: centerX - totalW / 2 + iw * col + baseW / 2, y: centerY + totalH / 2 - ih * row - baseH / 2, z: 0, scaleX: sx, scaleY: sy }
        })
        return { ...page, icons: gridIcons }
      })
      await api.post('/menus/sss/layout', { pages: updatedPages })
    } catch (err) {
      console.error('Auto SSS grid failed:', err)
    }
  }

  const handleBatchInstallStages = () => installStages([...selectedCustomStages])

  // Single-stage entry point used by the More Stages slot panel ("Add as new
  // stage"): same batch route + SSS re-fit, one slug.
  const handleInstallCustomStage = (slug) => installStages([slug])

  const installStages = async (slugs) => {
    if (slugs.length === 0 || batchInstallingStages) return
    setBatchInstallingStages(true)
    setBatchStageProgress({ current: 0, total: slugs.length })
    // Live progress via SocketIO so the bar moves instead of sitting at 0/N
    // (single synchronous request otherwise).
    const socket = channel()
    socket.on('custom_stage_install_progress', (d) => {
      setBatchStageProgress({
        current: d.current ?? 0,
        total: d.total ?? slugs.length,
        message: d.message || null,
        name: d.name || null,
      })
    })
    // ONE batch call: the backend folds add-stage + per-track add-music +
    // set-stage-playlist for every selected stage into a single workspace recompile
    // (~Nx faster than /install per stage). Output is byte-identical to the per-stage
    // path.
    try {
      const data = await api.post('/custom-stages/install-batch', { slugs })
      if (data.failed?.length) console.warn('Some stages failed to install:', data.failed)
      if (data.warnings?.length) console.warn('Install warnings:', data.warnings)
      setBatchStageProgress({ current: slugs.length, total: slugs.length })
    } catch (err) {
      console.error('Batch stage install error:', err)
      alert(err.message || 'Failed to add stages')
    } finally {
      socket.disconnect()
    }
    // Re-fit the SSS grid to the new roster (places the new stages on the
    // stage-select grid), same step the per-stage path ran.
    await autoApplySssGrid()
    setBatchInstallingStages(false)
    setSelectedCustomStages(new Set())
    await fetchCustomStagesData()
    onRefresh()
  }

  const removeCustomStageFromProject = async (stageName) => {
    try {
      return await api.post('/custom-stages/remove-from-project', { name: stageName })
    } catch (err) {
      throw new Error(err.message || 'Failed to remove stage')
    }
  }

  const handleRemoveCustomStage = async (stageName) => {
    if (!await appConfirm(`Remove "${stageName}" from the project?`, {
      title: 'Remove Custom Stage',
      confirmText: 'Remove',
    })) return
    try {
      await removeCustomStageFromProject(stageName)
      setSelectedInstalledCustomStages(prev => {
        const next = new Set(prev)
        next.delete(stageName)
        return next
      })
      await fetchCustomStagesData()
      onRefresh()
    } catch (err) {
      alert(`Error: ${err.message}`)
    }
  }

  const handleBatchRemoveCustomStages = async () => {
    const names = [...selectedInstalledCustomStages]
    if (names.length === 0 || removingCustomStages) return
    if (!await appConfirm(`Remove ${names.length} selected custom stage(s) from the project?`, {
      title: 'Remove Selected Stages',
      confirmText: 'Remove',
    })) return

    setRemovingCustomStages(true)
    let successCount = 0
    let failCount = 0

    // ONE batch call: removes every selected stage in a single workspace recompile
    // (~Nx faster than /remove-from-project per stage, same final stage set).
    try {
      const data = await api.post('/custom-stages/remove-batch', { names })
      successCount = data.totalRemoved ?? names.length
      failCount = data.totalFailed ?? 0
    } catch (err) {
      failCount = names.length
      console.error('Batch stage remove error:', err)
    }

    setRemovingCustomStages(false)
    setSelectedInstalledCustomStages(new Set())
    await fetchCustomStagesData()
    onRefresh()

    if (failCount > 0) {
      alert(`Batch remove completed:\n${successCount} removed, ${failCount} failed`)
    }
  }

  return {
    vaultStages,
    projectCustomStages,
    addingStage,
    setAddingStage,
    selectedCustomStages,
    selectedInstalledCustomStages,
    batchInstallingStages,
    removingCustomStages,
    batchStageProgress,
    fetchCustomStagesData,
    toggleCustomStageSelection,
    selectAllCustomStages,
    clearCustomStageSelection,
    toggleInstalledCustomStageSelection,
    selectAllInstalledCustomStages,
    clearInstalledCustomStageSelection,
    handleBatchInstallStages,
    handleInstallCustomStage,
    handleRemoveCustomStage,
    handleBatchRemoveCustomStages
  }
}
