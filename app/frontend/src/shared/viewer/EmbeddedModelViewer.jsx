import { useState, useEffect, useRef, useCallback, forwardRef, useImperativeHandle } from 'react'
import { createPortal } from 'react-dom'
import './EmbeddedModelViewer.css'
import { getAppContentPortalTarget } from '../ui/appContentPortal'
import { CloseIcon } from '../ui/Icons'
import { launchPreviewSession } from './viewerPair'
import { newViewerSessionId, viewerCapabilityWarning } from './viewerStream'
import { handleViewerControlMessage } from './viewerMessages'
import { useViewerSurface } from './useViewerSurface'
import { useViewerInput } from './useViewerInput'
import { cameraPanStep } from './viewerInput'
import './viewerSurface.css'

// Scene units per pixel of a pan before the renderer's camera is read (cameraPanStep), or from a renderer that
// cannot say: about right for a costume in a pane a few hundred pixels tall (the workbench's too).
const PAN_STEP = 0.08

/**
 * Embedded 3D Model Viewer Component
 * Native HSDRawViewer renders into an Electron canvas by default.
 * The explicit legacy embedded transport still supports a native window.
 */

console.log('[EmbeddedModelViewer] Module loaded')

// SVG Icons
const PlayIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
    <path d="M8 5.14v14l11-7-11-7z"/>
  </svg>
)

const PauseIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
    <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
  </svg>
)

const ChevronIcon = ({ expanded }) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    style={{
      transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)',
      transition: 'transform 0.15s ease'
    }}
  >
    <path d="M9 18l6-6-6-6"/>
  </svg>
)

const SearchIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="11" cy="11" r="8"/>
    <path d="M21 21l-4.35-4.35"/>
  </svg>
)

// Animation names and list groups live in animationNames.js (shared with Randall's workbench).
import { filterAnimations, getAnimDisplayName, groupAnimations } from './animationNames'
import { api } from '../transport/api'

const EmbeddedModelViewer = forwardRef(({
  character,
  skinId,
  title = null,          // e.g. the skin's name; replaces the generic header when given
  costumeCode, // For loading vanilla characters (e.g., "PlFxNr")
  datFile,
  sceneFile,
  ajFile,
  logsPath,
  onClose,
  // CSP preset props
  cspMode = false,
  showGrid = true,
  showBackground = true,
  // Callback when scene is exported (for pose manager)
  onSceneExported = null,
  inline = false,
  // "Start from existing pose": a scene file to load instead of the character's
  // default (restores camera/frame/hiddenNodes), plus an optional AJ animation
  // symbol to load once connected (for symbol poses).
  overrideSceneFile = null,
  startAnimSymbol = null,
  startFrame = 0
}, ref) => {
  const placeholderRef = useRef(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  const [streaming, setStreaming] = useState(null)
  const streamCanvasRef = useRef(null)
  const sessionRef = useRef(null)
  const sessionCleanupRef = useRef(null)
  const messageHandlerRef = useRef(null)
  const [capabilityWarning, setCapabilityWarning] = useState('')

  // Animation state
  const [animPlaying, setAnimPlaying] = useState(false)
  const [animFrame, setAnimFrame] = useState(0)
  const [animFrameCount, setAnimFrameCount] = useState(0)
  const [animSpeed, setAnimSpeed] = useState(1)
  const [animList, setAnimList] = useState([])
  const [selectedAnim, setSelectedAnim] = useState('')
  const [animFilter, setAnimFilter] = useState('')
  const [collapsedCategories, setCollapsedCategories] = useState({})

  // "Start from existing pose": apply frame + pause when the load completes
  // (handled in the animLoaded message, not a fixed timeout, to avoid the
  // race where animLoaded arrives after a timeout and re-sets playing=true).
  const startAnimSymbolRef = useRef(null)
  const startFrameRef = useRef(0)
  const startFromDoneRef = useRef(false)
  useEffect(() => {
    startAnimSymbolRef.current = startAnimSymbol
    startFrameRef.current = startFrame
    startFromDoneRef.current = false
  }, [startAnimSymbol, startFrame])

  // Check if Electron API is available
  const hasElectron = typeof window !== 'undefined' && window.electron?.viewerStart

  // Start the embedded viewer
  const startViewer = useCallback(async () => {
    const previousSessionId = sessionRef.current
    sessionCleanupRef.current?.()
    if (previousSessionId && hasElectron) {
      Promise.resolve(window.electron.viewerStop(previousSessionId)).catch(console.error)
    }
    const viewerSessionId = newViewerSessionId()
    sessionRef.current = viewerSessionId
    const isCurrent = () => sessionRef.current === viewerSessionId
    setIsConnected(false)
    setStreaming(null)
    setCapabilityWarning('')
    setAnimList([])
    setAnimFrameCount(0)
    setAnimPlaying(false)
    setAnimSpeed(1)
    startFromDoneRef.current = false

    try {
      setIsLoading(true)
      setError(null)

      if (!hasElectron) {
        console.error('[EmbeddedViewer] No Electron API available!')
        throw new Error('Embedded viewer requires Electron environment')
      }

      // If character and skinId are provided, fetch paths from API
      let viewerPaths = { datFile, sceneFile, ajFile, logsPath }

      if (character && skinId && !datFile) {
        // Load custom skin from storage
        console.log('[EmbeddedViewer] Fetching paths for:', character, skinId)
        let data
        try {
          data = await api.post('/api/viewer/paths', { character, skinId })
        } catch (err) {
          throw new Error(err.message || 'Failed to get viewer paths')
        }

        viewerPaths = {
          datFile: data.datFile,
          sceneFile: data.sceneFile,
          ajFile: data.ajFile,
          dataFile: data.dataFile,  // fighter-data dat -> per-animation mesh-part visibility
          logsPath: data.logsPath,
          members: data.members
        }
        console.log('[EmbeddedViewer] Got paths:', viewerPaths)
      } else if (character && costumeCode && !datFile) {
        // Load vanilla costume
        console.log('[EmbeddedViewer] Fetching vanilla paths for:', character, costumeCode)
        let data
        try {
          data = await api.post('/viewer/paths-vanilla', { character, costumeCode })
        } catch (err) {
          throw new Error(err.message || 'Failed to get vanilla viewer paths')
        }

        viewerPaths = {
          datFile: data.datFile,
          sceneFile: data.sceneFile,
          ajFile: data.ajFile,
          dataFile: data.dataFile,  // fighter-data dat -> per-animation mesh-part visibility
          logsPath: data.logsPath,
          members: data.members
        }
        console.log('[EmbeddedViewer] Got vanilla paths:', viewerPaths)
      }

      // "Start from existing pose": swap in the pose's scene file so the native
      // viewer restores its camera/frame/hiddenNodes (and baked animation, for
      // scene poses) on load.
      if (overrideSceneFile) {
        viewerPaths.sceneFile = overrideSceneFile
        if (viewerPaths.members) viewerPaths.members = viewerPaths.members.map(member =>
          member.datFile === viewerPaths.datFile ? { ...member, sceneFile: overrideSceneFile } : member)
      }

      console.log('[EmbeddedViewer] Starting viewer...')
      if (!isCurrent()) return
      const result = await launchPreviewSession({
        electron: window.electron, paths: { ...viewerPaths, viewerSessionId }, isCurrent,
        onMessage: message => messageHandlerRef.current?.(message),
        onSubscribe: cleanup => { sessionCleanupRef.current = cleanup },
        getCanvas: () => document.hidden ? null : streamCanvasRef.current,
        onFrameError: error => setError(error.message)
      })
      if (!result || !isCurrent()) return

      console.log('[EmbeddedViewer] Viewer started:', result)
      setStreaming(!!result.streaming)
      setIsConnected(result.connected !== false)
      setIsLoading(false)

      // Request animation list
      window.electron.viewerGetAnimList()

    } catch (err) {
      if (!isCurrent()) return
      console.error('[EmbeddedViewer] Failed to start:', err)
      setError(err.message || 'Failed to start viewer')
      setIsLoading(false)
    }
  }, [datFile, sceneFile, ajFile, logsPath, character, skinId, costumeCode, hasElectron, overrideSceneFile])

  useViewerSurface({ containerRef: placeholderRef, canvasRef: streamCanvasRef,
    streaming, connected: isConnected, sessionId: sessionRef.current,
    onError: error => setError(error.message) })
  // A pan keeps the model under the cursor, as in the workbench and the Texture Lab: the renderer's camera says how
  // far one pixel is at the model. Read once per connection (zoom scales the model, not the camera's distance).
  const cameraRef = useRef(null)
  const readCamera = useCallback(() => {
    const session = sessionRef.current
    Promise.resolve(window.electron?.viewerExportScene?.())
      .then(scene => { if (sessionRef.current === session && scene?.camera) cameraRef.current = scene.camera })
      .catch(() => {})
  }, [])
  useEffect(() => {
    cameraRef.current = null
    if (isConnected && hasElectron) readCamera()
  }, [isConnected, hasElectron, datFile, readCamera])
  useViewerInput({ containerRef: placeholderRef, enabled: !!hasElectron && isConnected,
    sessionId: sessionRef.current, onError: error => setError(error.message),
    panStep: () => cameraPanStep(cameraRef.current, placeholderRef.current?.clientWidth,
      placeholderRef.current?.clientHeight) ?? PAN_STEP })

  // Subscription is installed before start; use the latest display/pose props.
  messageHandlerRef.current = (message) => {
      if (handleViewerControlMessage(message, {
        onError: error => { setError(error); setIsLoading(false) },
        onAnimationFrame: update => {
          if ('frame' in update) setAnimFrame(update.frame)
          if ('frameCount' in update) setAnimFrameCount(update.frameCount)
          if ('playing' in update) setAnimPlaying(update.playing)
          if ('speed' in update) setAnimSpeed(update.speed)
        }
      })) return
      if (message.supported === false || (message.error && message.type !== 'disconnected')) {
        setError(message.error || `This viewer does not support ${message.command || message.type}.`)
        setIsLoading(false)
        return
      }
      switch (message.type) {
        case 'ready':
          setIsConnected(true)
          setIsLoading(false)
          window.electron.viewerSetCspMode(cspMode)
          window.electron.viewerSetGrid(showGrid)
          window.electron.viewerSetBackground(showBackground)
          readCamera()
          break
        case 'capabilities':
          setCapabilityWarning(viewerCapabilityWarning(message, { cspMode }))
          break
        case 'disconnected':
          setIsConnected(false)
          setIsLoading(false)
          setError(message.error || 'Viewer connection lost. Retry to reconnect.')
          break
        case 'animList':
          setAnimList(message.symbols || [])
          break
        case 'animLoaded':
          setSelectedAnim(message.symbol)
          setAnimFrameCount(message.frameCount || 0)
          // Starting from an existing pose: seek to its frame and pause,
          // instead of playing from frame 0.
          if (startAnimSymbolRef.current &&
              message.symbol === startAnimSymbolRef.current &&
              !startFromDoneRef.current) {
            startFromDoneRef.current = true
            const f = startFrameRef.current || 0
            setAnimFrame(f)
            setAnimPlaying(false)
            window.electron.viewerAnimSetFrame(f)
            window.electron.viewerAnimPause()
          } else {
            setAnimFrame(0)
            setAnimPlaying(true)
          }
          break
      }
  }

  useEffect(() => {
    startViewer()
    return () => {
      const viewerSessionId = sessionRef.current
      sessionRef.current = null
      sessionCleanupRef.current?.()
      sessionCleanupRef.current = null
      if (viewerSessionId && hasElectron) {
        Promise.resolve(window.electron.viewerStop(viewerSessionId)).catch(console.error)
      }
    }
  }, [startViewer])

  // "Start from existing pose" (symbol poses): once connected, load the saved
  // animation. The animLoaded handler then seeks to the saved frame and pauses.
  // Camera/hiddenNodes were already restored from the scene file at startup;
  // scene poses bake the animation in and need nothing here.
  useEffect(() => {
    if (!isConnected || !hasElectron || !startAnimSymbol) return
    window.electron.viewerLoadAnim(startAnimSymbol)
  }, [isConnected, hasElectron, startAnimSymbol])

  // Animation controls
  const toggleAnimation = () => {
    if (hasElectron) {
      window.electron.viewerAnimToggle()
      setAnimPlaying(!animPlaying)
    }
  }

  const setFrame = (frame) => {
    if (hasElectron) {
      window.electron.viewerAnimSetFrame(frame)
      setAnimFrame(frame)
    }
  }

  const loadAnimation = (symbol) => {
    if (hasElectron) {
      window.electron.viewerLoadAnim(symbol)
    }
  }

  // Export current scene settings
  const exportScene = useCallback(async () => {
    if (!hasElectron) return null
    const viewerSessionId = sessionRef.current
    try {
      const sceneData = await window.electron.viewerExportScene()
      if (sessionRef.current !== viewerSessionId) return null
      if (onSceneExported) {
        onSceneExported(sceneData)
      }
      return sceneData
    } catch (err) {
      if (sessionRef.current !== viewerSessionId) return null
      console.error('[EmbeddedViewer] Export scene failed:', err)
      setError(err.message || 'Could not export the viewer scene.')
      return null
    }
  }, [hasElectron, onSceneExported])

  // Expose methods to parent via ref
  useImperativeHandle(ref, () => ({
    exportScene,
    isConnected,
    animList,
    loadAnimation,
    selectedAnim,
    animPlaying,
    togglePlayback: () => hasElectron && window.electron.viewerAnimToggle(),
    setFrame: (frame) => hasElectron && window.electron.viewerAnimSetFrame(frame),
    animFrame,
    animFrameCount,
    animSpeed
  }), [exportScene, isConnected, animList, loadAnimation, selectedAnim, animPlaying, hasElectron, animFrame, animFrameCount, animSpeed])

  // Toggle category collapse
  const toggleCategory = (category) => {
    setCollapsedCategories(prev => ({
      ...prev,
      [category]: !prev[category]
    }))
  }

  // Group and filter animations
  const groupedAnims = groupAnimations(animList)
  const filteredGroups = {}
  for (const [cat, anims] of Object.entries(groupedAnims)) {
    const filtered = filterAnimations(anims, animFilter)
    if (filtered.length > 0) filteredGroups[cat] = filtered
  }

  // Render fallback for non-Electron
  const renderModal = (content) => {
    if (inline) return content
    const portalTarget = getAppContentPortalTarget()
    return portalTarget ? createPortal(content, portalTarget) : content
  }

  // Render fallback for non-Electron
  if (!hasElectron) {
    const fallback = (
      <div className="mv-overlay" onClick={onClose}>
        <div className="mv-container" onClick={(e) => e.stopPropagation()}>
          <div className="mv-header">
            <div className="mv-title">3D Viewer</div>
            <button className="mv-close-btn" onClick={onClose}>
              <CloseIcon />
            </button>
          </div>
          <div className="mv-body">
            <div className="mv-viewport">
              <div className="mv-status">
                <p>Embedded viewer requires Electron environment.</p>
                <p className="mv-status-sub">Please use the streaming viewer in browser mode.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    )

    return renderModal(fallback)
  }

  const modal = (
    <div className="mv-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="mv-container" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="mv-header">
          <div className="mv-title">
            <span className="mv-title-label">{title || 'Animation Viewer'}</span>
            {!title && <span className="mv-title-char">{character}</span>}
          </div>
          <button className="mv-close-btn" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>

        {/* Main body */}
        <div className="mv-body">
          {/* 3D Viewport */}
          <div
            ref={placeholderRef}
            className="mv-viewport viewer-canvas-surface"
            tabIndex={0}
            aria-label="3D model preview. Drag to rotate, right-drag to pan, scroll to zoom."
          >
            {streaming && <canvas ref={streamCanvasRef} className="viewer-stream-canvas" />}
            {capabilityWarning && <div className="viewer-capability-warning" role="status">{capabilityWarning}</div>}
            {isLoading && (
              <div className="mv-status">
                <div className="mv-spinner" />
                <p>Loading viewer...</p>
              </div>
            )}
            {error && (
              <div className="mv-status mv-status-error">
                <p>{error}</p>
                <button className="mv-retry-btn" onClick={startViewer}>Retry</button>
              </div>
            )}
            {!isLoading && !error && !isConnected && (
              <div className="mv-status">
                <div className="mv-spinner" />
                <p>Connecting to viewer...</p>
              </div>
            )}
            {isConnected && (
              <div className="mv-hint">
                Drag to rotate | Scroll to zoom | Right-drag to pan
              </div>
            )}
          </div>

          {/* Animation sidebar */}
          {isConnected && animList.length > 0 && (
            <div className="mv-sidebar">
              <div className="mv-sidebar-header">
                <span>Animations</span>
                <span className="mv-anim-count">{animList.length}</span>
              </div>

              <div className="mv-search-box">
                <SearchIcon />
                <input
                  type="text"
                  placeholder="Filter animations..."
                  value={animFilter}
                  onChange={(e) => setAnimFilter(e.target.value)}
                />
              </div>

              <div className="mv-anim-list">
                {Object.entries(filteredGroups).map(([category, anims]) => {
                  const isCollapsed = collapsedCategories[category]
                  return (
                    <div key={category} className="mv-category">
                      <button
                        className="mv-category-header"
                        onClick={() => toggleCategory(category)}
                      >
                        <ChevronIcon expanded={!isCollapsed} />
                        <span>{category}</span>
                        <span className="mv-category-count">{anims.length}</span>
                      </button>
                      {!isCollapsed && (
                        <div className="mv-category-items">
                          {anims.map(anim => (
                            <button
                              key={anim}
                              onClick={() => loadAnimation(anim)}
                              className={`mv-anim-item ${selectedAnim === anim ? 'mv-anim-selected' : ''}`}
                            >
                              {getAnimDisplayName(anim)}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* Playback controls */}
        {isConnected && animFrameCount > 0 && (
          <div className="mv-controls">
            <button onClick={toggleAnimation} className="mv-play-btn" title={animPlaying ? 'Pause' : 'Play'}>
              {animPlaying ? <PauseIcon /> : <PlayIcon />}
            </button>
            <div className="mv-scrubber">
              <input
                type="range"
                min={0}
                max={animFrameCount - 1}
                value={animFrame}
                onChange={(e) => setFrame(parseFloat(e.target.value))}
              />
              <div
                className="mv-scrubber-fill"
                style={{ width: `${(animFrame / (animFrameCount - 1)) * 100}%` }}
              />
            </div>
            <div className="mv-frame-display">
              <span className="mv-frame-current">{Math.floor(animFrame)}</span>
              <span className="mv-frame-sep">/</span>
              <span className="mv-frame-total">{Math.floor(animFrameCount)}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )

  return renderModal(modal)
})

export default EmbeddedModelViewer
