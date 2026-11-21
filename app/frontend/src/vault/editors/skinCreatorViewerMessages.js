import { viewerCapabilityWarning } from '../../shared/viewer/viewerStream'
import { handleViewerControlMessage } from '../../shared/viewer/viewerMessages'
import { settleExportDat } from './datUtils'
import { normalizePaintTextures, isCurrentTextureReply } from './paintProtocol'

// The Skin Creator's side of the paint-viewer protocol: what the editor does
// with each message the viewer sends (texture lists, full-resolution textures,
// ready / pair loaded, exports, animation and capability notices). Built each
// render from that render's state, refs and helpers, as the inline handler was.
export function createViewerMessageHandler({
  lastMessageTimeRef, materialColors, isStage, stageTextureReads, viewerGenerationRef,
  setSkinCreatorError, setStageAnimation, setAnimList, setSelectedAnim, setCapabilityWarning,
  failViewer, paintPairRef, paintSessionRef, textureListRequestRef, setModelTextures,
  setSelectedTextureIndex, fullTextureRequestRef, selectionRef, editedTexturesRef, isDrawingRef,
  savingRef, paintCanvasRef, layers, canvasOwnerRef, setCanvasOwner,
  updateCanvasScale, readyGenerationRef, setSkinCreatorStep, setConnectionFailed, paintCommand,
  pairLoadRef, setSkinCreatorLoading, restorePaintEdits, requestPaintTextures, activeStartPoseRef,
  exportDatResolverRef,
}) {
  return (msg) => {
    lastMessageTimeRef.current = Date.now()
    if (materialColors.receive(msg)) return
    if (isStage && msg.type === 'fullTexture') {
      const pending = stageTextureReads.current.get(msg.index)
      if (pending) {
        clearTimeout(pending.timer); stageTextureReads.current.delete(msg.index)
        if (msg.error || !msg.data || pending.generation !== viewerGenerationRef.current) pending.reject(new Error(msg.error || 'Stage session changed'))
        else pending.resolve(`data:image/png;base64,${msg.data}`)
      }
    }
    if (handleViewerControlMessage(msg, { onError: setSkinCreatorError, onAnimationFrame: update => setStageAnimation(previous => ({ ...previous, ...update })) })) return
    if (msg.type === 'animList') { setAnimList(Array.isArray(msg.symbols) ? msg.symbols : []); return }
    if (msg.type === 'animLoaded') {
      if (msg.success !== false && msg.symbol) {
        setSelectedAnim(msg.symbol)
        setStageAnimation(previous => ({ ...previous, frame: 0, frameCount: msg.frameCount || 0 }))
      }
      return
    }

    if (msg.type === 'capabilities') {
      setCapabilityWarning(viewerCapabilityWarning(msg))
      return
    }
    if (msg.supported === false) {
      setSkinCreatorError(msg.error || `This viewer does not support ${msg.command || msg.type}.`)
      return
    }
    if (msg.type === 'disconnected') {
      failViewer(new Error(msg.error || 'Viewer connection lost. Your paint edits are retained.'))
      return
    }
    if (paintPairRef.current && msg.type !== 'ready' && msg.sessionId !== paintSessionRef.current) return
    if (msg.type === 'textureList') {
      if (paintPairRef.current && msg.requestId !== textureListRequestRef.current) return
      if (msg.success === false || msg.error) { failViewer(new Error(msg.error || 'Could not read textures')); return }
      try {
        const textures = normalizePaintTextures(msg.textures, !!paintPairRef.current)
        setModelTextures(textures)
        setSelectedTextureIndex(index => textures.length ? (index ?? 0) : null)
      } catch (error) { failViewer(error) }
    } else if (msg.type === 'fullTexture') {
      const pending = fullTextureRequestRef.current
      if (!pending || !isCurrentTextureReply(msg, pending) || pending.generation !== viewerGenerationRef.current ||
          selectionRef.current !== pending.textureId || pending.received || pending.decoding) return
      if (msg.error || msg.success === false || !msg.data) {
        pending.fail(new Error(msg.error || 'Could not read the full-resolution texture.'))
        return
      }
      pending.decoding = true
      const img = new Image()
      img.onload = () => {
        if (pending.generation !== viewerGenerationRef.current || selectionRef.current !== pending.textureId ||
            fullTextureRequestRef.current !== pending || editedTexturesRef.current[pending.textureId] ||
            isDrawingRef.current || savingRef.current) return
        if (img.naturalWidth !== pending.width || img.naturalHeight !== pending.height ||
            msg.width !== pending.width || msg.height !== pending.height) {
          pending.fail(new Error('The viewer returned an unexpected texture size. Reconnect to retry.'))
          return
        }
        const canvas = paintCanvasRef.current
        if (!canvas) return
        canvas.width = msg.width
        canvas.height = msg.height
        const ctx = canvas.getContext('2d')
        ctx.imageSmoothingEnabled = false
        ctx.drawImage(img, 0, 0)
        // Unedited textures start from the viewer's original pixels. Returning
        // to one must preserve any session layer stack already built on them.
        layers.adoptCanvas(pending.textureId, canvas)
        canvasOwnerRef.current = pending.textureId
        setCanvasOwner(pending.textureId)
        pending.received = true
        clearTimeout(pending.timeout)
        updateCanvasScale(canvas, msg.width, msg.height)
      }
      img.onerror = () => pending.fail(new Error('Could not decode the full-resolution texture. Reconnect to retry.'))
      img.src = `data:image/png;base64,${msg.data}`

    } else if (msg.type === 'ready') {
      const generation = viewerGenerationRef.current
      if (readyGenerationRef.current === generation) return
      readyGenerationRef.current = generation
      setSkinCreatorStep('edit')
      setConnectionFailed(false)
      window.electron.viewerSetCspMode(false)
      window.electron.viewerSetGrid(!isStage)
      window.electron.viewerSetBackground(!isStage)
      if (paintPairRef.current) {
        const command = paintCommand({ type: 'loadPaintPair', members: paintPairRef.current.map(
          ({ memberId, datFile, sceneFile, dataFile }) => ({ memberId, datFile, sceneFile, dataFile })) })
        clearTimeout(pairLoadRef.current?.timeout)
        pairLoadRef.current = { requestId: command.requestId,
          timeout: setTimeout(() => { if (generation === viewerGenerationRef.current) failViewer(new Error('Loading Popo and Nana timed out. Reconnect to retry.')) }, 30000) }
        Promise.resolve(window.electron.viewerSend(command)).then(sent => {
          if (sent === false) throw new Error('Viewer disconnected before loading both climbers')
        }).catch(error => { if (generation === viewerGenerationRef.current) failViewer(error) })
        return
      }
      setSkinCreatorLoading(false)
      restorePaintEdits()
      requestPaintTextures()
      setAnimList([]); setSelectedAnim('')
      if (!isStage) window.electron.viewerSend({ type: 'getAnimList' })
      if (activeStartPoseRef.current?.animSymbol) {
        window.electron.viewerLoadAnim(activeStartPoseRef.current.animSymbol)
      }
    } else if (msg.type === 'paintPairLoaded') {
      if (msg.requestId !== pairLoadRef.current?.requestId) return
      clearTimeout(pairLoadRef.current.timeout)
      pairLoadRef.current = null
      if (!msg.success) { failViewer(new Error(msg.error || 'Could not load both climbers.')); return }
      restorePaintEdits()
      requestPaintTextures()
      setSkinCreatorLoading(false)
      setConnectionFailed(false)
    } else if (msg.type === 'exportDat' || msg.type === 'exportPaintPair') {
      settleExportDat(exportDatResolverRef, msg)
    } else if (msg.type === 'textureUpdated' && (msg.success === false || msg.error)) {
      failViewer(new Error(msg.error || `Could not update ${msg.memberId || 'the'} texture`))
    } else if (msg.type === 'animLoaded') {
      const pose = activeStartPoseRef.current
      if (pose?.animSymbol && msg.symbol === pose.animSymbol) {
        window.electron.viewerAnimSetFrame(pose.frame || 0)
        window.electron.viewerAnimPause()
      }
    }
  }
}
