import { useState, useEffect, useRef, useCallback } from 'react'
import { usePanelResize } from '../../shared/hooks/usePanelResize'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { api } from '../../shared/transport/api'
import { useCanvasScale } from './useCanvasScale'
import { useUndoRedo } from './useUndoRedo'
import { usePaintCanvas } from './usePaintCanvas'
import { useColorPalette } from './useColorPalette'
import { useViewerInput } from '../../shared/viewer/useViewerInput'
import { useViewerSurface } from '../../shared/viewer/useViewerSurface'
import '../../shared/viewer/viewerSurface.css'
import { cancelExportDat } from './datUtils'
import { viewerErrorMessage } from '../../shared/viewer/viewerSession'
import { textureKey, textureAddress, texturesInPaintScope } from './paintProtocol'
import { createViewerMessageHandler } from './skinCreatorViewerMessages'
import { createViewerLaunchers } from './skinCreatorLaunch'
import { useTextureCanvasLoad } from './useTextureCanvasLoad'
import { createTextureFileActions } from './textureFileActions'
import { createSaveActions } from './skinCreatorSave'
import { useViewerPose } from './useViewerPose'
import { paintPanStep, readViewerCamera } from './paintViewerPan'
import SkinCreatorHeader from './SkinCreatorHeader'
import CostumeSelectStep from './CostumeSelectStep'
import PaintToolbar from './PaintToolbar'
import { useTextureHighlight } from './useTextureHighlight'
import CanvasFloatingActions from './CanvasFloatingActions'
import TextureViewBar from './TextureViewBar'
import ColorToolsPanel from './ColorToolsPanel'
import { useMaterialColors } from './useMaterialColors'
import TextureStrip from './TextureStrip'
import PreviewPanel from './PreviewPanel'
import SelectionOverlay from './SelectionOverlay'
import { useLayers } from './useLayers'
import SaveModal from './SaveModal'
import './SkinCreator.css'
// Sheets split out of SkinCreator.css, which ends where they begin. Imported
// here, in their original order, so the cascade is unchanged.
import './ViewerAnimPopover.css'
import './areaSelection.css'
import './ReferencePanel.css'
import './TextureViewBar.css'
import './LayersPanel.css'
import { useContext } from 'react'
import { EditorContext } from '../../shared/lib/EditorContext'

export default function SkinCreator({
  isOpen,
  onClose,
  selectedCharacter,
  onSkinCreatorChange,
  onRefresh,
  initialCostume
}) {
  const isStage = Boolean(initialCostume?.stageCode)
  const stageWorkspaceRef = useRef(null)
  const stageTextureReads = useRef(new Map())
  const [stageAnimation, setStageAnimation] = useState({ playing: false, frame: 0, frameCount: 0 })
  // Character sessions: AJ animation symbols for the preview's animation popover
  const [animList, setAnimList] = useState([])
  const [selectedAnim, setSelectedAnim] = useState('')
  // State
  const assistantEditor = useContext(EditorContext)
  const assistantConnected = assistantEditor?.editor?.skinId === initialCostume?.id && Boolean(initialCostume)
  const [skinCreatorStep, setSkinCreatorStep] = useState('select') // 'select' or 'edit'
  const [vanillaCostumes, setVanillaCostumes] = useState([])
  const [selectedVanillaCostume, setSelectedVanillaCostume] = useState(null)
  const [skinCreatorLoading, setSkinCreatorLoading] = useState(false)
  const [skinCreatorError, setSkinCreatorError] = useState(null)
  const [viewerWs, setViewerWs] = useState(null)
  const [modelTextures, setModelTextures] = useState([])
  const [textureModels, setTextureModels] = useState(null) // which model draws each texture (textureSections)
  const [selectedTextureIndex, setSelectedTextureIndex] = useState(null)
  const skinCreatorCanvasRef = useRef(null)
  const paintCanvasRef = useRef(null)

  // Native frames are presented in the Electron canvas; legacy embedding is explicit.
  const [viewerStreaming, setViewerStreaming] = useState(null)
  const streamCanvasRef = useRef(null)
  const viewerCleanupRef = useRef(null)
  const [capabilityWarning, setCapabilityWarning] = useState('')

  const [adoptedRevision, setAdoptedRevision] = useState(0)
  const [pendingCheckpoint, setPendingCheckpoint] = useState(null)
  const [editedTextures, setEditedTextures] = useState({}) // { [index]: dataUrl }
  const editedTexturesRef = useRef({}) // Ref for interval callback access
  const [isDirty, setIsDirty] = useState(false)
  const [showSaveModal, setShowSaveModal] = useState(false)
  const [skinName, setSkinName] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const savingRef = useRef(false)
  const [saveError, setSaveError] = useState(null)
  const [skinCreatorReconnecting, setSkinCreatorReconnecting] = useState(false)
  const [skinCreatorReconnectAttempts, setSkinCreatorReconnectAttempts] = useState(0)
  const skinCreatorReconnectTimeoutRef = useRef(null)
  const skinCreatorMaxReconnectAttempts = 3
  const { poseOptions, selectedPoseName, setSelectedPoseName, defaultPoseName, activeStartPoseRef, resolveViewerPose } = useViewerPose()

  // Connection health and auto-refresh
  const autoRefreshIntervalRef = useRef(null)
  const pingIntervalRef = useRef(null)
  const lastMessageTimeRef = useRef(Date.now()) // Track last message received (any type)
  const [connectionFailed, setConnectionFailed] = useState(false)

  const exportDatResolverRef = useRef(null) // For promise-based exportDat with Electron IPC
  // The SOURCE costume's dat filename (e.g. PlFxNr.dat), captured from the
  // viewer-paths response. Saves must keep a Pl* dat name -- the import
  // pipeline only recognizes Pl*-stemmed DATs as costumes.
  const sourceDatNameRef = useRef(null)
  const paintPairRef = useRef(null)
  const [paintMembers, setPaintMembers] = useState([])
  const paintSessionRef = useRef(null)
  const paintRequestRef = useRef(0)
  const pairLoadRef = useRef(null)
  const readyGenerationRef = useRef(null)
  const selectionRevisionRef = useRef(0)
  const selectionRef = useRef(null)
  const fullTextureRequestRef = useRef(null)
  const textureListRequestRef = useRef(null)
  const canvasOwnerRef = useRef(null)
  const [canvasOwner, setCanvasOwner] = useState(null)
  // What the canvas itself last published, per texture, so the load effect can
  // tell its own echo from an outside write and leave the canvas (and its
  // ownership, and therefore undo) alone. See shouldReloadPaintCanvas.
  const canvasWritesRef = useRef(new Map()) // textureId -> dataUrl
  const [paletteScope, setPaletteScope] = useState('popo')
  const viewerGenerationRef = useRef(0)
  const [paletteTab, setPaletteTab] = useState('textures')
  const materialColors = useMaterialColors({ generation: viewerWs?.viewerSessionId, onChanged: () => setIsDirty(true) })
  const editorSessionRef = useRef(0)
  const sourceRequestRef = useRef(0)

  useEffect(() => () => {
    for (const pending of stageTextureReads.current.values()) { clearTimeout(pending.timer); pending.reject(new Error("Editor closed")) }
    stageTextureReads.current.clear()
    editorSessionRef.current += 1
    viewerGenerationRef.current += 1
    clearTimeout(pairLoadRef.current?.timeout)
    cancelExportDat(exportDatResolverRef, 'Skin Creator closed during export')
    viewerCleanupRef.current?.()
    viewerCleanupRef.current = null
    clearAllIntervals()
    clearTimeout(skinCreatorReconnectTimeoutRef.current)
    const viewerSessionId = paintSessionRef.current
    paintSessionRef.current = null
    if (viewerSessionId) Promise.resolve(window.electron?.viewerStop(viewerSessionId)).catch(console.error)
  }, [])

  useEffect(() => {
    if (isOpen) return
    editorSessionRef.current += 1
    viewerGenerationRef.current += 1
    viewerCleanupRef.current?.()
    viewerCleanupRef.current = null
    clearAllIntervals()
    clearTimeout(pairLoadRef.current?.timeout)
    clearTimeout(skinCreatorReconnectTimeoutRef.current)
    cancelExportDat(exportDatResolverRef, 'Skin Creator closed during export')
    const viewerSessionId = paintSessionRef.current
    paintSessionRef.current = null
    setViewerWs(null)
    setViewerStreaming(null)
    if (viewerSessionId) Promise.resolve(window.electron?.viewerStop(viewerSessionId)).catch(console.error)
  }, [isOpen])

  // Panel resize hook
  const {
    sizes: panelSizes,
    separatorProps,
    resetSizes,
  } = usePanelResize()

  // Check if Electron API is available
  const hasElectron = typeof window !== 'undefined' && window.electron?.viewerStart

  const updateEditedTextures = (update) => {
    const next = typeof update === 'function' ? update(editedTexturesRef.current) : update
    editedTexturesRef.current = next
    setEditedTextures(next)
  }

  // Canvas container sizing for dynamic scaling
  const { canvasContainerRef, updateCanvasScale, zoom, zoomBy, fit, actualSize,
    hand, setHand, panning, panMode, beginPan, isPanning } = useCanvasScale({
    skinCreatorStep,
    selectedTextureIndex,
    modelTextures,
    paintCanvasRef
  })

  const failViewer = (error) => {
    clearAllIntervals()
    clearTimeout(pairLoadRef.current?.timeout)
    pairLoadRef.current = null
    setConnectionFailed(true)
    setSkinCreatorLoading(false)
    setSkinCreatorError(viewerErrorMessage(error, isStage))
    cancelExportDat(exportDatResolverRef, error?.message || String(error))
  }

  const paintCommand = (message) => ({ ...message, ...(paintPairRef.current ? {
    sessionId: paintSessionRef.current, requestId: `paint-${++paintRequestRef.current}`
  } : {}) })

  const sendPaintCommand = (message) => {
    const generation = viewerGenerationRef.current
    return Promise.resolve(window.electron.viewerSend(paintCommand(message))).then(sent => {
      if (sent === false) throw new Error('Viewer disconnected. Your paint edits are retained.')
    }).catch(error => {
      if (generation === viewerGenerationRef.current) failViewer(error)
    })
  }

  const requestPaintTextures = () => {
    const generation = viewerGenerationRef.current
    const command = paintCommand({ type: 'getTextures' })
    textureListRequestRef.current = command.requestId
    Promise.resolve(window.electron.viewerSend(command)).then(sent => {
      if (sent === false) throw new Error('Viewer disconnected before loading textures')
    }).catch(error => { if (generation === viewerGenerationRef.current) failViewer(error) })
  }

  const restorePaintEdits = () => {
    Object.entries(editedTexturesRef.current).forEach(([key, dataUrl]) => {
      sendPaintCommand({ type: 'updateTexture', ...textureAddress(key),
        data: dataUrl.replace('data:image/png;base64,', '') })
    })
  }

  // Follow the chat: adopt when this editor shows the same costume and the
  // user has nothing unsaved; otherwise keep it as an offer, never a surprise.
  const chatCheckpoint = assistantEditor?.checkpoint
  useEffect(() => {
    if (!isOpen || !chatCheckpoint || skinCreatorStep !== 'edit') return
    const character = initialCostume?.character || selectedCharacter
    const target = chatCheckpoint.target || {}
    const sameCostume = target.character === character
      && (!target.skin_id || !initialCostume?.id || target.skin_id === initialCostume.id)
    if (!sameCostume || (chatCheckpoint.revision || 0) <= adoptedRevision) return
    const busy = isSaving || skinCreatorLoading || isDrawingRef.current
    if (!busy && Object.keys(editedTexturesRef.current).length === 0) adoptCheckpoint(chatCheckpoint)
    else setPendingCheckpoint(chatCheckpoint)
  }, [chatCheckpoint, isOpen, skinCreatorStep, isSaving, skinCreatorLoading, adoptedRevision,
      initialCostume?.id, initialCostume?.character, selectedCharacter])

  const selectedTexture = modelTextures[selectedTextureIndex]
  const selectedTextureId = selectedTexture ? textureKey(selectedTexture) : null
  useEffect(() => {
    if (!assistantConnected) return
    assistantEditor.setEditorTexture(selectedTexture ? {
      id: selectedTextureId, name: selectedTexture.name || `Texture ${selectedTexture.index}`,
      index: selectedTexture.index, memberId: selectedTexture.memberId || null,
      width: selectedTexture.width, height: selectedTexture.height,
    } : null)
  }, [assistantConnected, selectedTextureId, selectedTexture?.name, selectedTexture?.width, selectedTexture?.height, assistantEditor?.setEditorTexture])
  selectionRef.current = selectedTextureId

  const sendTextureUpdate = () => {
    const canvas = paintCanvasRef.current
    if (!canvas || !hasElectron || !viewerWs) return
    if (selectedTextureIndex === null || canvasOwnerRef.current !== selectedTextureId) return

    const ctx = canvas.getContext('2d')
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)

    const tempCanvas = document.createElement('canvas')
    tempCanvas.width = canvas.width
    tempCanvas.height = canvas.height
    const tempCtx = tempCanvas.getContext('2d')
    tempCtx.putImageData(imageData, 0, 0)

    const dataUrl = tempCanvas.toDataURL('image/png')
    const base64 = dataUrl.replace('data:image/png;base64,', '')

    try {
      if (hasElectron) {
        sendPaintCommand({
          type: 'updateTexture', ...textureAddress(selectedTextureId),
          data: base64
        })
      }

      canvasWritesRef.current.set(selectedTextureId, dataUrl)
      updateEditedTextures(prev => ({ ...prev, [selectedTextureId]: dataUrl }))
      setIsDirty(true)
    } catch (err) {
      console.error('Error sending updateTexture:', err)
    }
  }

  // Layer stack for the texture being painted. The game only ever takes a flat
  // texture, so the stack is a session-lived editor construct that flattens
  // into paintCanvasRef on every commit -- see useLayers.
  const layers = useLayers({ paintCanvasRef, onComposite: sendTextureUpdate })

  // Undo/Redo stack. With layers the entries are per-layer (or whole-stack for
  // structural edits) instead of flattened canvases -- one linear history per
  // texture either way.
  const layerHistory = {
    pixel: layers.pixelSnapshot, structure: layers.structureSnapshot, restore: layers.restoreSnapshot
  }
  const { undoStack, redoStack, saveToUndoStack, undo, redo } = useUndoRedo({
    paintCanvasRef,
    layerHistory,
    sendTextureUpdate,
    selectedTextureIndex: selectedTextureId,
    resetKey: paintSessionRef.current,
    canEdit: () => !savingRef.current && canvasOwnerRef.current === selectedTextureId && selectionRef.current === selectedTextureId,
    isOpen: isOpen && !skinCreatorLoading && !isSaving && !connectionFailed && canvasOwner === selectedTextureId,
    skinCreatorStep
  })

  // Every structural layer edit takes one undo step, snapshotted BEFORE it runs
  // (the stack it is about to change is the thing being restored).
  const layerAction = (fn) => (...args) => {
    const before = layers.structureSnapshot()
    if (before) saveToUndoStack(before)
    fn(...args)
  }
  const beginLayerEdit = () => {
    const before = layers.structureSnapshot()
    if (before) saveToUndoStack(before)
  }

  // Drawing tools state and paint canvas handlers
  const {
    activeTool,
    setActiveTool,
    drawColor,
    setDrawColor,
    brushSize,
    setBrushSize,
    replaceTolerance,
    setReplaceTolerance,
    selection,
    pendingSelection,
    clearSelection,
    paintCursor,
    isDrawingRef,
    handlePaintMouseDown,
    handlePaintMouseMove,
    handlePaintMouseUp
  } = usePaintCanvas({
    // Tools write into the ACTIVE LAYER; the on-screen canvas keeps the
    // flattened result, which is what the viewer, the export and the eyedropper
    // all read. Committing reflattens and publishes in one step.
    viewCanvasRef: paintCanvasRef,
    targetCanvasRef: layers.activeLayerRef,
    saveToUndoStack,
    sendTextureUpdate: layers.commit,
    onLivePaint: layers.composite,
    zoom,
    selectionKeysEnabled: isOpen && skinCreatorStep === 'edit' && !isSaving && !skinCreatorLoading
  })

  // The overlay mounts after the transform was last applied, so re-apply once
  // it exists (and whenever the rect changes) to place it over the canvas.
  const activeSelection = pendingSelection || selection
  useEffect(() => {
    if (activeSelection) updateCanvasScale()
  }, [activeSelection, updateCanvasScale])

  // "Where is this texture on the model?" — a flat-colour probe pushed to the
  // viewer and taken straight back off. Raw send on purpose: a highlight is not
  // an edit, so it must not go through sendTextureUpdate (dirty flag, edited
  // textures, undo).
  const pushTexturePixels = useCallback((textureId, data) => {
    if (!hasElectron || !viewerWs) return
    sendPaintCommand({ type: 'updateTexture', ...textureAddress(textureId), data })
  }, [hasElectron, viewerWs])
  const { flash: flashTexture, cancelHighlight, highlighting } = useTextureHighlight({
    paintCanvasRef, pushTexture: pushTexturePixels, enabled: hasElectron && !!viewerWs
  })

  // Selecting a texture flashes where it lands on the model. Keyed to the
  // canvas OWNER, not the selection: before the pixels are in the canvas there
  // is nothing to build a probe from.
  const flashedForRef = useRef(null)
  useEffect(() => {
    if (!canvasOwner || canvasOwner !== selectedTextureId) return
    if (flashedForRef.current === canvasOwner) return
    flashedForRef.current = canvasOwner
    flashTexture(canvasOwner)
    // ...and bring the camera to it, so the flash is somewhere you can see.
    // Older viewers ignore the command; a drag or zoom cancels the ease.
    try {
      const { index, memberId } = textureAddress(canvasOwner)
      sendPaintCommand({ type: 'focusTextures', indices: [index], durationMs: 400,
                         ...(memberId ? { memberId } : {}) })
    } catch { /* a texture with no live address cannot be framed */ }
  }, [canvasOwner, selectedTextureId, flashTexture])
  // Moving to another texture restores the one being probed before its canvas
  // is repainted under us.
  useEffect(() => () => cancelHighlight(), [selectedTextureId, cancelHighlight])

  const readStageTexture = texture => new Promise((resolve, reject) => {
    const key = texture.index
    const generation = viewerGenerationRef.current
    const timer = setTimeout(() => { stageTextureReads.current.delete(key); reject(new Error('Could not read full-resolution texture')) }, 15000)
    stageTextureReads.current.set(key, { resolve, reject, timer, generation })
    Promise.resolve(window.electron.viewerSend({ type: 'getFullTexture', index: key })).then(sent => {
      if (sent === false) throw new Error('Viewer disconnected while reading textures')
    }).catch(error => { clearTimeout(timer); stageTextureReads.current.delete(key); reject(error) })
  })

  // Color Palette
  const palette = useColorPalette({
    materials: paintMembers.length ? null : materialColors,
    modelTextures: texturesInPaintScope(modelTextures, paletteScope),
    getTextureSource: isStage ? readStageTexture : undefined,
    editedTextures,
    sendTexture: (texture, data) => sendPaintCommand({ type: 'updateTexture', ...textureAddress(textureKey(texture)), data }),
    setEditedTextures: updateEditedTextures,
    setIsDirty,
    hasElectron,
    viewerWs
  })

  // The renderer's camera, read again whenever a model is up (a new session, costume or pose, both climbers loaded):
  // a right-drag pans by it, so the model stays under the cursor as in Randall's workbench (paintViewerPan).
  const viewerCameraRef = useRef(null)
  const viewerLive = !!hasElectron && !!viewerWs?.connected && isOpen && skinCreatorStep === 'edit' && !connectionFailed
  useEffect(() => {
    viewerCameraRef.current = null
    if (!viewerLive || skinCreatorLoading) return
    let current = true
    readViewerCamera(window.electron).then(camera => { if (current) viewerCameraRef.current = camera })
    return () => { current = false }
  }, [viewerLive, skinCreatorLoading, viewerWs?.viewerSessionId])
  useViewerInput({ containerRef: skinCreatorCanvasRef, enabled: viewerLive,
    sessionId: viewerWs?.viewerSessionId, zoomScale: 0.1,
    panStep: () => paintPanStep(viewerCameraRef.current, skinCreatorCanvasRef.current, isStage),
    onError: failViewer })
  useViewerSurface({ containerRef: skinCreatorCanvasRef, canvasRef: streamCanvasRef,
    streaming: viewerStreaming, connected: !!viewerWs?.connected && skinCreatorStep === 'edit',
    sessionId: viewerWs?.viewerSessionId, visible: isOpen && !connectionFailed, onError: failViewer })

  // Keep editedTexturesRef in sync with state for interval callback access
  useEffect(() => {
    editedTexturesRef.current = editedTextures
  }, [editedTextures])

  // Tell the parent (App) whether the fullscreen editor is up. Only the edit
  // step is fullscreen and hides the app header — the select step renders as a
  // normal in-app page (below the header), like the vault grid pages.
  useEffect(() => {
    onSkinCreatorChange?.(isOpen && skinCreatorStep === 'edit')
    return () => onSkinCreatorChange?.(false)
  }, [isOpen, skinCreatorStep, onSkinCreatorChange])

  // Load costumes when opening
  useEffect(() => {
    if (isOpen && selectedCharacter && skinCreatorStep === 'select' && !initialCostume) {
      loadVanillaCostumes(selectedCharacter)
    }
  }, [isOpen, selectedCharacter, skinCreatorStep, initialCostume])

  // Handle initialCostume for "edit from vault" flow
  useEffect(() => {
    if (isOpen && initialCostume) {
      startSkinCreatorFromVault(initialCostume)
    }
  }, [isOpen, initialCostume])

  // Load vanilla costumes
  const loadVanillaCostumes = async (character) => {
    try {
      setSkinCreatorLoading(true)
      setSkinCreatorError(null)
      const data = await api.get(`/api/mex/vanilla/costumes/${character}`)
      setVanillaCostumes(data.costumes)
    } catch (err) {
      setSkinCreatorError(err.message)
    } finally {
      setSkinCreatorLoading(false)
    }
  }

  // Handle viewer messages (Electron IPC)
  const handleViewerMessage = createViewerMessageHandler({
    lastMessageTimeRef, materialColors, isStage, stageTextureReads, viewerGenerationRef,
    setSkinCreatorError, setStageAnimation, setAnimList, setSelectedAnim, setCapabilityWarning,
    failViewer, paintPairRef, paintSessionRef, textureListRequestRef, setModelTextures,
    setSelectedTextureIndex, fullTextureRequestRef, selectionRef, editedTexturesRef, isDrawingRef,
    savingRef, paintCanvasRef, layers, canvasOwnerRef, setCanvasOwner,
    updateCanvasScale, readyGenerationRef, setSkinCreatorStep, setConnectionFailed, paintCommand,
    pairLoadRef, setSkinCreatorLoading, restorePaintEdits, requestPaintTextures, activeStartPoseRef,
    exportDatResolverRef,
  })

  // Clear all intervals helper
  const clearAllIntervals = () => {
    if (autoRefreshIntervalRef.current) {
      clearInterval(autoRefreshIntervalRef.current)
      autoRefreshIntervalRef.current = null
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
      pingIntervalRef.current = null
    }
  }

  const { launchPaintViewer, startSkinCreatorViewer, adoptCheckpoint, startSkinCreatorFromVault } = createViewerLaunchers({
    editorSessionRef, sourceDatNameRef, viewerCleanupRef, clearAllIntervals, setViewerStreaming,
    setCapabilityWarning, viewerGenerationRef, paintSessionRef, handleViewerMessage, setViewerWs,
    streamCanvasRef, setSkinCreatorError, lastMessageTimeRef, autoRefreshIntervalRef, isDrawingRef,
    pairLoadRef, restorePaintEdits, paintPairRef, setPaintMembers, sourceRequestRef,
    setSkinCreatorLoading, setSelectedVanillaCostume, hasElectron, selectedCharacter, resolveViewerPose,
    initialCostume, updateEditedTextures, setAdoptedRevision, setPendingCheckpoint, stageWorkspaceRef,
    setTextureModels,
  })

  // Close and cleanup
  const closeSkinCreator = async (force = false) => {
    if (isDirty && !force) {
      const confirmed = await appConfirm('You have unsaved changes. Are you sure you want to close?', {
        title: 'Discard Changes',
        confirmText: 'Close',
      })
      if (!confirmed) return false
    }
    playSound('back')
    editorSessionRef.current += 1
    viewerGenerationRef.current += 1
    clearTimeout(pairLoadRef.current?.timeout)
    cancelExportDat(exportDatResolverRef, 'Skin Creator closed during export')

    if (skinCreatorReconnectTimeoutRef.current) {
      clearTimeout(skinCreatorReconnectTimeoutRef.current)
      skinCreatorReconnectTimeoutRef.current = null
    }

    // Clear ping and auto-refresh intervals
    clearAllIntervals()

    setSkinCreatorError('closing')

    // Clean up Electron IPC listener
    viewerCleanupRef.current?.()
    viewerCleanupRef.current = null
    setViewerWs(null)

    // Stop embedded viewer via Electron IPC
    if (hasElectron) {
      try {
        await window.electron.viewerStop(paintSessionRef.current)
      } catch (e) {
        // Ignore errors on cleanup
      }
    }

    // Reset state
    paintSessionRef.current = null
    sourceDatNameRef.current = null
    paintPairRef.current = null
    setPaintMembers([])
    viewerGenerationRef.current += 1
    editedTexturesRef.current = {}
    setSkinCreatorStep('select')
    setVanillaCostumes([])
    setSelectedVanillaCostume(null)
    setSkinCreatorError(null)
    setModelTextures([])
    setTextureModels(null)
    setSelectedTextureIndex(null)
    canvasOwnerRef.current = null
    setCanvasOwner(null)
    canvasWritesRef.current.clear()
    layers.forget()
    setEditedTextures({})
    setIsDirty(false)
    savingRef.current = false
    setIsSaving(false)
    setSkinCreatorReconnecting(false)
    setSkinCreatorReconnectAttempts(0)
    setConnectionFailed(false)
    setViewerStreaming(false)

    // Reset color palette
    palette.clearPaletteState()

    onClose?.()
    return true
  }

  useEffect(() => {
    if (!assistantConnected) return
    assistantEditor.closeHandler.current = closeSkinCreator
    return () => {
      if (assistantEditor.closeHandler.current === closeSkinCreator) assistantEditor.closeHandler.current = null
    }
  })

  // Refresh textures - resend all edited textures to viewer (Electron IPC)
  // Reset view: put the camera back where the model was first framed and
  // drop any animation loaded from the popover (the viewer's "resetView"),
  // then re-push the paint edits so the model shows the current textures.
  const refreshTextures = () => {
    if (hasElectron && viewerWs) {
      window.electron.viewerSend({ type: 'resetView' })
      setSelectedAnim('')
      restorePaintEdits()
    }
  }

  // Handle reconnect after connection failure
  const handleReconnect = async () => {
    if (paintPairRef.current) {
      const session = editorSessionRef.current
      await palette.flushColorAdjustments()
      await cleanupViewerConnection()
      if (session !== editorSessionRef.current) return
      setSkinCreatorLoading(true)
      setConnectionFailed(false)
      setSkinCreatorError(null)
      try { await launchPaintViewer(paintPairRef.current[0]) } catch (error) { failViewer(error) }
      return
    }
    setConnectionFailed(false)
    setSkinCreatorError(null)
    if (initialCostume) {
      startSkinCreatorFromVault(initialCostume)
    } else if (selectedVanillaCostume) {
      startSkinCreatorViewer(selectedVanillaCostume)
    }
  }

  const cleanupViewerConnection = async () => {
    viewerGenerationRef.current += 1
    clearTimeout(pairLoadRef.current?.timeout)
    pairLoadRef.current = null
    cancelExportDat(exportDatResolverRef, 'Viewer session changed during export')
    clearAllIntervals()
    viewerCleanupRef.current?.()
    viewerCleanupRef.current = null
    setViewerWs(null)
    setViewerStreaming(false)
    if (hasElectron) {
      try {
        await window.electron.viewerStop(paintSessionRef.current)
      } catch (e) {
        // Ignore viewer restart cleanup errors
      }
    }
  }

  const handlePoseChange = async (poseName) => {
    if (paintPairRef.current) return // Paired previews use the individual climber scenes.
    setSelectedPoseName(poseName)
    await cleanupViewerConnection()
    setSkinCreatorLoading(true)
    setConnectionFailed(false)
    if (initialCostume) {
      await startSkinCreatorFromVault(initialCostume, poseName)
    } else if (selectedVanillaCostume) {
      await startSkinCreatorViewer(selectedVanillaCostume, poseName)
    }
  }

  useTextureCanvasLoad({
    selectedTextureIndex, modelTextures, paintCanvasRef, editedTextures, canvasWritesRef,
    canvasOwnerRef, viewerGenerationRef, setCanvasOwner, paintPairRef, paintCommand,
    fullTextureRequestRef, failViewer, selectionRef, layers, updateCanvasScale,
  })

  // Warn before leaving with unsaved changes
  useEffect(() => {
    const handleBeforeUnload = (e) => {
      if (isDirty) {
        e.preventDefault()
        e.returnValue = 'You have unsaved changes. Are you sure you want to leave?'
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isDirty])

  const { exportTexture, importTexture } = createTextureFileActions({
    selectedTextureIndex, modelTextures, paintCanvasRef, canvasOwnerRef, selectedTextureId,
    viewerGenerationRef, selectionRevisionRef, selectionRef, layers, saveToUndoStack,
  })

  useEffect(() => {
    const request = assistantEditor?.textureRequest
    if (!request || !assistantConnected) return
    assistantEditor.setTextureRequest(null)
    if (request.texture.id !== selectedTextureId || canvasOwnerRef.current !== selectedTextureId || isSaving || skinCreatorLoading) {
      setSkinCreatorError('The selected texture changed. Choose the target texture and try again.')
      return
    }
    const generation = viewerGenerationRef.current
    const selection = selectionRevisionRef.current
    api.blob(`/api/assistant/files/${request.file.file_id}`).then(blob => {
      if (generation !== viewerGenerationRef.current || selection !== selectionRevisionRef.current || savingRef.current) return
      importTexture({ target: { files: [new File([blob], request.file.name, { type: 'image/png' })], value: '' } })
    }).catch(error => setSkinCreatorError(error.message))
  }, [assistantEditor?.textureRequest, assistantConnected, selectedTextureId, isSaving, skinCreatorLoading])

  const { openSaveModal, handleSaveToVault, handleDownloadDat } = createSaveActions({
    paintPairRef, connectionFailed, editorSessionRef, exportDatResolverRef, paintSessionRef,
    setConnectionFailed, selectedCharacter, setSkinName, setSaveError, setShowSaveModal,
    cancelHighlight, materialColors, skinName, hasElectron, savingRef,
    selectionRevisionRef, setIsSaving, palette, isStage, streamCanvasRef,
    stageWorkspaceRef, setIsDirty, onRefresh, initialCostume, sourceDatNameRef,
    selectedVanillaCostume, selectedPoseName, viewerWs,
  })

  if (!isOpen) return null

  return (
    <>
      <div className={`skin-creator-overlay${skinCreatorStep === 'select' ? ' skin-creator-overlay--select' : ''}`}>
        <div className="skin-creator-modal">
          {/* Header - only shown in edit step */}
          {skinCreatorStep === 'edit' && (
            <SkinCreatorHeader
              title={isStage ? "Stage Creator" : "Skin Creator"}
              assistantAction={assistantConnected ? <button type="button" onClick={assistantEditor.showSidebar}>Randall</button> : null}
              selectedCharacter={selectedCharacter}
              selectedVanillaCostume={selectedVanillaCostume}
              isDirty={isDirty}
              paintMembers={paintMembers}
              busy={skinCreatorLoading || isSaving || connectionFailed || palette.isAnalyzing || palette.isApplying || materialColors.busy || Boolean(materialColors.error)}
              poseOptions={poseOptions}
              selectedPoseName={selectedPoseName}
              defaultPoseName={defaultPoseName}
              onPoseChange={handlePoseChange}
              onSave={openSaveModal}
              onDownload={handleDownloadDat}
              onClose={() => closeSkinCreator()}
            />
          )}

          {skinCreatorStep === 'edit' && skinCreatorError && skinCreatorError !== 'closing' && (
            <div className="skin-creator-error" role="alert">{skinCreatorError}</div>
          )}

          {/* Costume Selection Step */}
          {skinCreatorStep === 'select' && (
            <CostumeSelectStep
              initialCostume={initialCostume}
              onBack={() => closeSkinCreator()}
              vanillaCostumes={vanillaCostumes}
              selectedCharacter={selectedCharacter}
              loading={skinCreatorLoading}
              error={skinCreatorError}
              reconnecting={skinCreatorReconnecting}
              reconnectAttempts={skinCreatorReconnectAttempts}
              maxReconnectAttempts={skinCreatorMaxReconnectAttempts}
              onSelectCostume={startSkinCreatorViewer}
            />
          )}

          {/* Editor Step */}
          {skinCreatorStep === 'edit' && (
            <div className="skin-creator-body">
              {/* Main area: Canvas + Right Panel */}
              <div className="skin-creator-main">
                {/* Center - Paint Canvas */}
                <div className="skin-creator-canvas-area" inert={skinCreatorLoading || isSaving || connectionFailed}>
                  <PaintToolbar
                    undo={undo}
                    redo={redo}
                    canUndo={canvasOwner === selectedTextureId && undoStack.length > 0}
                    canRedo={canvasOwner === selectedTextureId && redoStack.length > 0}
                    drawColor={drawColor}
                    setDrawColor={setDrawColor}
                    activeTool={activeTool}
                    setActiveTool={setActiveTool}
                    brushSize={brushSize}
                    setBrushSize={setBrushSize}
                    replaceTolerance={replaceTolerance}
                    setReplaceTolerance={setReplaceTolerance}
                    selection={selection}
                    clearSelection={clearSelection}
                  />
                  <div
                    ref={canvasContainerRef}
                    className={`skin-creator-canvas tool-${activeTool}${panMode ? " pan-mode" : ""}${panning ? " is-panning" : ""}`}
                    tabIndex={0}
                    aria-label="Texture canvas. Scroll to zoom, Space-drag or middle-drag to pan."
                    onMouseDown={event => { if (!beginPan(event) && !highlighting && canvasOwnerRef.current === selectedTextureId) handlePaintMouseDown(event) }}
                    onMouseMove={event => { if (!isPanning() && !highlighting && canvasOwnerRef.current === selectedTextureId) handlePaintMouseMove(event) }}
                    onMouseUp={handlePaintMouseUp}
                    onMouseLeave={handlePaintMouseUp}
                  >
                    {selectedTextureIndex === null ? (
                      <div className="canvas-placeholder">
                        <span>Paint Canvas</span>
                        <p>Select a texture to start editing</p>
                      </div>
                    ) : (
                      <>
                        <canvas ref={paintCanvasRef} className="paint-canvas" draggable="false"
                          style={paintCursor && !panMode ? { cursor: paintCursor } : undefined} />
                        <SelectionOverlay selection={activeSelection} zoom={zoom}
                          width={selectedTexture?.width} height={selectedTexture?.height} />
                        {/* Floating Import/Export buttons */}
                        <CanvasFloatingActions
                          onImport={importTexture}
                          onExport={exportTexture}
                        />
                      </>
                    )}
                </div>
                  <TextureViewBar
                    modelTextures={modelTextures}
                    selectedTextureIndex={selectedTextureIndex}
                    highlighting={highlighting}
                    flashTexture={flashTexture}
                    selectedTextureId={selectedTextureId}
                    canvasOwner={canvasOwner}
                    hand={hand}
                    setHand={setHand}
                    zoomBy={zoomBy}
                    zoom={zoom}
                    actualSize={actualSize}
                    fit={fit}
                    resetSizes={resetSizes}
                  />
              </div>

                {/* Vertical resize handle between canvas and right panel */}
                <div
                  className="resize-handle vertical"
                  {...separatorProps("rightPanelWidth", "Preview panel width")}
                />

                {/* Right Panel - 3D Preview */}
                <PreviewPanel
                  panelSizes={panelSizes}
                  isStage={isStage}
                  stageAnimation={stageAnimation}
                  paintMembers={paintMembers}
                  refreshTextures={refreshTextures}
                  viewerWs={viewerWs}
                  connectionFailed={connectionFailed}
                  skinCreatorCanvasRef={skinCreatorCanvasRef}
                  viewerStreaming={viewerStreaming}
                  streamCanvasRef={streamCanvasRef}
                  capabilityWarning={capabilityWarning}
                  pendingCheckpoint={pendingCheckpoint}
                  adoptCheckpoint={adoptCheckpoint}
                  setAdoptedRevision={setAdoptedRevision}
                  setPendingCheckpoint={setPendingCheckpoint}
                  animList={animList}
                  skinCreatorLoading={skinCreatorLoading}
                  selectedAnim={selectedAnim}
                  handleReconnect={handleReconnect}
                  skinCreatorReconnecting={skinCreatorReconnecting}
                  skinCreatorReconnectAttempts={skinCreatorReconnectAttempts}
                  skinCreatorMaxReconnectAttempts={skinCreatorMaxReconnectAttempts}
                />
              </div>

              {/* Horizontal resize handle above texture strip */}
              <div
                className="resize-handle horizontal"
                {...separatorProps("textureStripHeight", "Texture browser height")}
              />

              {/* Bottom row - Texture Strip | Color tools */}
              <div className="skin-creator-bottom" style={{ height: panelSizes.textureStripHeight }}>
                <TextureStrip
                  modelTextures={modelTextures}
                  textureModels={textureModels}
                  selectedTextureIndex={selectedTextureIndex}
                  onSelectTexture={index => {
                    if (index === selectedTextureIndex) return
                    isDrawingRef.current = false
                    selectionRevisionRef.current += 1
                    canvasOwnerRef.current = null
                    setCanvasOwner(null)
                    selectionRef.current = textureKey(modelTextures[index])
                    setSelectedTextureIndex(index)
                  }}
                  disabled={skinCreatorLoading || isSaving || connectionFailed}
                  editedTextures={editedTextures}
                />

                {/* Vertical resize handle between texture strip and color tools */}
                <div
                  className="resize-handle vertical"
                  {...separatorProps("colorToolsWidth", "Color tools width")}
                />

                {/* Tool Palette */}
                <ColorToolsPanel
                  panelSizes={panelSizes}
                  skinCreatorLoading={skinCreatorLoading}
                  isSaving={isSaving}
                  connectionFailed={connectionFailed}
                  paletteTab={paletteTab}
                  setPaletteTab={setPaletteTab}
                  palette={palette}
                  paintMembers={paintMembers}
                  materialColors={materialColors}
                  layers={layers}
                  canvasOwner={canvasOwner}
                  selectedTextureId={selectedTextureId}
                  layerAction={layerAction}
                  beginLayerEdit={beginLayerEdit}
                  drawColor={drawColor}
                  setDrawColor={setDrawColor}
                  modelTextures={modelTextures}
                  paletteScope={paletteScope}
                  setPaletteScope={setPaletteScope}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Save Modal */}
      {showSaveModal && (
        <SaveModal
          itemLabel={isStage ? "stage" : "skin"}
          skinName={skinName}
          setSkinName={setSkinName}
          isSaving={isSaving}
          saveError={saveError}
          onSave={handleSaveToVault}
          onClose={() => setShowSaveModal(false)}
        />
      )}
    </>
  )
}
