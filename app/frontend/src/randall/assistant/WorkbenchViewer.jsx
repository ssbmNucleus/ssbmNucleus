import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../shared/transport/api'
import { backendMediaUrl } from '../../shared/config/config'
import { getAnimDisplayName, groupAnimations } from '../../shared/viewer/animationNames'
import { launchPreviewSession } from '../../shared/viewer/viewerPair'
import { newViewerSessionId, viewerCapabilityWarning, viewerSupports } from '../../shared/viewer/viewerStream'
import { handleViewerControlMessage } from '../../shared/viewer/viewerMessages'
import { useViewerSurface } from '../../shared/viewer/useViewerSurface'
import { useViewerInput } from '../../shared/viewer/useViewerInput'
import { cameraPanStep } from '../../shared/viewer/viewerInput'
import { cameraBack, canLoadInPlace, freshCamera, listedAnimation, screenAction, swapPlan, wantedAnimation } from './workbench'
import '../../shared/viewer/viewerSurface.css'

// How long one texture swap may wait for the renderer's reply before the view reloads instead.
const SWAP_REPLY_MS = 15000
// A model swap (loadDat) reads and builds a whole file: give it longer.
const LOAD_REPLY_MS = 60000
// One updateTextures message carries at most this much base64 (the viewer refuses a message over 32 MiB).
const BATCH_CHARS = 16 * 1024 * 1024
// The in-place colour messages and the reply each one waits for.
const COLOUR_REPLIES = { setVertexColors: 'vertexColorsSet', setAnimationColors: 'animationColorsSet',
  setLightColors: 'lightColorsSet' }
// Scene units per pixel of a pan before the renderer's camera is read (cameraPanStep), or from a renderer that
// cannot say: about right for a costume in a pane a few hundred pixels tall.
const PAN_STEP = 0.08

// What the renderer shows: the file, and what it is of.
const shownOf = target => ({ fileId: target.fileId, character: target.character, stageCode: target.stageCode })

async function colourMessages(id) {
  const response = await fetch(backendMediaUrl(`/api/assistant/viewer-updates/${id}`))
  if (!response.ok) throw new Error('The colour change could not be read.')
  const messages = await response.json()
  if (!Array.isArray(messages) || !messages.every(message => COLOUR_REPLIES[message?.type]))
    throw new Error('The colour change could not be read.')
  return messages
}

async function pictureBase64(fileId) {
  const response = await fetch(backendMediaUrl(`/api/assistant/files/${fileId}?preview=1`))
  if (!response.ok) throw new Error('The texture could not be read.')
  const blob = await response.blob()
  const url = await new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(reader.error || new Error('The texture could not be read.'))
    reader.readAsDataURL(blob)
  })
  return String(url).split(',', 2)[1] || ''
}

/** The live 3D view of Randall's newest working file.

    A new checkpoint whose edit changed only textures, material values, or (on a
    renderer that announces protocol 2) vertex colours, colour keys and light
    colours the lab's renderer took in place (the backend says which:
    workbench.swapPlan) is shown by putting those into the renderer already
    running, in a fraction of a second, keeping the camera and the animation
    where the user left them. Anything else (a scenery change, a different file
    of the same kind) is loaded into the running renderer when it takes loadDat
    (workbench.canLoadInPlace: about half a second, camera and animation kept;
    another subject, which is another chat's costume, or another fighter takes a
    fresh camera: workbench.freshCamera);
    otherwise (a renderer that is not up, an older renderer, a stage after a
    costume, a swap or load that fails) the viewer relaunches on the file, as
    every edit used to: 2-5 s of process and GL start-up. The canvas keeps the
    previous frame until the new one paints, so an edit reads as the model
    changing in place rather than the panel blanking. The chosen animation is
    kept across reloads of the same subject (another chat's model starts in
    its pose: workbench.wantedAnimation), and the list shows the animation the renderer has
    loaded, or "Pose" when it has none (another fighter's model has none of the
    last one's). "Pose" in the list puts the model back in its starting pose and
    leaves the camera where the user had it; the reset button puts the camera
    back as it was first framed and plays the chosen animation again (both are
    the renderer's resetView, which does pose and camera together:
    workbench.cameraBack undoes the camera half for Pose). A right-drag pans
    with the model under the cursor (cameraPanStep, from the renderer's camera).

    Off screen (another app tab, the Pictures tab) an idle view stays up, its
    renderer paused, so coming back shows it at once; a model that changed
    meanwhile is shown on the way back, as above (workbench.screenAction). A view
    still loading stops instead and starts again when shown. There is one viewer
    process app-wide and another tab's 3D view replaces this one without telling
    it, so a kept view asks Electron whether it still runs before it paints or
    takes input again, and relaunches when it does not. */
export default function WorkbenchViewer({ model, subject = '', active }) {
  const hasElectron = typeof window !== 'undefined' && !!window.electron?.viewerStart
  const isStage = Boolean(model?.stageCode)
  const containerRef = useRef(null)
  const canvasRef = useRef(null)
  const sessionRef = useRef(null)
  const cleanupRef = useRef(null)
  const handlerRef = useRef(null)
  // The animation the user picked and the subject it was picked on (workbench.wantedAnimation).
  const wantedAnim = useRef({ symbol: '', subject: null })
  const modelRef = useRef(model)
  modelRef.current = model
  // What the model is of (workbenchState's subject key: one chat's costume), and the one the renderer shows.
  const subjectRef = useRef(subject)
  subjectRef.current = subject
  const shownSubjectRef = useRef(null)
  const activeRef = useRef(active)
  activeRef.current = active
  // What the running renderer shows ({fileId, character, stageCode}), whether it is the climbers' pair,
  // whether it is connected, and the texture swaps waiting on its replies (oldest first).
  const shownRef = useRef(null)
  const pairRef = useRef(false)
  const connectedRef = useRef(false)
  const acksRef = useRef([])
  const swappingRef = useRef(false)
  const pendingRef = useRef(false)
  // The running renderer's `capabilities` message (null: none yet, or a pre-protocol viewer) and the
  // animation it plays (a reload keeps it; the animation list then need not load it again).
  const capsRef = useRef(null)
  const animRef = useRef('')
  // The running renderer's camera as last read (exportScene: z and fovRadians set how far a pan moves).
  const cameraRef = useRef(null)
  // Whether the view was on screen at the last check (going off and coming back are what count), and whether it
  // is unmounted (work still in flight then never starts a viewer).
  const wasActiveRef = useRef(false)
  const goneRef = useRef(false)
  const [sessionId, setSessionId] = useState(null)
  // Kept up off screen, or back on screen and not yet confirmed as still the app's renderer: its surface and
  // input stay off, so nothing it sends can reach another tab's viewer.
  const [kept, setKept] = useState(false)
  const [connected, setConnectedState] = useState(false)
  const [streaming, setStreaming] = useState(null)
  const [loading, setLoading] = useState(false)
  const [painted, setPainted] = useState(false)
  const [error, setError] = useState('')
  const [warning, setWarning] = useState('')
  const [anims, setAnims] = useState([])
  const [anim, setAnim] = useState('')
  const [playing, setPlaying] = useState(false)
  const setConnected = value => { connectedRef.current = value; setConnectedState(value) }

  const failAcks = reason => { for (const ack of acksRef.current.splice(0)) ack.reject(new Error(reason)) }

  const stop = useCallback(() => {
    const previous = sessionRef.current
    sessionRef.current = null
    shownRef.current = null
    shownSubjectRef.current = null
    setKept(false)
    failAcks('The 3D view stopped.')
    cleanupRef.current?.(); cleanupRef.current = null
    if (previous && window.electron?.viewerStop) Promise.resolve(window.electron.viewerStop(previous)).catch(() => {})
  }, [])

  // The running renderer's camera, for the pan step and for Pose. -> the camera, or null (an older renderer, no
  // answer, or another view's renderer meanwhile).
  const readCamera = useCallback(async () => {
    const id = sessionRef.current
    try {
      const scene = await window.electron?.viewerExportScene?.()
      if (sessionRef.current !== id || !scene?.camera) return null
      cameraRef.current = scene.camera
      return scene.camera
    } catch { return null }
  }, [])

  // The renderer now shows `about`. Another subject than the one an animation was picked on starts in its pose, also
  // when its chat is opened again later (as it starts with its own camera).
  const showing = useCallback(about => {
    shownSubjectRef.current = about
    if (wantedAnim.current.subject !== about) wantedAnim.current = { symbol: '', subject: about }
  }, [])

  const start = useCallback(async () => {
    stop()
    capsRef.current = null
    animRef.current = ''
    cameraRef.current = null
    // A new renderer has no animation loaded until the list arrives and the chosen one is loaded again.
    setAnim(''); setPlaying(false)
    const target = modelRef.current
    const about = subjectRef.current
    if (!target?.fileId || !hasElectron) return
    const stage = Boolean(target.stageCode)
    const id = newViewerSessionId()
    sessionRef.current = id
    const current = () => sessionRef.current === id
    // The animation list stays until the new one arrives: removing the controls
    // row would resize the canvas, and a resize wipes the frame being held.
    setConnected(false); setLoading(true); setError(''); setWarning('')
    if (stage) setAnims([])
    try {
      const fileId = target.fileId
      const paths = await api.post('/viewer/paths-checkpoint', stage
        ? { stageCode: target.stageCode, fileId }
        : { character: target.character, fileId })
      if (!current()) return
      const result = await launchPreviewSession({
        electron: window.electron, isCurrent: current,
        paths: { datFile: paths.datFile, sceneFile: paths.sceneFile, ajFile: paths.ajFile, dataFile: paths.dataFile,
          logsPath: paths.logsPath, members: paths.members, viewerSessionId: id },
        onMessage: message => handlerRef.current?.(message),
        onSubscribe: cleanup => { cleanupRef.current = cleanup },
        getCanvas: () => document.hidden ? null : canvasRef.current,
        onFrameError: failure => setError(failure.message),
      })
      if (!result || !current()) return
      pairRef.current = Boolean(paths.members)
      shownRef.current = shownOf(target)
      showing(about)
      setSessionId(id)
      setStreaming(!!result.streaming)
      setConnected(result.connected !== false)
      setLoading(false); setPainted(true)
      if (!stage) window.electron.viewerGetAnimList()
      readCamera()
    } catch (failure) {
      if (!current()) return
      setError(failure.message || 'The 3D view could not start.')
      setLoading(false)
    }
  }, [hasElectron, stop, readCamera, showing])

  // One command at a time (the renderer answers in order): `type` is the reply it waits for.
  const waitAck = (type, ms = SWAP_REPLY_MS) => new Promise((resolve, reject) => {
    const ack = { type, resolve, reject }
    const timer = setTimeout(() => {
      acksRef.current = acksRef.current.filter(item => item !== ack)
      reject(new Error('The 3D view did not answer.'))
    }, ms)
    ack.resolve = value => { clearTimeout(timer); resolve(value) }
    ack.reject = reason => { clearTimeout(timer); reject(reason) }
    acksRef.current.push(ack)
  })

  // One command to the running renderer and its reply.
  const command = async (message, replyType, ms) => {
    const reply = waitAck(replyType, ms)
    const sent = await window.electron.viewerSend(message)
    if (sent === false) failAcks('The 3D view did not take the change.')
    return reply
  }

  const supports = type => viewerSupports(capsRef.current, type)
  const requestId = () => newViewerSessionId()

  // The changed textures, colour messages and material values into the running renderer; on any failure,
  // reload the file.
  const swap = async (target, plan) => {
    const id = sessionRef.current
    const about = subjectRef.current
    swappingRef.current = true
    setLoading(true)
    try {
      if (supports('updateTextures') && plan.textures.length > 1) {
        // One batch (decoded and encoded in parallel by the renderer), split only when very large.
        let batch = [], size = 0
        const flush = async () => {
          if (!batch.length) return
          await command({ type: 'updateTextures', requestId: requestId(), textures: batch }, 'texturesUpdated')
          batch = []; size = 0
        }
        for (const texture of plan.textures) {
          const data = await pictureBase64(texture.file_id)
          if (sessionRef.current !== id) return
          if (batch.length && size + data.length > BATCH_CHARS) await flush()
          batch.push({ index: texture.index, data }); size += data.length
        }
        await flush()
        if (sessionRef.current !== id) return
      } else {
        for (const texture of plan.textures) {
          const data = await pictureBase64(texture.file_id)
          if (sessionRef.current !== id) return
          await command({ type: 'updateTexture', index: texture.index, data }, 'textureUpdated')
          if (sessionRef.current !== id) return
        }
      }
      // Vertex colours, colour keys and lights, in the order the edits made them, before material values.
      for (const colours of plan.colours || []) {
        const messages = await colourMessages(colours.id)
        if (sessionRef.current !== id) return
        for (const message of messages) {
          await command({ ...message, requestId: requestId() }, COLOUR_REPLIES[message.type])
          if (sessionRef.current !== id) return
        }
      }
      // Colours go in one batch (#rrggbbaa); opacity and shininess field by field.
      const colours = plan.materials.filter(edit => typeof edit.value === 'string')
      if (colours.length) await command({ type: 'setMaterialColors', edits: colours }, 'materials')
      for (const edit of plan.materials.filter(item => typeof item.value !== 'string')) {
        if (sessionRef.current !== id) return
        await command({ type: 'setMaterial', id: edit.id, field: edit.field, value: edit.value }, 'materials')
      }
      if (sessionRef.current !== id) return
      shownRef.current = { fileId: target.fileId, character: target.character, stageCode: target.stageCode }
      showing(about)
      setLoading(false)
    } catch {
      // A reload shows the newest model, so a change that arrived meanwhile is covered too.
      if (sessionRef.current === id) { swappingRef.current = false; pendingRef.current = false; await start(); return }
    } finally {
      settle()
    }
  }

  // The model's file loaded into the running renderer (loadDat: camera and animation kept, but a fresh camera for
  // another subject or fighter, and the pose for another subject); on any failure (a pair, a file the renderer
  // refuses, no answer), a relaunch.
  const loadInPlace = async target => {
    const id = sessionRef.current
    const about = subjectRef.current
    const reframe = freshCamera(shownRef.current && { ...shownRef.current, subject: shownSubjectRef.current },
      { subject: about, character: target.character, stageCode: target.stageCode })
    const current = () => sessionRef.current === id
    swappingRef.current = true
    setLoading(true); setError('')
    try {
      const fileId = target.fileId
      const paths = await api.post('/viewer/paths-checkpoint', target.stageCode
        ? { stageCode: target.stageCode, fileId }
        : { character: target.character, fileId })
      if (!current()) return
      if (paths.members) throw new Error('A pair loads two files.')
      // Another chat's model starts in its pose. The renderer carries an animation over to a file whose fighter has
      // it, so the one playing is stopped first (resetView: the pose; the camera is reframed by the load anyway).
      if (about && shownSubjectRef.current !== about && animRef.current && supports('resetView')) {
        await command({ type: 'resetView' }, 'cameraReset')
        if (!current()) return
        animRef.current = ''
      }
      const reply = await command({ type: 'loadDat', requestId: requestId(), datFile: paths.datFile,
        sceneFile: paths.sceneFile || '', ajFile: paths.ajFile || '', dataFile: paths.dataFile || '',
        ...(reframe ? { reframe: true } : {}) },
      'datLoaded', LOAD_REPLY_MS)
      if (!current()) return
      shownRef.current = shownOf(target)
      showing(about)
      // A reframed load starts the view over, its toggles too (preview.28: the next chat's model stood on black
      // with no grid): set them as on a renderer's `ready`.
      if (reply.reframed) {
        window.electron.viewerSetCspMode(false)
        window.electron.viewerSetGrid(!target.stageCode)
        window.electron.viewerSetBackground(!target.stageCode)
      }
      // The renderer keeps the animation only when the new file's fighter has it; with none it stands in its pose.
      animRef.current = reply.animSymbol || ''
      setAnim(animRef.current); setPlaying(Boolean(reply.animSymbol && reply.animation?.playing))
      setLoading(false); setPainted(true)
      if (!target.stageCode) window.electron.viewerGetAnimList()
      if (reply.reframed) readCamera()
    } catch {
      if (current()) { swappingRef.current = false; pendingRef.current = false; await start(); return }
    } finally {
      settle()
    }
  }

  // The renderer's resetView puts the model back as it first framed it: its starting pose and that camera. With
  // `again` (the reset button) the animation it was showing is then loaded again, so only the camera is reset;
  // without (Pose in the list) the pose is what was asked for and no animation is wanted any more, and the camera is
  // put back where the user had it (cameraBack: read before and after). A renderer that does not take resetView, or
  // does not answer, is relaunched: a new renderer starts framed and in its pose, then loads the wanted animation.
  const resetView = async ({ again }) => {
    const id = sessionRef.current
    if (!id || swappingRef.current) return
    const chosen = again ? animRef.current : ''
    wantedAnim.current = { symbol: chosen, subject: subjectRef.current }
    if (!supports('resetView')) { await start(); return }
    swappingRef.current = true
    try {
      const before = again ? null : await readCamera()
      if (sessionRef.current !== id) return
      await command({ type: 'resetView' }, 'cameraReset')
      if (sessionRef.current !== id) return
      animRef.current = ''
      setAnim(''); setPlaying(false)
      if (chosen && anims.includes(chosen)) window.electron.viewerLoadAnim(chosen)
      const home = await readCamera()
      const back = before && home && cameraBack(before, home)
      if (back && sessionRef.current === id) {
        await Promise.resolve(window.electron.viewerCamera(...back)).catch(() => {})
        readCamera()
      }
    } catch {
      if (sessionRef.current === id) { swappingRef.current = false; pendingRef.current = false; await start(); return }
    } finally {
      settle()
    }
  }

  // A swap, load or check is over: a change asked for meanwhile (show() found it busy) is shown now, also when
  // the work stopped early because the view was stopped and shown again meanwhile.
  const settle = () => {
    swappingRef.current = false
    if (pendingRef.current) { pendingRef.current = false; show() }
  }

  // Bring the view to the newest model: a swap when the plan allows it, else the file loaded into the running
  // renderer when it can, else a relaunch.
  const show = () => {
    const target = modelRef.current
    if (!activeRef.current || goneRef.current) return   // hidden meanwhile (it starts again when shown) or unmounted
    if (swappingRef.current) { pendingRef.current = true; return }
    if (shownRef.current?.fileId && shownRef.current.fileId === target?.fileId) return
    const live = { connected: connectedRef.current && Boolean(sessionRef.current), pair: pairRef.current, supports }
    const plan = swapPlan(shownRef.current, target, live)
    if (plan) swap(target, plan)
    else if (canLoadInPlace(shownRef.current, target, live)) loadInPlace(target)
    else start()
  }

  // Back on screen after being kept: the same renderer, at once, when it is still this view's; else a relaunch.
  // Then the newest model, which may have changed meanwhile.
  const resume = async () => {
    const id = sessionRef.current
    swappingRef.current = true
    let running = false
    try { running = await window.electron.viewerRunning?.(id) === true } catch { /* relaunched below */ }
    // Off screen again (stopped) or relaunched meanwhile: only a change asked for meanwhile is shown.
    if (sessionRef.current !== id) { settle(); return }
    swappingRef.current = false
    pendingRef.current = false
    if (!running || !connectedRef.current) { stop(); setConnected(false) }
    else setKept(false)
    show()
  }

  handlerRef.current = message => {
    const ack = acksRef.current[0]
    if (ack && (message.type === ack.type || message.type === 'commandError')) {
      acksRef.current.shift()
      if (message.type === ack.type && message.success !== false) ack.resolve(message)
      else ack.reject(new Error(message.error || 'The 3D view could not take the change.'))
      return
    }
    if (handleViewerControlMessage(message, {
      onError: text => setError(text),
      onAnimationFrame: update => { if ('playing' in update) setPlaying(update.playing) },
    })) return
    switch (message.type) {
      case 'ready':
        setConnected(true); setLoading(false); setPainted(true)
        window.electron.viewerSetCspMode(false)
        window.electron.viewerSetGrid(!isStage)
        window.electron.viewerSetBackground(!isStage)
        readCamera()
        break
      case 'capabilities':
        capsRef.current = message
        setWarning(viewerCapabilityWarning(message, { cspMode: false }))
        break
      case 'disconnected':
        setConnected(false); setLoading(false)
        failAcks('The 3D view stopped.')
        // A view kept off screen relaunches when shown instead.
        if (activeRef.current) setError(message.error || 'The 3D view stopped. Retry to reload it.')
        break
      case 'animList': {
        const symbols = message.symbols || []
        setAnims(symbols)
        // Keep the animation the user was watching when the file reloads (a loadDat already kept it), on its subject.
        const wanted = wantedAnimation(wantedAnim.current, subjectRef.current)
        if (wanted && symbols.includes(wanted) && animRef.current !== wanted) window.electron.viewerLoadAnim(wanted)
        break
      }
      case 'animLoaded':
        animRef.current = message.symbol || ''
        setAnim(message.symbol); setPlaying(true)
        break
    }
  }

  // Before the effect below: on a remount (StrictMode runs every effect twice) the view must be live again before
  // it is shown.
  useEffect(() => {
    goneRef.current = false
    return () => { goneRef.current = true; stop() }
  }, [stop])
  useEffect(() => {
    const action = screenAction({ active, wasActive: wasActiveRef.current, session: Boolean(sessionRef.current),
      shown: Boolean(shownRef.current), connected: connectedRef.current, streaming: streaming === true,
      busy: swappingRef.current })
    wasActiveRef.current = active
    if (action === 'keep') setKept(true)
    else if (action === 'stop') { stop(); setConnected(false); setLoading(false) }
    else if (action === 'resume') resume()
    else show()
    // show/stop/resume read refs; the view follows what it shows, not their identities.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, model?.fileId, model?.character, model?.stageCode])

  // A kept view sends nothing (no resize, show or camera) until it is confirmed as still the app's renderer.
  const live = connected && !kept
  useViewerSurface({ containerRef, canvasRef, streaming, connected: live, sessionId, visible: active,
    onError: failure => setError(failure.message) })
  // A pan keeps the model under the cursor: the renderer's camera says how far one pixel is at the model.
  useViewerInput({ containerRef, enabled: hasElectron && live && active, sessionId, zoomScale: 0.1,
    panStep: () => cameraPanStep(cameraRef.current, containerRef.current?.clientWidth,
      containerRef.current?.clientHeight) ?? PAN_STEP,
    onError: failure => setError(failure.message) })

  if (!hasElectron) return <div className="workbench-empty">
    <p>The 3D view needs the Nucleus desktop app.</p>
  </div>

  const groups = groupAnimations(anims)
  // What the list shows is what the renderer has loaded; nothing loaded is the pose, and has nothing to play.
  const shownAnim = listedAnimation(anims, anim)
  return <div className="workbench-viewer">
    <div ref={containerRef} className="workbench-viewport viewer-canvas-surface" tabIndex={0}
      aria-label={`3D view of ${isStage ? 'the stage' : 'the costume'}. Drag to rotate, right-drag to pan, scroll to zoom.`}>
      <canvas ref={canvasRef} className="viewer-stream-canvas" />
      {warning && <div className="viewer-capability-warning" role="status">{warning}</div>}
      {loading && !error && (painted
        ? <div className="workbench-badge" role="status"><span className="assistant-work-pulse" aria-hidden="true"><i /></span>Updating</div>
        : <div className="workbench-status" role="status"><div className="mv-spinner" /><p>Loading the 3D view…</p></div>)}
      {error && <div className="workbench-status workbench-status--error" role="alert">
        <p>{error}</p><button type="button" className="assistant-secondary" onClick={start}>Retry</button></div>}
    </div>
    {!isStage && anims.length > 0 && <div className="workbench-controls">
      <button type="button" className="workbench-play" disabled={!live || !shownAnim}
        aria-label={playing && shownAnim ? 'Pause' : 'Play'}
        onClick={() => { window.electron.viewerAnimToggle(); setPlaying(value => !value) }}>
        {playing && shownAnim
          ? <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 4h4v16H6zm8 0h4v16h-4z"/></svg>
          : <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.14v14l11-7z"/></svg>}
      </button>
      <select aria-label="Animation" value={shownAnim} disabled={!live} onChange={event => {
        if (event.target.value) {
          wantedAnim.current = { symbol: event.target.value, subject: subjectRef.current }
          window.electron.viewerLoadAnim(event.target.value)
        } else resetView({ again: false })
      }}>
        <option value="">Pose</option>
        {Object.entries(groups).map(([group, symbols]) => <optgroup key={group} label={group}>
          {symbols.map(symbol => <option key={symbol} value={symbol}>{getAnimDisplayName(symbol)}</option>)}
        </optgroup>)}
      </select>
      <button type="button" className="workbench-play" disabled={!live} aria-label="Reset the view" title="Reset the view"
        onClick={() => resetView({ again: true })}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M17.65 6.35A7.95 7.95 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z"/></svg>
      </button>
    </div>}
  </div>
}
