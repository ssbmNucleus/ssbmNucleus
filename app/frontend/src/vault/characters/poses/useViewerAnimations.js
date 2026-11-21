import { useState, useEffect } from 'react'

/**
 * Coordinates with the embedded HSDRawViewer via the viewer ref:
 * polls for the available animation list and loads animations on demand.
 *
 * NOTE: timing matters — the 500ms polling interval and its cleanup must
 * match the original behavior exactly (runs only while `show` is true).
 */
export default function useViewerAnimations({ show, viewerRef }) {
  const [animList, setAnimList] = useState([])
  const [selectedAnim, setSelectedAnim] = useState('')
  const [animFilter, setAnimFilter] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('All')

  // Poll viewer for animation list
  useEffect(() => {
    if (!show) return
    const interval = setInterval(() => {
      if (viewerRef.current?.animList?.length > 0) {
        setAnimList(viewerRef.current.animList)
        if (viewerRef.current.selectedAnim) {
          setSelectedAnim(viewerRef.current.selectedAnim)
        }
      }
    }, 500)
    return () => clearInterval(interval)
  }, [show])

  const handleLoadAnim = (symbol) => {
    if (viewerRef.current?.loadAnimation) {
      viewerRef.current.loadAnimation(symbol)
      setSelectedAnim(symbol)
    }
  }

  return {
    animList,
    selectedAnim,
    animFilter,
    setAnimFilter,
    selectedCategory,
    setSelectedCategory,
    handleLoadAnim
  }
}
