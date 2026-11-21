import { useEffect, useRef } from 'react'
import { elementScreenRect } from './screenRect'
import { createViewerSurface } from './viewerSurface'

export function useViewerSurface({ containerRef, canvasRef, streaming, connected, sessionId, visible = true, onError }) {
  const errorRef = useRef(onError)
  errorRef.current = onError
  useEffect(() => {
    const element = containerRef.current
    if (!connected || streaming === null || !element) return
    const electron = window.electron
    const surface = createViewerSurface({ element, getCanvas: () => canvasRef.current, streaming,
      resize: (...args) => electron.viewerResize(...args), show: () => electron.viewerShow(),
      hide: () => electron.viewerHide(), screenRect: elementScreenRect,
      isVisible: () => visible && !document.hidden,
      onError: error => errorRef.current?.(error) })
    let layoutSize
    let disposed = false
    const update = () => { if (!disposed) surface.update(layoutSize) }
    const observer = new ResizeObserver(entries => {
      layoutSize = entries.find(entry => entry.target === element)?.contentRect || layoutSize
      update()
    })
    observer.observe(element)
    // Visibility changes need an explicit check even when the box is unchanged.
    const visibilityObserver = typeof IntersectionObserver === 'function' ? new IntersectionObserver(update) : null
    visibilityObserver?.observe(element)
    const attributesObserver = new MutationObserver(update)
    for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
      attributesObserver.observe(ancestor, { attributes: true, attributeFilter: ['class', 'style', 'hidden'] })
    }
    document.addEventListener('visibilitychange', update)
    window.addEventListener('resize', update)
    let dpiQuery
    const watchDpi = () => {
      dpiQuery?.removeEventListener('change', dpiChanged)
      dpiQuery = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`)
      dpiQuery.addEventListener('change', dpiChanged)
    }
    const dpiChanged = () => { update(); watchDpi() }
    watchDpi()
    // Only the explicitly selected legacy embedded transport tracks desktop moves.
    const timer = streaming ? null : setInterval(update, 250)
    if (!streaming) window.addEventListener('scroll', update, true)
    update()
    return () => {
      disposed = true
      observer.disconnect()
      visibilityObserver?.disconnect()
      attributesObserver.disconnect()
      document.removeEventListener('visibilitychange', update)
      window.removeEventListener('resize', update)
      dpiQuery?.removeEventListener('change', dpiChanged)
      if (timer !== null) clearInterval(timer)
      if (!streaming) window.removeEventListener('scroll', update, true)
    }
  }, [containerRef, canvasRef, streaming, connected, sessionId, visible])
}
