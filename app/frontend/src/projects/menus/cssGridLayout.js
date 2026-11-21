/**
 * CSS (Character Select Screen) grid layout math.
 *
 * Shared by the CSS layout editor (manual "Columns" control) and the
 * auto-layout that runs whenever characters are added to / removed from the
 * project, so both produce identical grids: centered rows (including a
 * centered trailing partial row), edge-column side drops, and per-axis
 * scaling that keeps the grid inside the vanilla 9x3 bounding box.
 *
 * L-load alternates (`altExternalIds`) keep a CSS icon tucked behind their
 * base's (docs/dev/L_LOAD.md). Those icons never take a grid slot: they are
 * left untouched in place and the backend re-tucks them on every save.
 */

// Vanilla 9x3 grid boundaries (game units)
export const CSS_VANILLA_WIDTH = 63.45  // 9 * 7.05
export const CSS_VANILLA_HEIGHT = 21.6  // 3 * 7.2
export const CSS_ICON_BASE_WIDTH = 7.05
export const CSS_ICON_BASE_HEIGHT = 7.2
export const CSS_GRID_CENTER_X = 0.05
export const CSS_GRID_CENTER_Y = 9.5

/**
 * Lay icons out on the template grid. Centers every row (partial trailing
 * rows included) and applies the template's edge-column side drops. Icons
 * whose fighter is in `altExternalIds` (tucked) are returned as they were.
 */
export function applyCssTemplate(icons, template, altExternalIds = []) {
  const { iconsPerRow, scaleX, scaleY, centerX, centerY, iconWidth, iconHeight,
          iconSideDropX, iconSideDropY, iconSideDropZ } = template
  const tucked = new Set(altExternalIds)
  const count = gridIcons(icons, altExternalIds).length
  if (count === 0 || iconsPerRow <= 0) return icons

  const rows = Math.ceil(count / iconsPerRow)
  const iw = iconWidth * scaleX
  const ih = iconHeight * scaleY
  const totalW = Math.min(count, iconsPerRow) * iw
  const totalH = rows * ih

  let slot = 0
  return icons.map((icon) => {
    if (tucked.has(icon.fighter)) return icon
    const i = slot++
    const col = i % iconsPerRow
    const row = Math.floor(i / iconsPerRow)
    const iconsInRow = row === rows - 1 ? count - row * iconsPerRow : iconsPerRow
    const isEdge = col === 0 || col === iconsInRow - 1

    // Center partial rows (e.g. a trailing row of 8 in a 9-wide grid)
    const rowOffsetX = (iconsPerRow - iconsInRow) * iw / 2

    let x = centerX - totalW / 2 + iw * col + iw / 2 + rowOffsetX
    let y = centerY + totalH / 2 - ih * row - ih / 2
    let z = 0
    let colOffX = 0, colOffY = 0

    if (isEdge) {
      colOffX = -iconSideDropX
      colOffY = -iconSideDropY
      z = iconSideDropZ
    }

    return {
      ...icon,
      x, y, z,
      scaleX, scaleY,
      collisionSizeX: iconWidth,
      collisionSizeY: iconHeight,
      collisionOffsetX: colOffX,
      collisionOffsetY: colOffY
    }
  })
}

/**
 * Template for a `cols`-wide grid of `count` icons, scaled per-axis to fill
 * the vanilla bounding box exactly.
 */
export function buildCssGridTemplate(template, count, cols) {
  const rows = Math.max(1, Math.ceil(count / cols))
  return {
    ...template,
    iconsPerRow: cols,
    scaleX: CSS_VANILLA_WIDTH / (cols * CSS_ICON_BASE_WIDTH),
    scaleY: CSS_VANILLA_HEIGHT / (rows * CSS_ICON_BASE_HEIGHT),
    iconWidth: CSS_ICON_BASE_WIDTH,
    iconHeight: CSS_ICON_BASE_HEIGHT,
    centerX: CSS_GRID_CENTER_X,
    centerY: CSS_GRID_CENTER_Y
  }
}

/**
 * Pick the column count that keeps the icons closest to their natural
 * (vanilla) aspect: maximize the smaller of the two axis scales. Ties go to
 * fewer rows. 27 icons -> 9x3 (vanilla), 28-30 -> 10x3, ~40 -> 10x4, etc.
 */
export function pickAutoColumns(count) {
  if (count <= 0) return 9
  let bestCols = Math.min(count, 9)
  let bestScore = -Infinity
  for (let rows = 1; rows <= Math.min(8, count); rows++) {
    const cols = Math.ceil(count / rows)
    const sx = CSS_VANILLA_WIDTH / (cols * CSS_ICON_BASE_WIDTH)
    const sy = CSS_VANILLA_HEIGHT / (rows * CSS_ICON_BASE_HEIGHT)
    const score = Math.min(sx, sy)
    if (score > bestScore + 1e-9) {
      bestScore = score
      bestCols = cols
    }
  }
  return bestCols
}

/** The icons that take a grid slot: everything but tucked L-load alternates. */
export function gridIcons(icons, altExternalIds = []) {
  if (altExternalIds.length === 0) return icons
  const tucked = new Set(altExternalIds)
  return icons.filter(icon => !tucked.has(icon.fighter))
}

/**
 * Full auto-layout: choose columns for the visible icon count, rebuild the
 * template, and reposition every visible icon (tucked alternates stay put).
 * Returns { icons, template } ready to POST to /menus/css/layout.
 */
export function computeAutoCssLayout(icons, template, altExternalIds = []) {
  const count = gridIcons(icons, altExternalIds).length
  const cols = pickAutoColumns(count)
  const newTemplate = buildCssGridTemplate(template, count, cols)
  return { icons: applyCssTemplate(icons, newTemplate, altExternalIds), template: newTemplate }
}
