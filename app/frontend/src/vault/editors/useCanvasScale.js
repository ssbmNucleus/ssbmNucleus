import { useState, useEffect, useRef, useCallback } from 'react'

const clamp = value => Math.min(64, Math.max(0.05, value))
const isInput = target => target?.closest('input, textarea, select, button, [contenteditable="true"]')

// View transforms never resize pixel data or change undo/texture ownership.
export function useCanvasScale({ skinCreatorStep, selectedTextureIndex, modelTextures, paintCanvasRef }) {
  const canvasContainerRef = useRef(null)
  const view = useRef({ scale: 1, x: 0, y: 0, fit: true })
  const drag = useRef(null)
  const space = useRef(false)
  const [zoom, setZoom] = useState(1)
  const [hand, setHand] = useState(false)
  const [panning, setPanning] = useState(false)
  const [spaceHeld, setSpaceHeld] = useState(false)
  const apply = useCallback(() => {
    const canvas = paintCanvasRef.current
    const container = canvasContainerRef.current
    if (!canvas || !container) return
    const v = view.current
    if (v.fit) {
      v.scale = clamp(Math.min((container.clientWidth - 48) / canvas.width, (container.clientHeight - 48) / canvas.height, 10))
      v.x = 0; v.y = 0
    }
    canvas.style.transform = `translate(${v.x}px, ${v.y}px) scale(${v.scale})`
    canvas.style.transformOrigin = 'center center'
    // The area-selection overlay is a sibling, so it has to be pinned to the
    // canvas's layout box and given the same transform -- otherwise the
    // marching ants drift away from the pixels they describe on zoom/pan.
    const overlay = container.querySelector('.paint-selection')
    if (overlay) {
      overlay.style.left = `${canvas.offsetLeft}px`
      overlay.style.top = `${canvas.offsetTop}px`
      overlay.style.width = `${canvas.width}px`
      overlay.style.height = `${canvas.height}px`
      overlay.style.transform = canvas.style.transform
      overlay.style.transformOrigin = 'center center'
    }
    setZoom(v.scale)
  }, [paintCanvasRef])
  const fit = useCallback(() => { view.current.fit = true; apply() }, [apply])
  const setZoomAt = useCallback((scale, point) => {
    const v = view.current
    const next = clamp(scale)
    const rect = canvasContainerRef.current?.getBoundingClientRect()
    const x = point && rect ? point.x - rect.left - rect.width / 2 : 0
    const y = point && rect ? point.y - rect.top - rect.height / 2 : 0
    v.x = x - (x - v.x) * next / v.scale
    v.y = y - (y - v.y) * next / v.scale
    v.scale = next; v.fit = false
    apply()
  }, [apply])
  const zoomBy = useCallback(factor => setZoomAt(view.current.scale * factor), [setZoomAt])
  const actualSize = useCallback(() => {
    view.current = { scale: 1, x: 0, y: 0, fit: false }; apply()
  }, [apply])
  const texture = modelTextures[selectedTextureIndex]
  const textureId = texture ? `${texture.memberId || ''}:${texture.index}` : ''
  useEffect(() => { fit() }, [textureId, skinCreatorStep, fit])
  useEffect(() => {
    const container = canvasContainerRef.current
    if (!container) return
    const observer = new ResizeObserver(apply)
    observer.observe(container)
    const wheel = event => {
      if (isInput(event.target) || drag.current || (event.buttons & 1)) return
      event.preventDefault()
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? container.clientHeight : 1)
      setZoomAt(view.current.scale * Math.exp(-Math.max(-200, Math.min(200, delta)) * 0.002), { x: event.clientX, y: event.clientY })
    }
    container.addEventListener('wheel', wheel, { passive: false })
    return () => { observer.disconnect(); container.removeEventListener('wheel', wheel) }
  }, [skinCreatorStep, apply, setZoomAt])
  useEffect(() => {
    const release = () => { space.current = false; drag.current = null; setSpaceHeld(false); setPanning(false) }
    const keydown = event => {
      if (isInput(event.target) || !canvasContainerRef.current?.contains(document.activeElement)) return
      if (event.code === 'Space') { event.preventDefault(); space.current = true; setSpaceHeld(true) }
      if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomBy(1.25) }
      if (event.key === '-') { event.preventDefault(); zoomBy(0.8) }
      if (event.key === '0') { event.preventDefault(); fit() }
      if (event.key === '1') { event.preventDefault(); actualSize() }
    }
    const keyup = event => { if (event.code === 'Space') { space.current = false; setSpaceHeld(false) } }
    const move = event => {
      if (!drag.current) return
      view.current.x = drag.current.x + event.clientX - drag.current.clientX
      view.current.y = drag.current.y + event.clientY - drag.current.clientY
      apply()
    }
    const end = () => { drag.current = null; setPanning(false) }
    window.addEventListener('keydown', keydown); window.addEventListener('keyup', keyup)
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', end); window.addEventListener('blur', release)
    return () => {
      window.removeEventListener('keydown', keydown); window.removeEventListener('keyup', keyup)
      window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', end); window.removeEventListener('blur', release)
      drag.current = null; space.current = false
    }
  }, [apply, zoomBy, fit, actualSize])
  const beginPan = event => {
    if (isInput(event.target)) return true
    canvasContainerRef.current?.focus({ preventScroll: true })
    if (event.button !== 1 && !(event.button === 0 && (hand || space.current))) return false
    event.preventDefault()
    view.current.fit = false
    drag.current = { x: view.current.x, y: view.current.y, clientX: event.clientX, clientY: event.clientY }
    setPanning(true)
    return true
  }
  return { canvasContainerRef, updateCanvasScale: apply, zoom, zoomBy, fit, actualSize,
    hand, setHand, panning, panMode: hand || spaceHeld, beginPan, isPanning: () => !!drag.current }
}
