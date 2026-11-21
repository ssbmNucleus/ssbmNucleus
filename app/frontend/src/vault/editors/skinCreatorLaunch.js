import { api } from '../../shared/transport/api'
import { resolvePaintSource, launchPaintViewerSession, viewerErrorMessage } from '../../shared/viewer/viewerSession'
import { createPaintPair } from './paintPair'
import { launchTextureModels } from './textureSections'

// Opening something in the paint viewer: a vanilla costume, a vault costume or
// stage, or Randall's latest checkpoint of the costume being edited. Each
// resolves the files, then starts a fresh viewer session on them. Built each
// render from that render's state, refs and helpers, as the inline functions were.
export function createViewerLaunchers({
  editorSessionRef, sourceDatNameRef, viewerCleanupRef, clearAllIntervals, setViewerStreaming,
  setCapabilityWarning, viewerGenerationRef, paintSessionRef, handleViewerMessage, setViewerWs,
  streamCanvasRef, setSkinCreatorError, lastMessageTimeRef, autoRefreshIntervalRef, isDrawingRef,
  pairLoadRef, restorePaintEdits, paintPairRef, setPaintMembers, sourceRequestRef,
  setSkinCreatorLoading, setSelectedVanillaCostume, hasElectron, selectedCharacter, resolveViewerPose,
  initialCostume, updateEditedTextures, setAdoptedRevision, setPendingCheckpoint, stageWorkspaceRef,
  setTextureModels,
}) {
  const launchPaintViewer = async (data, pose = null) => {
    const session = editorSessionRef.current
    sourceDatNameRef.current = (data.datFile || '').split(/[\\/]/).pop() || null
    viewerCleanupRef.current?.()
    clearAllIntervals()
    setViewerStreaming(null)
    setCapabilityWarning('')
    const generation = ++viewerGenerationRef.current
    paintSessionRef.current = `skin-${Date.now()}-${session}-${generation}`
    // Which model draws each texture, for the strip's sections (textureSections).
    setTextureModels(launchTextureModels(data, data.memberId ? paintPairRef.current : null))
    const result = await launchPaintViewerSession({
      electron: window.electron,
      isCurrent: () => session === editorSessionRef.current && generation === viewerGenerationRef.current,
      onMessage: handleViewerMessage,
      onSubscribe: cleanup => {
        viewerCleanupRef.current = cleanup
        setViewerWs({ cleanup, viewerSessionId: paintSessionRef.current, connected: false })
      },
      getCanvas: () => document.hidden ? null : streamCanvasRef.current,
      onFrameError: error => setSkinCreatorError(error.message),
      paths: {
        viewerSessionId: paintSessionRef.current,
        datFile: data.datFile,
        sceneFile: pose?.sceneFile || data.sceneFile,
        ajFile: data.ajFile,
        dataFile: data.dataFile,
        logsPath: data.logsPath
      }
    })
    if (result === null) return
    setViewerStreaming(!!result.streaming)
    setViewerWs(current => ({ ...current, connected: true }))
    lastMessageTimeRef.current = Date.now()
    clearAllIntervals()
    autoRefreshIntervalRef.current = setInterval(() => {
      if (isDrawingRef.current) return
      if (!pairLoadRef.current) restorePaintEdits()
    }, 5000)
  }

  const preparePaintPair = (data) => {
    if (!data.members) return data
    const members = createPaintPair(data.members)
    paintPairRef.current = members
    setPaintMembers(members)
    return members[0]
  }

  // Start viewer with selected costume (Electron IPC)
  const startSkinCreatorViewer = async (costume, poseNameOverride) => {
    const session = editorSessionRef.current
    const requestId = ++sourceRequestRef.current
    const isCurrent = () => session === editorSessionRef.current && requestId === sourceRequestRef.current
    try {
      setSkinCreatorLoading(true)
      setSkinCreatorError(null)
      setSelectedVanillaCostume(costume)

      if (!hasElectron) {
        throw new Error('Electron environment required for embedded viewer')
      }

      // Get file paths from Flask (no viewer spawning)
      const source = await resolvePaintSource(
        () => api.post('/viewer/paths-vanilla', {
          character: selectedCharacter, costumeCode: costume.code,
          paintPair: ['Ice Climbers', 'Nana'].includes(selectedCharacter)
        }),
        () => resolveViewerPose(selectedCharacter, poseNameOverride),
        isCurrent
      )
      if (!source) return
      await launchPaintViewer(preparePaintPair(source.data), source.pose)

    } catch (err) {
      if (!isCurrent()) return
      setSkinCreatorError(err.message)
      setSkinCreatorLoading(false)
    }
  }

  // Randall edits the same costume in its own session and checkpoints a
  // working DAT after each edit. Adopting it shows that edit here live; the
  // user's own unsaved paint is never thrown away for it (see the effect
  // below, which only adopts while there is none).
  const adoptCheckpoint = async (checkpoint) => {
    const character = initialCostume?.character || selectedCharacter
    if (!character || !checkpoint?.file?.file_id) return
    const session = editorSessionRef.current
    const requestId = ++sourceRequestRef.current
    const isCurrent = () => session === editorSessionRef.current && requestId === sourceRequestRef.current
    try {
      setSkinCreatorLoading(true)
      const source = await resolvePaintSource(
        () => api.post('/viewer/paths-checkpoint', { character, fileId: checkpoint.file.file_id }),
        () => resolveViewerPose(character),
        isCurrent
      )
      if (!source) return
      // Randall's DAT already contains its edits; local paint state would
      // otherwise be re-applied over them by the 5s restore.
      updateEditedTextures({})
      setAdoptedRevision(checkpoint.revision || 0)
      setPendingCheckpoint(null)
      await launchPaintViewer(preparePaintPair(source.data), source.pose)
    } catch (err) {
      if (!isCurrent()) return
      setSkinCreatorError(viewerErrorMessage(err, false))
      setSkinCreatorLoading(false)
    }
  }

  // Start from vault costume (for editing existing costumes) - Electron IPC
  const startSkinCreatorFromVault = async (costume, poseNameOverride) => {
    console.log('[SkinCreator] startSkinCreatorFromVault called with:', costume)
    const session = editorSessionRef.current
    const requestId = ++sourceRequestRef.current
    const isCurrent = () => session === editorSessionRef.current && requestId === sourceRequestRef.current
    try {
      const character = costume.character || selectedCharacter
      if (!character) {
        throw new Error('No character specified')
      }

      if (!hasElectron) {
        throw new Error('Electron environment required for embedded viewer')
      }

      setSkinCreatorLoading(true)
      setSkinCreatorError(null)
      setSelectedVanillaCostume({ code: costume.id, colorName: costume.color })

      if (costume.stageCode) {
        const data = await api.post('/stage-editor/open', { stageCode: costume.stageCode, variantId: costume.variantId || undefined })
        if (!isCurrent()) return
        stageWorkspaceRef.current = data
        sourceDatNameRef.current = data.datName
        await launchPaintViewer({ ...data, datFile: data.datFile })
        sourceDatNameRef.current = data.datName
        return
      }
      // Get file paths from Flask (no viewer spawning)
      const source = await resolvePaintSource(
        () => api.post('/viewer/paths-vault', {
          character: character, costumeId: costume.id,
          paintPair: ['Ice Climbers', 'Nana'].includes(character)
        }),
        () => resolveViewerPose(character, poseNameOverride),
        isCurrent
      )
      if (!source) return
      await launchPaintViewer(preparePaintPair(source.data), source.pose)

    } catch (err) {
      if (!isCurrent()) return
      console.error('[SkinCreator] Error in startSkinCreatorFromVault:', err)
      setSkinCreatorError(viewerErrorMessage(err, Boolean(costume.stageCode)))
      setSkinCreatorLoading(false)
    }
  }

  return { launchPaintViewer, startSkinCreatorViewer, adoptCheckpoint, startSkinCreatorFromVault }
}
