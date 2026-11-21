/**
 * useStageVariants - DAS (Dynamic Alternate Stages) state and logic for StageMode
 *
 * Covers: DAS install check/install, storage + MEX variant fetching,
 * single/batch import, removal (with confirm dialog), button token
 * assignment/removal via rename, and available-variant selection.
 */
import { useState, useEffect, useRef } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { appAlert, appConfirm } from '../../shared/ui/appDialogs'
import { BACKEND_URL } from '../../shared/config/config'
import { api } from '../../shared/transport/api'
import { pruneSelection } from './pruneSelection'
import {
  summarizeTransformFixResults
} from './stadiumTransformFix'
import { DAS_NOTICE_TITLE, dasInstallNotice } from './dasInstall'

export const DAS_STAGES = [
  { code: 'GrOp', name: 'Dreamland', folder: 'dreamland', vanillaImage: `${BACKEND_URL}/vanilla/stages/dreamland.png` },
  { code: 'GrPs', name: 'Pokemon Stadium', folder: 'pokemon_stadium', vanillaImage: `${BACKEND_URL}/vanilla/stages/pokemon stadium.png` },
  { code: 'GrSt', name: "Yoshi's Story", folder: 'yoshis_story', vanillaImage: `${BACKEND_URL}/vanilla/stages/yoshis story.png` },
  { code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', vanillaImage: `${BACKEND_URL}/vanilla/stages/battlefield.png` },
  { code: 'GrIz', name: 'Fountain of Dreams', folder: 'fountain_of_dreams', vanillaImage: `${BACKEND_URL}/vanilla/stages/fountain of dreams.png` },
  { code: 'GrNLa', name: 'Final Destination', folder: 'final_destination', vanillaImage: `${BACKEND_URL}/vanilla/stages/final destination.png` }
]

const BUTTON_TOKEN_REGEX = /\s*\(([ABXYLRZ])\)$/i

function normalizeWhitespace(name) {
  return name.replace(/\s+/g, ' ').trim()
}

function toProjectVariantBaseName(name) {
  const words = normalizeWhitespace(name)
    .match(/[A-Za-z0-9]+/g)

  if (!words || words.length === 0) {
    return normalizeWhitespace(name).replace(/\s+/g, '')
  }

  return words.map(word => word.charAt(0).toUpperCase() + word.slice(1)).join('')
}

function stripButtonIndicator(name) {
  return normalizeWhitespace(name.replace(BUTTON_TOKEN_REGEX, ''))
}

function addButtonIndicator(name, button) {
  return `${toProjectVariantBaseName(stripButtonIndicator(name))}(${button})`
}

function normalizeProjectVariantName(name) {
  const normalized = normalizeWhitespace(name)
  const match = normalized.match(BUTTON_TOKEN_REGEX)
  const baseName = toProjectVariantBaseName(stripButtonIndicator(normalized))

  if (match) {
    return `${baseName}(${match[1].toUpperCase()})`
  }

  return baseName
}

export default function useStageVariants({ onRefresh }) {
  const [dasInstalled, setDasInstalled] = useState(false)
  // Stages set up without a loader (their install found no vanilla source):
  // the Stages tab offers the install again for them.
  const [dasMissingStages, setDasMissingStages] = useState([])
  const [dasChecking, setDasChecking] = useState(false)
  const [selectedStage, setSelectedStage] = useState(null)
  const [storageVariants, setStorageVariants] = useState([])
  const [mexVariants, setMexVariants] = useState([])
  const [mexVariantCounts, setMexVariantCounts] = useState({})
  const [selectedVariants, setSelectedVariants] = useState(new Set())
  const [selectedInstalledVariants, setSelectedInstalledVariants] = useState(new Set())
  const [selectedButton, setSelectedButton] = useState(null)
  const [importing, setImporting] = useState(false)
  const [importingCostume, setImportingCostume] = useState(null)
  const [removing, setRemoving] = useState(false)
  const [restoringVanilla, setRestoringVanilla] = useState(false)
  const [batchImporting, setBatchImporting] = useState(false)
  const [batchProgress, setBatchProgress] = useState({ current: 0, total: 0 })
  const [dataReady, setDataReady] = useState(false)
  const [transformFixNotice, setTransformFixNotice] = useState(null)

  // Confirm dialog state for removing variants
  const [showConfirmDialog, setShowConfirmDialog] = useState(false)
  const [pendingRemoval, setPendingRemoval] = useState(null)

  // Ref for scrolling Available to Import list to top on stage change
  const availableListRef = useRef(null)

  useEffect(() => {
    checkDASInstallation()
    fetchStorageVariants()
    fetchAllMexVariantCounts()
  }, [])

  useEffect(() => {
    // Custom Stages / a replace-slot stage are not DAS stages: nothing to
    // fetch here (useCustomStages / useStageSlots own their data).
    if (selectedStage?.isCustom || selectedStage?.isSlot) {
      setDataReady(true)
      return
    }
    if (selectedStage && dasInstalled) {
      setDataReady(false)
      setTransformFixNotice(null)
      setMexVariants([])
      setSelectedButton(null)
      fetchMexVariants(selectedStage.code)
      // Reset scroll position of Available to Import list
      if (availableListRef.current) {
        availableListRef.current.scrollTop = 0
      }
    }
  }, [selectedStage, dasInstalled])

  const checkDASInstallation = async () => {
    setDasChecking(true)
    try {
      const data = await api.get('/das/status')
      setDasInstalled(data.installed)
      setDasMissingStages(data.missingStages || [])
    } catch (err) {
      console.error('Failed to check DAS status:', err)
    } finally {
      setDasChecking(false)
    }
  }

  const installDAS = async () => {
    if (!await appConfirm('Install Dynamic Alternate Stages framework? This will modify stage files in your MEX project.', {
      title: 'Install DAS Framework',
      confirmText: 'Install',
      confirmStyle: 'primary',
    })) {
      return
    }

    setDasChecking(true)
    try {
      const result = await api.post('/das/install')
      // Each loader is rebuilt from the user's own vanilla stage file; when
      // no vanilla copy can be found the backend installs the rest and says
      // so. The status read below keeps offering the install for those.
      const notice = dasInstallNotice(result)
      if (notice) {
        playSound('error')
        appAlert(notice, { title: DAS_NOTICE_TITLE })
      } else {
        alert('DAS framework installed successfully!')
      }
      await checkDASInstallation()
      fetchStorageVariants()
      fetchAllMexVariantCounts()
      if (selectedStage && !selectedStage.isCustom && !selectedStage.isSlot) {
        fetchMexVariants(selectedStage.code)
      }
    } catch (err) {
      console.error('DAS installation error:', err)
      alert(`DAS installation failed: ${err.message}`)
    } finally {
      setDasChecking(false)
    }
  }

  const fetchStorageVariants = async () => {
    try {
      const data = await api.get('/das/storage/variants')
      setStorageVariants(data.variants)
      // Forget selections for vault variants that no longer exist.
      const zipPaths = new Set((data.variants || []).map(v => v.zipPath))
      setSelectedVariants(prev => pruneSelection(prev, key => zipPaths.has(key)))
    } catch (err) {
      console.error('Failed to fetch storage variants:', err)
    }
  }

  const fetchMexVariants = async (stageCode) => {
    try {
      const data = await api.get(`/das/stages/${stageCode}/variants`)
      const variants = data.variants || []
      setMexVariants(variants)
      // Drop selections for this stage's variants that were removed or
      // renamed, so "Remove selected" never targets a variant that is gone.
      const names = new Set(variants.map(v => v.name))
      setSelectedInstalledVariants(prev => pruneSelection(prev, key => {
        const item = parseInstalledVariantKey(key)
        return !!item && (item.stageCode !== stageCode || names.has(item.variantName))
      }))
    } catch (err) {
      console.error('Failed to fetch MEX variants:', err)
      if (!err.data) setMexVariants([])  // envelope errors keep the last good list
    } finally {
      setTimeout(() => setDataReady(true), 50)
    }
  }

  const fetchAllMexVariantCounts = async () => {
    try {
      const counts = {}
      await Promise.all(
        DAS_STAGES.map(async (stage) => {
          try {
            const data = await api.get(`/das/stages/${stage.code}/variants`)
            counts[stage.code] = data.variants?.length || 0
          } catch { /* a stage with no readable variant list keeps no count */ }
        })
      )
      setMexVariantCounts(counts)
    } catch (err) {
      console.error('Failed to fetch MEX variant counts:', err)
    }
  }

  const handleImportVariant = async (variant) => {
    if (importing) return

    setImporting(true)
    setImportingCostume(variant.zipPath)
    setTransformFixNotice(null)

    try {
      const result = await api.post('/das/import', {
        stageCode: variant.stageCode,
        variantPath: variant.zipPath
      })
      const reports = [{
        name: variant.name,
        transformFix: result.transformFix
      }]
      setTransformFixNotice(summarizeTransformFixResults(reports))

      console.log(`✓ Successfully imported variant to ${variant.stageName}`)
      await onRefresh()
      await fetchMexVariants(selectedStage.code)
      await fetchStorageVariants()
      await fetchAllMexVariantCounts()
    } catch (err) {
      console.error('Import error:', err)
      alert(`Import failed: ${err.message}`)
    } finally {
      setImporting(false)
      setImportingCostume(null)
    }
  }

  const handleRestoreVanilla = async () => {
    if (!selectedStage || restoringVanilla) return
    setRestoringVanilla(true)
    try {
      await api.post('/das/restore-vanilla', {
        stageCode: selectedStage.code,
      })
      playSound('newSkin')
      await fetchMexVariants(selectedStage.code)
      await fetchAllMexVariantCounts()
    } catch (err) {
      console.error('Vanilla stage restore failed:', err)
      alert('Restore failed: ' + err.message)
    } finally {
      setRestoringVanilla(false)
    }
  }

  const handleBatchImportVariants = async () => {
    if (selectedVariants.size === 0 || batchImporting) return

    setBatchImporting(true)
    const variantsToImport = Array.from(selectedVariants)
    const total = variantsToImport.length
    setBatchProgress({ current: 0, total })

    let successCount = 0
    let failCount = 0
    let completedCount = 0
    const transformFixResults = []
    setTransformFixNotice(null)
    const markBatchStepComplete = () => {
      completedCount += 1
      setBatchProgress({ current: completedCount, total })
    }

    for (let i = 0; i < variantsToImport.length; i++) {
      const zipPath = variantsToImport[i]
      const variant = storageVariants.find(v => v.zipPath === zipPath)

      if (!variant) {
        failCount++
        markBatchStepComplete()
        continue
      }

      try {
        const result = await api.post('/das/import', {
          stageCode: variant.stageCode,
          variantPath: variant.zipPath
        })
        transformFixResults.push({
          name: variant.name,
          transformFix: result.transformFix
        })
        successCount++
      } catch (err) {
        console.error(`Import error for ${variant.name}:`, err)
        failCount++
      } finally {
        markBatchStepComplete()
      }
    }

    // Refresh once at the end
    await onRefresh()
    if (selectedStage) {
      await fetchMexVariants(selectedStage.code)
    }
    await fetchStorageVariants()
    await fetchAllMexVariantCounts()

    setTransformFixNotice(summarizeTransformFixResults(transformFixResults))

    // Clear selections
    setSelectedVariants(new Set())
    setBatchImporting(false)
    setBatchProgress({ current: 0, total: 0 })

    // Show summary
    if (failCount > 0) {
      playSound('error')
      alert(`Batch import completed:\n${successCount} succeeded, ${failCount} failed`)
    } else {
      playSound('newSkin')
      console.log(`✓ Successfully imported ${successCount} stage variant(s)`)
    }
  }

  const handleButtonClick = (button) => {
    setSelectedButton(selectedButton === button ? null : button)
  }

  const handleVariantClick = async (variant) => {
    if (!selectedButton) return

    if (variant.button === selectedButton) {
      console.log(`Variant already has button ${selectedButton}`)
      return
    }

    const buttonToAdd = selectedButton
    const variantNameWithoutExt = variant.name
    const newVariantName = addButtonIndicator(variantNameWithoutExt, buttonToAdd)

    try {
      await api.post('/das/rename', {
        stageCode: variant.stageCode,
        oldName: variantNameWithoutExt,
        newName: newVariantName
      })

      console.log(`✓ Added button ${buttonToAdd} to ${variant.name}`)
      setSelectedButton(null)
      await fetchMexVariants(selectedStage.code)
    } catch (err) {
      console.error('Button add error:', err)
      alert(`Failed to add button: ${err.message}`)
    }
  }

  const handleRemoveButton = async (variant) => {
    if (!variant.button) return

    const variantNameWithoutExt = variant.name
    const variantNameWithoutButton = normalizeProjectVariantName(stripButtonIndicator(variantNameWithoutExt))

    try {
      await api.post('/das/rename', {
        stageCode: variant.stageCode,
        oldName: variantNameWithoutExt,
        newName: variantNameWithoutButton
      })

      console.log(`✓ Removed button ${variant.button} from ${variant.name}`)
      await fetchMexVariants(selectedStage.code)
    } catch (err) {
      console.error('Button remove error:', err)
      alert(`Failed to remove button: ${err.message}`)
    }
  }

  const removeVariantFromProject = async (stageCode, variantName) => {
    try {
      return await api.post('/das/remove', {
        stageCode: stageCode,
        variantName: variantName
      })
    } catch (err) {
      throw new Error(err.message || 'Remove failed')
    }
  }

  const handleRemoveVariant = (stageCode, variantName) => {
    if (removing) return

    // Show confirm dialog instead of native confirm()
    setPendingRemoval({ stageCode, variantName })
    setShowConfirmDialog(true)
  }

  const handleBatchRemoveVariants = () => {
    if (removing || selectedInstalledVariants.size === 0) return

    const items = Array.from(selectedInstalledVariants)
      .map(parseInstalledVariantKey)
      .filter(Boolean)

    if (items.length === 0) return

    setPendingRemoval({ bulk: true, items })
    setShowConfirmDialog(true)
  }

  const confirmRemoveVariant = async () => {
    if (!pendingRemoval) return

    const removal = pendingRemoval
    setShowConfirmDialog(false)
    setPendingRemoval(null)

    if (removal.bulk) {
      await confirmBatchRemoveVariants(removal.items)
      return
    }

    const { stageCode, variantName } = removal
    setRemoving(true)

    try {
      await api.post('/das/remove', {
        stageCode: stageCode,
        variantName: variantName
      })

      console.log(`✓ Successfully removed "${variantName}"`)
      setSelectedInstalledVariants(prev => {
        const next = new Set(prev)
        next.delete(installedVariantKey(stageCode, variantName))
        return next
      })
      await onRefresh()
      await fetchMexVariants(selectedStage.code)
      await fetchStorageVariants()
      await fetchAllMexVariantCounts()
    } catch (err) {
      console.error('Remove error:', err)
      alert(`Remove failed: ${err.message}`)
    } finally {
      setRemoving(false)
    }
  }

  const confirmBatchRemoveVariants = async (items) => {
    const removalQueue = Array.from(
      new Map(items.map(item => [installedVariantKey(item.stageCode, item.variantName), item])).values()
    ).sort((a, b) => {
      const stageCompare = a.stageCode.localeCompare(b.stageCode)
      return stageCompare || a.variantName.localeCompare(b.variantName)
    })

    setRemoving(true)
    let successCount = 0
    let failCount = 0

    for (const item of removalQueue) {
      try {
        await removeVariantFromProject(item.stageCode, item.variantName)
        successCount++
      } catch (err) {
        failCount++
        console.error(`Failed to remove ${item.stageCode} variant ${item.variantName}:`, err)
      }
    }

    try {
      await onRefresh()
      if (selectedStage && !selectedStage.isCustom) {
        await fetchMexVariants(selectedStage.code)
      }
      await fetchStorageVariants()
      await fetchAllMexVariantCounts()
    } finally {
      setRemoving(false)
      setSelectedInstalledVariants(new Set())
    }

    if (failCount > 0) {
      playSound('error')
      alert(`Batch remove completed:\n${successCount} removed, ${failCount} failed`)
    } else {
      playSound('boop')
      console.log(`âœ“ Successfully removed ${successCount} stage variant(s)`)
    }
  }

  const getVariantsForStage = (stageCode) => {
    return storageVariants.filter(v => v.stageCode === stageCode)
  }

  const installedVariantKey = (stageCode, variantName) => JSON.stringify([stageCode, variantName])

  const parseInstalledVariantKey = (key) => {
    try {
      const [stageCode, variantName] = JSON.parse(key)
      if (typeof stageCode !== 'string' || typeof variantName !== 'string') return null
      return { stageCode, variantName }
    } catch (err) {
      console.error('Invalid installed variant key:', key, err)
      return null
    }
  }

  const toggleInstalledVariantSelection = (stageCode, variantName) => {
    const key = installedVariantKey(stageCode, variantName)
    setSelectedInstalledVariants(prev => {
      const newSet = new Set(prev)
      if (newSet.has(key)) {
        newSet.delete(key)
      } else {
        newSet.add(key)
      }
      return newSet
    })
  }

  const selectAllInstalledVariants = () => {
    if (!selectedStage) return
    setSelectedInstalledVariants(prev => {
      const newSet = new Set(prev)
      mexVariants.forEach(variant => newSet.add(installedVariantKey(selectedStage.code, variant.name)))
      return newSet
    })
  }

  const clearInstalledVariantSelection = () => {
    setSelectedInstalledVariants(new Set())
  }

  const toggleVariantSelection = (zipPath) => {
    setSelectedVariants(prev => {
      const newSet = new Set(prev)
      if (newSet.has(zipPath)) {
        newSet.delete(zipPath)
      } else {
        newSet.add(zipPath)
      }
      return newSet
    })
  }

  const selectAllVariants = () => {
    if (!selectedStage) return
    const allVariants = getVariantsForStage(selectedStage.code)
    setSelectedVariants(prev => {
      const newSet = new Set(prev)
      allVariants.forEach(v => newSet.add(v.zipPath))
      return newSet
    })
  }

  const clearVariantSelection = () => {
    setSelectedVariants(new Set())
  }

  return {
    dasInstalled,
    dasMissingStages,
    dasChecking,
    selectedStage,
    setSelectedStage,
    storageVariants,
    mexVariants,
    mexVariantCounts,
    selectedVariants,
    selectedInstalledVariants,
    selectedButton,
    importing,
    importingCostume,
    removing,
    restoringVanilla,
    batchImporting,
    batchProgress,
    dataReady,
    transformFixNotice,
    setTransformFixNotice,
    showConfirmDialog,
    setShowConfirmDialog,
    pendingRemoval,
    setPendingRemoval,
    availableListRef,
    installDAS,
    handleImportVariant,
    handleRestoreVanilla,
    handleBatchImportVariants,
    handleButtonClick,
    handleVariantClick,
    handleRemoveButton,
    handleRemoveVariant,
    handleBatchRemoveVariants,
    confirmRemoveVariant,
    getVariantsForStage,
    installedVariantKey,
    toggleInstalledVariantSelection,
    selectAllInstalledVariants,
    clearInstalledVariantSelection,
    toggleVariantSelection,
    selectAllVariants,
    clearVariantSelection
  }
}
