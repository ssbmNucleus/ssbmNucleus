import { useRef, useEffect, useCallback, useState } from 'react'
import { API_URL, backendMediaUrl } from '../../shared/config/config.js'

const SSS_BASE_WIDTH = 2.9760742
const SSS_BASE_HEIGHT = 2.603993
const SSS_TEMPLATE_WIDTH = 28.59
const SSS_TEMPLATE_HEIGHT = 23.50

function transformRect(gameX, gameY, gameW, gameH, zoom, offsetX, offsetY, canvasW, canvasH) {
  const x = gameX * zoom + offsetX
  const y = gameY * zoom - offsetY
  const w = gameW * zoom
  const h = gameH * zoom
  return {
    x: canvasW / 2 + x - w,
    y: canvasH / 2 - y - h,
    width: w * 2,
    height: h * 2
  }
}

function hitTest(screenX, screenY, icons, zoom, offX, offY, cw, ch, drag, bw, bh) {
  for (let i = icons.length - 1; i >= 0; i--) {
    const icon = icons[i]
    if (icon.status === 0) continue
    let ix = icon.x, iy = icon.y
    if (drag && drag.idx === i) { ix += drag.dx; iy += drag.dy }
    const r = transformRect(ix, iy, bw * icon.scaleX, bh * icon.scaleY, zoom, offX, offY, cw, ch)
    if (screenX >= r.x && screenX <= r.x + r.width && screenY >= r.y && screenY <= r.y + r.height)
      return i
  }
  return -1
}

function rectsOverlap(a, b) {
  return a.x < b.x + b.width && a.x + a.width > b.x &&
         a.y < b.y + b.height && a.y + a.height > b.y
}

function normalizeRect(x1, y1, x2, y2) {
  return { x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.abs(x2 - x1), height: Math.abs(y2 - y1) }
}

export default function SssCanvas({
  icons = [],
  selectedIndices = [],
  onSelectionChange,
  onMoveIcon,
  onMoveIcons,
  onSwapIcons,
  onReorderIcons,
  onContextMenu,
  zoom = 8,
  offset = { x: 0, y: 0 },
  onZoomChange,
  onOffsetChange,
  showCollision = true,
  showOverscan = false,
  swapMode = true,
  reorderMode = false,
  iconBaseWidth = SSS_BASE_WIDTH,
  iconBaseHeight = SSS_BASE_HEIGHT,
  templateWidth = SSS_TEMPLATE_WIDTH,
  templateHeight = SSS_TEMPLATE_HEIGHT,
  // The select screen behind the icons, rendered from the user's own game by
  // the backend (menu_backdrops); a plain panel when it cannot be made.
  templateSrc = backendMediaUrl(`${API_URL}/menus/sss/backdrop`),
  getCollisionRect,
  iconEndpoint = '/menus/sss/stage-icon',
  fitToView = false
}) {
  const canvasRef = useRef(null)
  const containerRef = useRef(null)
  const imgCache = useRef({})
  const templateImg = useRef(null)
  const didFit = useRef(false)
  const [canvasSize, setCanvasSize] = useState({ w: 800, h: 600 })
  const [imgVersion, setImgVersion] = useState(0)

  const drag = useRef(null)       // { idx, dx, dy, ghostX, ghostY }
  const boxSel = useRef(null)     // { startX, startY, curX, curY } in canvas px
  const panning = useRef(false)
  const lastCursor = useRef({ x: 0, y: 0 })
  const [renderTick, setRenderTick] = useState(0)
  const tickRef = useRef(null)

  const scheduleRepaint = useCallback(() => {
    if (!tickRef.current) {
      tickRef.current = requestAnimationFrame(() => { tickRef.current = null; setRenderTick(t => t + 1) })
    }
  }, [])

  useEffect(() => {
    templateImg.current = null
    const img = new Image()
    img.onload = () => { templateImg.current = img; setImgVersion(v => v + 1) }
    img.onerror = () => { templateImg.current = null; setImgVersion(v => v + 1) }
    img.src = templateSrc
  }, [templateSrc])

  const makeIconUrl = useCallback((iconPath) => {
    return backendMediaUrl(`${API_URL}${iconEndpoint}?path=${encodeURIComponent(iconPath)}`)
  }, [API_URL, iconEndpoint])

  useEffect(() => {
    imgCache.current = {}
    icons.forEach(icon => {
      if (!icon.iconPath) return
      const url = makeIconUrl(icon.iconPath)
      if (url in imgCache.current) return
      imgCache.current[url] = null
      const img = new Image()
      img.onload = () => { imgCache.current[url] = img; setImgVersion(v => v + 1) }
      img.onerror = () => { imgCache.current[url] = false }
      img.src = url
    })
  }, [icons, makeIconUrl])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = (width, height) => {
      if (width <= 0 || height <= 0) return
      const w = Math.floor(width), h = Math.floor(height)
      setCanvasSize({ w, h })
      // On the first real measurement, pick a zoom that fits the template to
      // ~90% of the canvas so it doesn't start tiny on large displays.
      if (fitToView && !didFit.current) {
        didFit.current = true
        const fill = 0.9
        const fitZoom = Math.min((w * fill) / (templateWidth * 2), (h * fill) / (templateHeight * 2))
        onZoomChange?.(Math.max(4, Math.min(20, Math.round(fitZoom))))
      }
    }
    // Measure once up front — the ResizeObserver's initial callback isn't
    // always delivered, so don't depend on it for the starting size/zoom.
    const rect = el.getBoundingClientRect()
    measure(rect.width, rect.height)
    const obs = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      measure(width, height)
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [fitToView, templateWidth, templateHeight, onZoomChange])

  const getImg = (icon) => {
    if (!icon.iconPath) return null
    return imgCache.current[makeIconUrl(icon.iconPath)] || null
  }

  const selSet = new Set(selectedIndices)

  // Swap and reorder both drag a ghost icon and drop onto a target slot;
  // they only differ in what happens on drop. Free-move drags the icon itself.
  const ghostDrag = swapMode || reorderMode

  // ── Render ──
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const cw = canvas.width, ch = canvas.height
    const _d = drag.current
    const _box = boxSel.current

    ctx.clearRect(0, 0, cw, ch)

    const screenRect = transformRect(0, 0, templateWidth, templateHeight, zoom, offset.x, offset.y, cw, ch)
    if (templateImg.current) {
      ctx.drawImage(templateImg.current, screenRect.x, screenRect.y, screenRect.width, screenRect.height)
    } else {
      // No backdrop (not rendered yet, or no game to render it from): a plain
      // panel the size of the screen, so the layout still has its frame.
      ctx.fillStyle = '#0b0f24'
      ctx.fillRect(screenRect.x, screenRect.y, screenRect.width, screenRect.height)
    }

    icons.forEach((icon, idx) => {
      if (icon.status === 0) return
      let ix = icon.x, iy = icon.y
      if (_d && !ghostDrag && (_d.idx === idx || (_d.multi && selSet.has(idx)))) { ix += _d.dx; iy += _d.dy }

      const iw = iconBaseWidth * icon.scaleX
      const ih = iconBaseHeight * icon.scaleY
      const r = transformRect(ix, iy, iw, ih, zoom, offset.x, offset.y, cw, ch)

      const img = getImg(icon)
      if (img) ctx.drawImage(img, r.x, r.y, r.width, r.height)
      else { ctx.fillStyle = '#ffffff'; ctx.fillRect(r.x, r.y, r.width, r.height) }

      if (showCollision && icon.status !== 4) {
        const col = getCollisionRect
          ? getCollisionRect(icon)
          : { ox: 0, oy: 0, w: icon.width * icon.scaleX, h: icon.height * icon.scaleY }
        const cr = transformRect(ix + col.ox, iy + col.oy, col.w, col.h, zoom, offset.x, offset.y, cw, ch)
        ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 1; ctx.strokeRect(cr.x, cr.y, cr.width, cr.height)
      }
    })

    // Ghost
    if (_d && ghostDrag) {
      const icon = icons[_d.idx]
      if (icon) {
        const r = transformRect(_d.ghostX, _d.ghostY, iconBaseWidth * icon.scaleX, iconBaseHeight * icon.scaleY, zoom, offset.x, offset.y, cw, ch)
        ctx.globalAlpha = 0.5
        const img = getImg(icon)
        if (img) ctx.drawImage(img, r.x, r.y, r.width, r.height)
        else { ctx.strokeStyle = '#ffff00'; ctx.lineWidth = 1; ctx.strokeRect(r.x, r.y, r.width, r.height) }
        ctx.globalAlpha = 1.0
      }
    }

    // Selection highlights
    const _sel = selSet
    icons.forEach((icon, idx) => {
      if (!_sel.has(idx) || icon.status === 0) return
      let ix = icon.x, iy = icon.y
      if (_d && !ghostDrag && (_d.idx === idx || (_d.multi && _sel.has(idx)))) { ix += _d.dx; iy += _d.dy }
      const col = getCollisionRect
        ? getCollisionRect(icon)
        : { ox: 0, oy: 0, w: icon.width * icon.scaleX, h: icon.height * icon.scaleY }
      const sw = icon.status === 4 ? iconBaseWidth * icon.scaleX : col.w
      const sh = icon.status === 4 ? iconBaseHeight * icon.scaleY : col.h
      const ox = icon.status === 4 ? 0 : col.ox
      const oy = icon.status === 4 ? 0 : col.oy
      const r = transformRect(ix + ox, iy + oy, sw, sh, zoom, offset.x, offset.y, cw, ch)
      ctx.fillStyle = 'rgba(255, 255, 0, 0.35)'
      ctx.fillRect(r.x, r.y, r.width, r.height)
    })

    // Overscan
    if (showOverscan) {
      const full = transformRect(0, 0, templateWidth, templateHeight, zoom, offset.x, offset.y, cw, ch)
      ctx.strokeStyle = 'rgba(255, 0, 0, 0.7)'; ctx.lineWidth = 2; ctx.strokeRect(full.x, full.y, full.width, full.height)
      const o5 = transformRect(0, 0, templateWidth * 0.95, templateHeight * 0.95, zoom, offset.x, offset.y, cw, ch)
      ctx.strokeStyle = 'rgba(255, 255, 0, 0.7)'; ctx.strokeRect(o5.x, o5.y, o5.width, o5.height)
      const o1 = transformRect(0, 0, templateWidth * 0.9, templateHeight * 0.9, zoom, offset.x, offset.y, cw, ch)
      ctx.strokeStyle = 'rgba(0, 255, 0, 0.7)'; ctx.strokeRect(o1.x, o1.y, o1.width, o1.height)
    }

    // Box select rectangle
    if (_box) {
      const br = normalizeRect(_box.startX, _box.startY, _box.curX, _box.curY)
      ctx.strokeStyle = 'rgba(100, 150, 255, 0.8)'; ctx.lineWidth = 1; ctx.strokeRect(br.x, br.y, br.width, br.height)
      ctx.fillStyle = 'rgba(100, 150, 255, 0.15)'; ctx.fillRect(br.x, br.y, br.width, br.height)
    }
  }, [icons, selectedIndices, zoom, offset, showCollision, showOverscan, ghostDrag, canvasSize, imgVersion, renderTick, iconBaseWidth, iconBaseHeight, templateWidth, templateHeight, getCollisionRect])

  // ── Pointer handlers ──
  const handlePointerDown = useCallback((e) => {
    // Right-click: start pan if on empty space (context menu on icons handled separately)
    if (e.button === 2) {
      const canvas = canvasRef.current
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const sx = (e.clientX - rect.left) * (canvas.width / rect.width)
      const sy = (e.clientY - rect.top) * (canvas.height / rect.height)
      const idx = hitTest(sx, sy, icons, zoom, offset.x, offset.y, canvas.width, canvas.height, null, iconBaseWidth, iconBaseHeight)
      if (idx < 0) {
        panning.current = true
        lastCursor.current = { x: e.clientX, y: e.clientY }
        canvas.setPointerCapture(e.pointerId)
        e.preventDefault()
      }
      return
    }
    if (e.button !== 0) return
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const scaleY = canvas.height / rect.height
    const sx = (e.clientX - rect.left) * scaleX
    const sy = (e.clientY - rect.top) * scaleY
    lastCursor.current = { x: e.clientX, y: e.clientY }

    const idx = hitTest(sx, sy, icons, zoom, offset.x, offset.y, canvas.width, canvas.height, null, iconBaseWidth, iconBaseHeight)

    if (idx >= 0) {
      const alreadySelected = selectedIndices.includes(idx)
      if (e.shiftKey) {
        const cur = new Set(selectedIndices)
        if (cur.has(idx)) cur.delete(idx); else cur.add(idx)
        onSelectionChange?.([...cur])
      } else if (!alreadySelected) {
        onSelectionChange?.([idx])
      }
      drag.current = { idx, dx: 0, dy: 0, ghostX: icons[idx].x, ghostY: icons[idx].y, multi: alreadySelected && selectedIndices.length > 1 }
      canvas.setPointerCapture(e.pointerId)
      e.preventDefault()
    } else {
      if (!e.shiftKey) onSelectionChange?.([])
      boxSel.current = { startX: sx, startY: sy, curX: sx, curY: sy }
      canvas.setPointerCapture(e.pointerId)
      e.preventDefault()
    }
  }, [icons, zoom, offset, onSelectionChange, selectedIndices, iconBaseWidth, iconBaseHeight])

  const handlePointerMove = useCallback((e) => {
    const dx = e.clientX - lastCursor.current.x
    const dy = e.clientY - lastCursor.current.y
    lastCursor.current = { x: e.clientX, y: e.clientY }

    if ((e.buttons & 4) || (panning.current && (e.buttons & 2))) {
      onOffsetChange?.({ x: offset.x + dx, y: offset.y + dy })
      return
    }

    if (boxSel.current && (e.buttons & 1)) {
      const canvas = canvasRef.current
      if (canvas) {
        const rect = canvas.getBoundingClientRect()
        boxSel.current.curX = (e.clientX - rect.left) * (canvas.width / rect.width)
        boxSel.current.curY = (e.clientY - rect.top) * (canvas.height / rect.height)
      }
      scheduleRepaint()
      return
    }

    if (drag.current && (e.buttons & 1)) {
      const gx = dx / zoom
      const gy = -dy / zoom
      if (ghostDrag) { drag.current.ghostX += gx; drag.current.ghostY += gy }
      else { drag.current.dx += gx; drag.current.dy += gy }
      scheduleRepaint()
    }
  }, [zoom, offset, ghostDrag, onOffsetChange, scheduleRepaint])

  const handlePointerUp = useCallback((e) => {
    if (panning.current) { panning.current = false; return }

    // Box select finish
    if (boxSel.current) {
      const bs = boxSel.current
      boxSel.current = null
      const selRect = normalizeRect(bs.startX, bs.startY, bs.curX, bs.curY)
      if (selRect.width > 3 || selRect.height > 3) {
        const canvas = canvasRef.current
        if (canvas) {
          const hits = []
          icons.forEach((icon, idx) => {
            if (icon.status === 0) return
            const r = transformRect(icon.x, icon.y, iconBaseWidth * icon.scaleX, iconBaseHeight * icon.scaleY, zoom, offset.x, offset.y, canvas.width, canvas.height)
            if (rectsOverlap(selRect, r)) hits.push(idx)
          })
          if (e.shiftKey) {
            const cur = new Set(selectedIndices)
            hits.forEach(i => cur.add(i))
            onSelectionChange?.([...cur])
          } else {
            onSelectionChange?.(hits)
          }
        }
      }
      scheduleRepaint()
      return
    }

    // Icon drag finish
    const d = drag.current
    if (!d) return

    if (ghostDrag) {
      const canvas = canvasRef.current
      if (canvas) {
        const rect = canvas.getBoundingClientRect()
        const sx = (e.clientX - rect.left) * (canvas.width / rect.width)
        const sy = (e.clientY - rect.top) * (canvas.height / rect.height)
        const target = hitTest(sx, sy, icons, zoom, offset.x, offset.y, canvas.width, canvas.height, null, iconBaseWidth, iconBaseHeight)
        if (target >= 0 && target !== d.idx) {
          if (reorderMode) onReorderIcons?.(d.idx, target)
          else onSwapIcons?.(d.idx, target)
        }
      }
    } else if (Math.abs(d.dx) > 0.001 || Math.abs(d.dy) > 0.001) {
      if (d.multi && selectedIndices.length > 1) {
        onMoveIcons?.(selectedIndices, d.dx, d.dy)
      } else {
        onMoveIcon?.(d.idx, d.dx, d.dy)
      }
    }

    drag.current = null
    scheduleRepaint()
  }, [icons, zoom, offset, ghostDrag, reorderMode, onSwapIcons, onReorderIcons, onMoveIcon, onMoveIcons, scheduleRepaint, selectedIndices, onSelectionChange, iconBaseWidth, iconBaseHeight])

  const handleWheel = useCallback((e) => {
    e.preventDefault()
    onZoomChange?.(Math.max(4, Math.min(20, zoom + (e.deltaY > 0 ? -1 : 1))))
  }, [zoom, onZoomChange])

  return (
    <div ref={containerRef} style={{ flex: 1, minHeight: 0, minWidth: 0, background: 'var(--color-bg-deep)', overflow: 'hidden' }}>
      <canvas
        ref={canvasRef}
        width={canvasSize.w}
        height={canvasSize.h}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
        onContextMenu={(e) => {
          e.preventDefault()
          if (onContextMenu) {
            const rect = canvasRef.current.getBoundingClientRect()
            const sx = (e.clientX - rect.left) * (canvasRef.current.width / rect.width)
            const sy = (e.clientY - rect.top) * (canvasRef.current.height / rect.height)
            const idx = hitTest(sx, sy, icons, zoom, offset.x, offset.y, canvasRef.current.width, canvasRef.current.height, null, iconBaseWidth, iconBaseHeight)
            if (idx >= 0) {
              if (!selectedIndices.includes(idx)) onSelectionChange?.([idx])
              onContextMenu(e.clientX, e.clientY)
            }
          }
        }}
        style={{ display: 'block', width: '100%', height: '100%' }}
      />
    </div>
  )
}
