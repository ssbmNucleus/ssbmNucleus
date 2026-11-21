import { useState, useEffect, useRef } from 'react'
import { materialSamples, materialAdjustments } from './materialPalette'
import { textureKey } from './paintProtocol'
import { analyzeTextureColors, applyGroupAdjustments } from './colorUtils'

// Color palette analysis and batch hue/saturation adjustments across all textures.
export function useColorPalette({ modelTextures, editedTextures, setEditedTextures, setIsDirty, hasElectron, viewerWs, sendTexture, getTextureSource, materials }) {
  const [colorPaletteEnabled, setColorPaletteEnabled] = useState(false)
  const [colorGroups, setColorGroups] = useState([])
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState(null)
  const [maxColorGroups, setMaxColorGroups] = useState(8)
  const [selectedColorGroup, setSelectedColorGroup] = useState(null)
  const [originalTextureData, setOriginalTextureData] = useState({}) // { [index]: ImageData }
  const materialFieldsRef = useRef({})
  const workRef = useRef(Promise.resolve())
  const appliedRef = useRef(false)
  const [paletteTarget, setPaletteTarget] = useState('both')
  const [isApplying, setIsApplying] = useState(false)
  const pixelGroupMapRef = useRef({}) // Maps pixels to their color group index
  const colorDebounceRef = useRef(null)
  const analysisGenerationRef = useRef(0)

  const cancelPendingWork = () => {
    analysisGenerationRef.current += 1
    clearTimeout(colorDebounceRef.current)
    colorDebounceRef.current = null
    setIsAnalyzing(false)
  }

  useEffect(() => () => {
    analysisGenerationRef.current += 1
    clearTimeout(colorDebounceRef.current)
  }, [])

  // Analyze all textures and detect color groups
  const analyzeColors = async () => {
    if (modelTextures.length === 0 && !materials) return
    const generation = ++analysisGenerationRef.current
    setIsAnalyzing(true)
    setAnalysisError(null)

    try {
      // First, capture original texture data
      const originals = {}
      for (let texIdx = 0; texIdx < (materials && paletteTarget === 'materials' ? 0 : modelTextures.length); texIdx++) {
        const tex = modelTextures[texIdx]
        const key = textureKey(tex)
        if (generation !== analysisGenerationRef.current) return
        const imgSrc = editedTextures[key] || (getTextureSource ? await getTextureSource(tex) : (tex.thumbnail ? `data:image/png;base64,${tex.thumbnail}` : null))
        if (generation !== analysisGenerationRef.current) return
        if (!imgSrc) continue

        const img = await new Promise((resolve, reject) => {
          const i = new Image()
          i.onload = () => resolve(i)
          i.onerror = () => reject(new Error(`Could not read ${tex.label || tex.memberId || ''} texture ${tex.index}`))
          i.src = imgSrc
        })
        if (generation !== analysisGenerationRef.current) return

        const canvas = document.createElement('canvas')
        canvas.width = tex.width
        canvas.height = tex.height
        const ctx = canvas.getContext('2d')
        ctx.drawImage(img, 0, 0, tex.width, tex.height)
        originals[key] = ctx.getImageData(0, 0, tex.width, tex.height)
      }
      materialFieldsRef.current = {}
      if (materials && paletteTarget !== 'textures') {
        const inventory = await materials.inspect()
        if (generation !== analysisGenerationRef.current) return
        const samples = materialSamples(inventory)
        Object.assign(originals, samples.originals)
        materialFieldsRef.current = samples.fields
      }
      appliedRef.current = false
      setOriginalTextureData(originals)

      const { groups, pixelMap } = analyzeTextureColors(originals, maxColorGroups)
      pixelGroupMapRef.current = pixelMap

      setColorGroups(groups)
      setColorPaletteEnabled(true)
    } catch (error) {
      if (generation === analysisGenerationRef.current) setAnalysisError(error.message)
    } finally {
      if (generation === analysisGenerationRef.current) setIsAnalyzing(false)
    }
  }

  // Apply color adjustments to all textures
  const applyColorAdjustments = async (groups) => {
    if (!groups || groups.length === 0 || Object.keys(originalTextureData).length === 0) return

    // Skip if all adjustments are zero
    const hasAdjustments = groups.some(g => g.hueShift !== 0 || g.saturationShift !== 0)
    if (!hasAdjustments && !appliedRef.current) return

    const newEditedTextures = {}

    for (const texIdxStr of Object.keys(originalTextureData)) {
      const texIdx = texIdxStr
      const texture = modelTextures.find(tex => textureKey(tex) === texIdx)
      if (!texture) continue
      const original = originalTextureData[texIdx]
      const pixelMap = pixelGroupMapRef.current[texIdx]
      if (!original || !pixelMap) continue

      const result = applyGroupAdjustments(original, pixelMap, groups)

      // Convert to data URL
      const canvas = document.createElement('canvas')
      canvas.width = original.width
      canvas.height = original.height
      const ctx = canvas.getContext('2d')
      ctx.putImageData(result, 0, 0)
      newEditedTextures[texIdx] = canvas.toDataURL('image/png')

      // Send to viewer via Electron IPC
      if (hasElectron && viewerWs) {
        const base64 = newEditedTextures[texIdx].replace('data:image/png;base64,', '')
        if (sendTexture) sendTexture(texture, base64)
        else window.electron.viewerSend({ type: 'updateTexture', index: texture.index, data: base64 })
      }
    }

    if (materials && Object.keys(materialFieldsRef.current).length) {
      await materials.apply(materialAdjustments(originalTextureData, materialFieldsRef.current, pixelGroupMapRef.current, groups))
    }
    appliedRef.current = hasAdjustments
    setEditedTextures(previous => ({ ...previous, ...newEditedTextures }))
    setIsDirty(true)
  }

  const queueAdjustments = groups => {
    const generation = analysisGenerationRef.current
    setIsApplying(true)
    const task = workRef.current.catch(() => {}).then(async () => {
      if (generation !== analysisGenerationRef.current) return
      await applyColorAdjustments(groups)
      if (generation === analysisGenerationRef.current) setAnalysisError(null)
    })
    workRef.current = task
    task.catch(error => {
      if (generation === analysisGenerationRef.current) setAnalysisError(error.message)
    }).finally(() => { if (workRef.current === task) setIsApplying(false) })
    return task
  }

  // Handle color group adjustment
  const handleColorAdjust = (groupId, field, value) => {
    setColorGroups(prev => prev.map(g => {
      if (g.id !== groupId) return g
      if (field === 'reset') {
        return { ...g, hueShift: 0, saturationShift: 0 }
      }
      return { ...g, [field]: value }
    }))
  }

  // Apply color adjustments when groups change (debounced via effect)
  useEffect(() => {
    if (!colorPaletteEnabled || colorGroups.length === 0) return

    // Debounce the application
    if (colorDebounceRef.current) {
      clearTimeout(colorDebounceRef.current)
    }
    colorDebounceRef.current = setTimeout(() => {
      colorDebounceRef.current = null
      queueAdjustments(colorGroups)
    }, 50)

    return () => {
      if (colorDebounceRef.current) {
        clearTimeout(colorDebounceRef.current)
      }
    }
  }, [colorGroups, colorPaletteEnabled])

  // Commit a pending slider change before exporting/stopping the current DAT.
  const flushColorAdjustments = async () => {
    const pending = colorDebounceRef.current !== null
    clearTimeout(colorDebounceRef.current)
    colorDebounceRef.current = null
    if (pending) queueAdjustments(colorGroups)
    await workRef.current
  }

  // Reset color palette
  const resetColorPalette = async () => {
    clearTimeout(colorDebounceRef.current)
    colorDebounceRef.current = null
    try { await queueAdjustments(colorGroups.map(g => ({ ...g, hueShift: 0, saturationShift: 0 }))) }
    catch { return }
    cancelPendingWork()
    setColorPaletteEnabled(false)
    setColorGroups([])
    setSelectedColorGroup(null)
    setOriginalTextureData({})
    pixelGroupMapRef.current = {}
  }

  // Reset palette state when the skin creator closes (does not touch selectedColorGroup,
  // matching the original close behavior)
  const clearPaletteState = () => {
    cancelPendingWork()
    setAnalysisError(null)
    setColorPaletteEnabled(false)
    setColorGroups([])
    setOriginalTextureData({})
    pixelGroupMapRef.current = {}
  }

  return {
    materialSupport: Boolean(materials), paletteTarget, setPaletteTarget, isApplying,
    colorPaletteEnabled,
    colorGroups,
    isAnalyzing,
    analysisError,
    maxColorGroups,
    setMaxColorGroups,
    selectedColorGroup,
    setSelectedColorGroup,
    analyzeColors,
    resetColorPalette,
    clearPaletteState,
    flushColorAdjustments,
    handleColorAdjust
  }
}
