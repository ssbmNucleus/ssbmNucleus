import { useEffect, useRef } from 'react'
import { bindViewerInput } from './viewerInput'

// `panStep` (optional): scene units per pixel, read at each move (bindViewerInput); held in a ref, so a new function
// each render does not rebind the listeners.
export function useViewerInput({ containerRef, enabled, sessionId, panScale, panStep, zoomScale, onError }) {
  const errorRef = useRef(onError)
  errorRef.current = onError
  const stepRef = useRef(panStep)
  stepRef.current = panStep
  const following = Boolean(panStep)
  useEffect(() => {
    if (!enabled || !containerRef.current) return
    return bindViewerInput({ element: containerRef.current, panScale, zoomScale,
      panStep: following ? () => stepRef.current?.() : null,
      sendCamera: (...args) => window.electron.viewerCamera(...args),
      onError: error => errorRef.current?.(error) })
  }, [containerRef, enabled, sessionId, panScale, following, zoomScale])
}
