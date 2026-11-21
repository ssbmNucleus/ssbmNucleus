import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../transport/api'
import { elementScreenRect } from './screenRect'
import { startDolphinPreview } from './dolphinPreview'
import { captureCrop } from './captureCrop'

function LegacyDolphinEmbedPanel({ active, fill = false, windowApi = null, onUnsupported = null }) {
  // which backend owns the window: default = the in-game test engine;
  // pass e.g. `${BACKEND_URL}/api/nucleome/watch-mods/window` for replay playback
  const apiBase = windowApi || api.url('/test-in-game/window')
  const placeholderRef = useRef(null)
  const lastSentRef = useRef(null)   // JSON key of the last acknowledged post
  const busyRef = useRef(false)      // one request in flight at a time
  const foundRef = useRef(false)
  const unsupportedRef = useRef(false)
  const tickRef = useRef(0)
  const [found, setFound] = useState(false)
  // Off Windows the backend answers supported:false -- embedding has no
  // Wayland/X11 analog, Dolphin plays in its own window. Say so instead of
  // showing the boot loader forever.
  const [unsupported, setUnsupported] = useState(false)
  // Ref, not a dependency: callers pass inline arrows, and WatchModsModal
  // re-renders on its 2s status poll -- depending on the prop identity would
  // tear down and restart the polling effect (with its cleanup park() POST)
  // every 2 seconds while a replay plays.
  const onUnsupportedRef = useRef(onUnsupported)
  useEffect(() => { onUnsupportedRef.current = onUnsupported }, [onUnsupported])

  const sendPosition = useCallback(async () => {
    const el = placeholderRef.current
    if (!el || busyRef.current || unsupportedRef.current) return

    const rect = el.getBoundingClientRect()

    let path, body
    if (rect.width < 2 || rect.height < 2) {
      // Collapsed / hidden mid-layout: get the native window out of the way.
      path = 'park'
      body = {}
    } else {
      // Screen rect in PHYSICAL pixels (same math as EmbeddedModelViewer),
      // zoom- and DPI-aware.
      path = 'position'
      body = elementScreenRect(rect)
    }

    // Until the window is found, retry every tick (Dolphin appears mid-test);
    // after that only on change, plus a ~2s heartbeat in case Dolphin recreated
    // its render window (fresh title bar, default position).
    const key = `${path}:${JSON.stringify(body)}`
    tickRef.current += 1
    if (foundRef.current && lastSentRef.current === key && tickRef.current % 8 !== 0) return

    busyRef.current = true
    try {
      let data
      try {
        data = await api.post(`${apiBase}/${path}`, body)
      } catch (err) {
        // The backend answers `success: false` WITH a payload for the
        // off-Windows / no-window-yet cases -- ApiError keeps that body in
        // err.data. A real network failure has none: try again next tick.
        if (!err?.data) return
        data = err.data
      }
      lastSentRef.current = key
      if (data && data.supported === false) {
        unsupportedRef.current = true
        setUnsupported(true)
        if (onUnsupportedRef.current) onUnsupportedRef.current()
        return
      }
      const ok = !!(data && data.found) && path === 'position'
      if (ok !== foundRef.current) {
        foundRef.current = ok
        setFound(ok)
      }
    } finally {
      busyRef.current = false
    }
  }, [apiBase])

  useEffect(() => {
    if (!active) return undefined
    foundRef.current = false
    lastSentRef.current = null
    setFound(false)

    sendPosition()
    const intervalId = setInterval(sendPosition, 250)
    const handleMove = () => sendPosition()
    window.addEventListener('resize', handleMove)
    window.addEventListener('scroll', handleMove, true)
    return () => {
      clearInterval(intervalId)
      window.removeEventListener('resize', handleMove)
      window.removeEventListener('scroll', handleMove, true)
      foundRef.current = false
      // Best-effort: if the Dolphin is still alive, move it offscreen.
      api.post(`${apiBase}/park`).catch(() => {})
    }
  }, [active, sendPosition])

  if (!active) return null

  const placeholder = (
    <div
      ref={placeholderRef}
      style={{
        aspectRatio: '4 / 3',
        // fill: contain-fit 4:3 inside the flex-given stage (100cqw/100cqh =
        // the stage's own size -- can never overflow, so nothing scrolls).
        // inline: scale with the viewport (cq units fall back to viewport
        // units with no container), ~17rem reserved for surrounding text.
        width: fill
          ? 'min(100cqw, calc(100cqh * 4 / 3))'
          : 'clamp(280px, calc((100cqh - 17rem) * 4 / 3), 100%)',
        margin: fill ? '0 auto' : '1rem auto 0',
        background: 'var(--color-bg-deep)',
        border: '1px solid var(--color-border-subtle)',
        borderRadius: 'var(--radius-md)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {!found && (
        <p style={{ color: 'var(--color-text-tertiary)', fontSize: '0.85em', padding: '1rem', textAlign: 'center' }}>
          {unsupported
            ? 'The game is playing in a separate Dolphin window.'
            : 'The game appears here once Dolphin boots…'}
        </p>
      )}
    </div>
  )

  if (!fill) return placeholder

  // The stage: takes whatever space the flex-column parent has left and
  // becomes the size container the placeholder fits into. minHeight: 0 lets
  // it actually shrink instead of forcing overflow.
  return (
    <div
      style={{
        flex: '1 1 auto', minHeight: 0, width: '100%', marginTop: '1rem',
        containerType: 'size',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      {placeholder}
    </div>
  )
}


// Watch Mods still uses its separately owned legacy window controller.
export default function DolphinEmbedPanel(props) {
  if (props.expectedSessionId && !window.electron?.dolphinCapturePrepare)
    return <p>The game is playing in a separate Dolphin window.</p>
  if (props.windowApi || !window.electron?.dolphinCapturePrepare)
    return <LegacyDolphinEmbedPanel {...props} />
  return <DolphinCapturePanel {...props} />
}

/** Whether this window can show the owned Dolphin as a live video capture. */
export const canCaptureDolphin = () => !!window.electron?.dolphinCapturePrepare

/** One live Dolphin capture into `videoRef`'s <video> while `active`.
    `state` is dolphinPreview's: { status: 'starting' | 'live' | 'separate', message, client }. */
export function useDolphinCapture({ active, expectedSessionId }) {
  const videoRef = useRef(null)
  const previewRef = useRef(null)
  const [state, setState] = useState({ status: 'starting', message: '' })
  useEffect(() => {
    if (!active || !videoRef.current) return undefined
    let mounted = true
    const preview = startDolphinPreview({ bridge: window.electron,
      mediaDevices: navigator.mediaDevices, video: videoRef.current, expectedSessionId,
      onState: next => { if (mounted) setState(next) } })
    previewRef.current = preview
    return () => { mounted = false; preview.stop(); previewRef.current = null }
  }, [active, expectedSessionId])
  const popout = useCallback(() => previewRef.current?.popout(), [])
  return { videoRef, state, popout }
}

function DolphinCapturePanel({ active, fill = false, expectedSessionId }) {
  const { videoRef, state, popout } = useDolphinCapture({ active, expectedSessionId })
  if (!active) return null
  return <DolphinCaptureView videoRef={videoRef} state={state} popout={popout} fill={fill} />
}

/** The capture is Dolphin's whole window, its title bar and borders included.
    The stage is Melee's 4:3 and, once the backend has measured where the game
    sits in that window (`state.client`), the video is placed so only the game
    shows. Unmeasured, the whole window is shown, contained. */
export function DolphinCaptureView({ videoRef, state, popout, fill = false }) {
  const live = state.status === 'live'
  const crop = live ? captureCrop(state.client) : null
  const stage = (
    <div style={{ position: 'relative', overflow: 'hidden', aspectRatio: '4 / 3',
      // fill: contain-fit 4:3 inside the size container below (as the legacy panel does)
      width: fill ? 'min(100cqw, calc(100cqh * 4 / 3))' : '100%', minHeight: fill ? undefined : 160,
      background: 'var(--color-bg-deep)',
      border: '1px solid var(--color-border-subtle)', borderRadius: 'var(--radius-md)' }}>
      <video ref={videoRef} muted playsInline style={crop || { width: '100%', height: '100%',
        position: 'absolute', inset: 0, objectFit: 'contain', visibility: live ? 'visible' : 'hidden' }} />
      {!live && <p style={{ color: 'var(--color-text-tertiary)', padding: '1rem', textAlign: 'center' }}>{state.message}</p>}
    </div>
  )
  return (
    <div style={{ flex: fill ? '1 1 auto' : undefined, minHeight: 0, width: '100%',
      marginTop: fill ? 0 : '1rem', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
      {fill ? (
        <div style={{ flex: '1 1 auto', minHeight: 0, width: '100%', containerType: 'size',
          display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {stage}
        </div>
      ) : stage}
      <button type="button" className="btn btn-secondary btn-sm" onClick={popout}>
        Open Dolphin window
      </button>
    </div>
  )
}
