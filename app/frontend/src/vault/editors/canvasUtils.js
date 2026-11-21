// Pure canvas drawing helpers for the paint canvas (no React state)

// An area selection is {x, y, w, h} in TEXTURE pixels, or null for "the whole
// texture". Every tool takes it and refuses to touch a pixel outside it, so a
// selection is a real mask rather than a drawing aid.
export const inSelection = (selection, x, y) => !selection ||
  (x >= selection.x && x < selection.x + selection.w &&
   y >= selection.y && y < selection.y + selection.h)

// Drag start/end -> a normalized rect clamped to the canvas. Zero-area drags
// (a plain click) return null = "clear the selection".
export const selectionFromDrag = (canvas, start, end) => {
  if (!canvas || !start || !end) return null
  const clampX = (v) => Math.max(0, Math.min(canvas.width, v))
  const clampY = (v) => Math.max(0, Math.min(canvas.height, v))
  const x0 = clampX(Math.min(start.x, end.x))
  const y0 = clampY(Math.min(start.y, end.y))
  const x1 = clampX(Math.max(start.x, end.x) + 1)
  const y1 = clampY(Math.max(start.y, end.y) + 1)
  const w = x1 - x0, h = y1 - y0
  return w > 0 && h > 0 && (w > 1 || h > 1) ? { x: x0, y: y0, w, h } : null
}

export const parseColor = (color) => {
  const scratch = document.createElement('canvas')
  scratch.width = scratch.height = 1
  const ctx = scratch.getContext('2d')
  ctx.fillStyle = color
  ctx.fillRect(0, 0, 1, 1)
  return ctx.getImageData(0, 0, 1, 1).data
}

export const getCanvasCoords = (canvas, e) => {
  if (!canvas) return null
  const rect = canvas.getBoundingClientRect()
  const scaleX = canvas.width / rect.width
  const scaleY = canvas.height / rect.height
  return {
    x: Math.floor((e.clientX - rect.left) * scaleX),
    y: Math.floor((e.clientY - rect.top) * scaleY)
  }
}

export const drawBrush = (canvas, x, y, color, size, selection = null) => {
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = color

  if (size === 1) {
    if (inSelection(selection, x, y)) ctx.fillRect(x, y, 1, 1)
  } else {
    // Draw a square brush centered on the point
    const offset = Math.floor(size / 2)
    for (let dy = 0; dy < size; dy++) {
      for (let dx = 0; dx < size; dx++) {
        const px = x - offset + dx
        const py = y - offset + dy
        if (px >= 0 && px < canvas.width && py >= 0 && py < canvas.height &&
            inSelection(selection, px, py)) {
          ctx.fillRect(px, py, 1, 1)
        }
      }
    }
  }
}

export const eraseBrush = (canvas, x, y, size, selection = null) => {
  if (!canvas) return
  const ctx = canvas.getContext('2d')

  const offset = Math.floor(size / 2)
  for (let dy = 0; dy < size; dy++) {
    for (let dx = 0; dx < size; dx++) {
      const px = x - offset + dx
      const py = y - offset + dy
      if (px >= 0 && px < canvas.width && py >= 0 && py < canvas.height &&
          inSelection(selection, px, py)) {
        ctx.clearRect(px, py, 1, 1)
      }
    }
  }
}

// Repaint EVERY pixel of one color, not just the contiguous blob the bucket
// would reach: a costume's colors are scattered across the sheet, so "make all
// the red parts blue" is a different job from filling a region.
export const replaceColor = (canvas, startX, startY, fillColor,
                             { tolerance = 0, selection = null } = {}) => {
  if (!canvas) return 0
  const ctx = canvas.getContext('2d')
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const data = imageData.data
  const fill = parseColor(fillColor)

  const startIdx = (startY * canvas.width + startX) * 4
  const target = [data[startIdx], data[startIdx + 1], data[startIdx + 2], data[startIdx + 3]]
  // Clicking empty space has no color to replace, and matching on alpha alone
  // would paint EVERY transparent pixel on the sheet solid. Use the bucket if
  // you actually want to fill a hole.
  if (target[3] === 0) return 0
  if (target[0] === fill[0] && target[1] === fill[1] &&
      target[2] === fill[2] && target[3] === fill[3]) return 0

  // Tolerance is a per-channel distance on RGB; alpha must match exactly so a
  // replace can never punch holes in (or fill in) the transparent background.
  let changed = 0
  for (let y = 0; y < canvas.height; y++) {
    for (let x = 0; x < canvas.width; x++) {
      if (!inSelection(selection, x, y)) continue
      const i = (y * canvas.width + x) * 4
      if (data[i + 3] !== target[3]) continue
      if (Math.abs(data[i] - target[0]) > tolerance) continue
      if (Math.abs(data[i + 1] - target[1]) > tolerance) continue
      if (Math.abs(data[i + 2] - target[2]) > tolerance) continue
      data[i] = fill[0]
      data[i + 1] = fill[1]
      data[i + 2] = fill[2]
      data[i + 3] = fill[3]
      changed++
    }
  }
  if (changed) ctx.putImageData(imageData, 0, 0)
  return changed
}

export const drawLine = (x0, y0, x1, y1, toolFn) => {
  const dx = Math.abs(x1 - x0)
  const dy = Math.abs(y1 - y0)
  const sx = x0 < x1 ? 1 : -1
  const sy = y0 < y1 ? 1 : -1
  let err = dx - dy

  while (true) {
    toolFn(x0, y0)
    if (x0 === x1 && y0 === y1) break
    const e2 = 2 * err
    if (e2 > -dy) { err -= dy; x0 += sx }
    if (e2 < dx) { err += dx; y0 += sy }
  }
}

export const floodFill = (canvas, startX, startY, fillColor, selection = null) => {
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
  const data = imageData.data
  const width = canvas.width
  const height = canvas.height

  const fillRgba = parseColor(fillColor)

  // Get target color
  const startIdx = (startY * width + startX) * 4
  const targetR = data[startIdx]
  const targetG = data[startIdx + 1]
  const targetB = data[startIdx + 2]
  const targetA = data[startIdx + 3]

  // Don't fill if same color
  if (targetR === fillRgba[0] && targetG === fillRgba[1] &&
      targetB === fillRgba[2] && targetA === fillRgba[3]) return

  const stack = [[startX, startY]]
  const visited = new Set()

  while (stack.length > 0) {
    const [x, y] = stack.pop()
    const key = `${x},${y}`

    if (visited.has(key)) continue
    if (x < 0 || x >= width || y < 0 || y >= height) continue
    if (!inSelection(selection, x, y)) continue

    const idx = (y * width + x) * 4
    if (data[idx] !== targetR || data[idx + 1] !== targetG ||
        data[idx + 2] !== targetB || data[idx + 3] !== targetA) continue

    visited.add(key)
    data[idx] = fillRgba[0]
    data[idx + 1] = fillRgba[1]
    data[idx + 2] = fillRgba[2]
    data[idx + 3] = fillRgba[3]

    stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1])
  }

  ctx.putImageData(imageData, 0, 0)
}

// ---- area selection: paint.net-style move / resize ------------------------
// The overlay is drawn inside the canvas's zoom transform, so every size here
// that should feel constant under the cursor (grab radius, handles) is quoted
// in SCREEN pixels and divided by the zoom before it meets a texture coord.

const ZONE_CURSORS = {
  nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize',
  n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize', inside: 'move'
}

export const selectionCursor = (zone) => ZONE_CURSORS[zone] || 'crosshair'

// Grab radius in texture pixels for a given zoom, so the grips stay ~5px on
// screen whether you are zoomed way out or painting at 30x.
export const gripRadius = (zoom) => 5 / Math.max(zoom || 1, 0.01)

/** Which part of the selection is under the pointer, if any. */
export const selectionHitZone = (selection, x, y, grip = 3) => {
  if (!selection) return null
  const { x: left, y: top, w, h } = selection
  const right = left + w, bottom = top + h
  if (x < left - grip || x > right + grip || y < top - grip || y > bottom + grip) return null
  const onLeft = Math.abs(x - left) <= grip, onRight = Math.abs(x - right) <= grip
  const onTop = Math.abs(y - top) <= grip, onBottom = Math.abs(y - bottom) <= grip
  if (onTop && onLeft) return 'nw'
  if (onTop && onRight) return 'ne'
  if (onBottom && onLeft) return 'sw'
  if (onBottom && onRight) return 'se'
  if (onTop) return 'n'
  if (onBottom) return 's'
  if (onLeft) return 'w'
  if (onRight) return 'e'
  return x >= left && x < right && y >= top && y < bottom ? 'inside' : null
}

// A rect clamped to the texture. Collapsing it to nothing returns null, which
// every caller reads as "no selection" -- same as a plain click.
const clampRect = ({ x, y, w, h }, { width, height }) => {
  const x0 = Math.max(0, Math.min(width, x)), x1 = Math.max(0, Math.min(width, x + w))
  const y0 = Math.max(0, Math.min(height, y)), y1 = Math.max(0, Math.min(height, y + h))
  const rect = { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) }
  return rect.w > 0 && rect.h > 0 ? rect : null
}

/** Drag the whole selection. It keeps its size and stays on the texture. */
export const moveSelection = (selection, dx, dy, { width, height }) => {
  if (!selection) return null
  const w = Math.min(selection.w, width), h = Math.min(selection.h, height)
  return {
    x: Math.max(0, Math.min(width - w, Math.round(selection.x + dx))),
    y: Math.max(0, Math.min(height - h, Math.round(selection.y + dy))),
    w, h
  }
}

/** Drag one edge or corner. Pulling an edge past its opposite flips the rect. */
export const resizeSelection = (origin, zone, dx, dy, bounds) => {
  if (!origin || !zone || zone === 'inside') return origin
  let { x, y, w, h } = origin
  if (zone.includes('w')) { x += dx; w -= dx }
  if (zone.includes('e')) { w += dx }
  if (zone.includes('n')) { y += dy; h -= dy }
  if (zone.includes('s')) { h += dy }
  if (w < 0) { x += w; w = -w }
  if (h < 0) { y += h; h = -h }
  return clampRect({ x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) }, bounds)
}

/** Shift-drag: square off the drag from its start corner. */
export const constrainDrag = (start, end) => {
  const dx = end.x - start.x, dy = end.y - start.y
  const size = Math.max(Math.abs(dx), Math.abs(dy))
  return { x: start.x + (dx < 0 ? -size : size), y: start.y + (dy < 0 ? -size : size) }
}

/** The eight grip points of a selection, in texture coords. */
export const selectionHandles = (selection) => {
  if (!selection) return []
  const { x, y, w, h } = selection
  const midX = x + w / 2, midY = y + h / 2, right = x + w, bottom = y + h
  return [
    { zone: 'nw', x, y }, { zone: 'n', x: midX, y }, { zone: 'ne', x: right, y },
    { zone: 'w', x, y: midY }, { zone: 'e', x: right, y: midY },
    { zone: 'sw', x, y: bottom }, { zone: 's', x: midX, y: bottom }, { zone: 'se', x: right, y: bottom }
  ]
}
