/**
 * currentExtraState - pure helpers behind the extras panel's "Currently in
 * MEX" card (useExtras + ExtrasView).
 *
 * The card reads the project's DAT through GET /storage/extras/current. Two
 * things make that racy: the user can switch effect or fighter while a read
 * is in flight, and an install/restore re-reads after it finishes. Every
 * read is therefore tagged with the fighter/effect it was made for and only
 * the newest read for the selection still on screen may land.
 */

export const currentKey = (fighterName, typeId) => `${fighterName}\u0000${typeId}`

/**
 * Tracks which fighter/effect is on screen and which read is the newest.
 *
 *   select(key)   the selection changed (or is being re-read): every read
 *                 already in flight becomes stale. Returns true when the key
 *                 differs from the previous one.
 *   begin(key)    start a read for `key`. Returns a token, or null when `key`
 *                 is no longer the selection (a stale closure asked).
 *   accepts(tok)  may this read's answer be shown?
 */
export function createRequestGate() {
  let seq = 0
  let activeKey = null
  return {
    select(key) {
      const changed = key !== activeKey
      activeKey = key
      seq += 1
      return changed
    },
    begin(key) {
      if (key == null || key !== activeKey) return null
      seq += 1
      return { seq, key }
    },
    accepts(token) {
      return !!token && token.seq === seq && token.key === activeKey
    },
  }
}

export const IDLE_CURRENT = Object.freeze({ phase: 'idle', key: null })

export const loadingCurrent = key => ({ phase: 'loading', key })

/** The reading to show for `key`: a reading of anything else is "Loading". */
export function currentForSelection(current, key) {
  if (key == null) return IDLE_CURRENT
  return current?.key === key ? current : loadingCurrent(key)
}

const STATUSES = ['vanilla', 'custom', 'unknown']

/**
 * A reading's verdict. The backend's `status` is authoritative ('unknown'
 * = it could not locate or cannot detect what is installed); readings
 * without one fall back to isVanilla.
 */
export function readingStatus(data) {
  if (STATUSES.includes(data?.status)) return data.status
  return data?.isVanilla === true ? 'vanilla' : 'custom'
}

/**
 * A successful read. `readId` changes on every read so an installed image
 * can be re-fetched (cache-busted) after an install.
 *
 * - `image`: an image effect is installed (image shines). Its colors are
 *   empty on purpose -- the game no longer draws the colored model.
 * - `parts`: a unit's nested parts, each read the same way as the primary.
 * - `unknownLayers`: layers that could not be located in the project file.
 */
export function currentFromResponse(key, data, readId = 0) {
  const parts = data?.parts && typeof data.parts === 'object' ? data.parts : null
  const status = readingStatus(data)
  return {
    phase: 'ready',
    key,
    readId,
    status,
    colors: data?.colors || {},
    isVanilla: status === 'vanilla',
    image: data?.imageInstalled ? (data.image || {}) : null,
    sidebModel: data?.sidebModel || null,
    unknownLayers: Array.isArray(data?.unknownLayers) ? data.unknownLayers : [],
    detail: typeof data?.detail === 'string' ? data.detail : '',
    approximate: data?.approximate === true,
    parts,
  }
}

export function currentFromError(key, err) {
  return {
    phase: 'error',
    key,
    error: err?.message || 'Could not read the project file',
  }
}

const STATUS_LABELS = { vanilla: 'Vanilla', custom: 'Custom', unknown: 'Unknown' }

/** Heading shown on the card. Never claims Vanilla before a read landed. */
export function currentLabel(current) {
  switch (current?.phase) {
    case 'ready':
      if (current.image) return 'Image effect'
      if (current.sidebModel) return 'Afterimage model'
      return STATUS_LABELS[current.status] || 'Custom'
    case 'error':
      return "Couldn't read"
    default:
      return 'Loading...'
  }
}

/**
 * The restore-vanilla × shows on any landed read that is not confirmed
 * vanilla (custom, image, or unknown -- restore locates what it rewrites
 * itself and reports what it could not), never while loading or failed.
 */
export const canRestoreCurrent = current =>
  current?.phase === 'ready' && current.isVanilla === false

/** Colors to preview, or null when there is nothing trustworthy to draw. */
export const currentPreviewColors = current =>
  current?.phase === 'ready' && !current.image && !current.sidebModel && current.status !== 'unknown'
    ? current.colors
    : null

/** One short line under the card heading explaining the reading, or ''. */
export function currentNote(current) {
  if (current?.phase === 'error') return 'The project file could not be read'
  if (current?.phase !== 'ready') return ''
  if (current.sidebModel) return 'Imported Side-B model'
  if (current.image) {
    const size = currentImageSize(current)
    return size ? `${size} image` : ''
  }
  if (current.status === 'unknown') {
    return current.detail || "Couldn't locate these colors in the project file"
  }
  const missing = current.unknownLayers?.length || 0
  if (missing) return `${missing} layer${missing === 1 ? '' : 's'} couldn't be read`
  if (current.approximate) return 'Approximate color (from the texture)'
  return ''
}

const sameColor = (a, b) =>
  typeof a === 'string' && typeof b === 'string' && a.toUpperCase() === b.toUpperCase()

// Every color the read reported equals the recipe's color for that layer.
const recipeCovers = (recipe, colors) => {
  const layers = Object.entries(colors || {})
  return layers.length > 0 &&
    layers.every(([layer, color]) => sameColor(recipe?.[layer]?.color, color))
}

/**
 * The vault mod whose recipe is exactly what the file holds, or null.
 *
 * Only for a clean custom reading (no unread layers, not an image, not an
 * approximate texture swatch). Every reported color must equal the mod's
 * color for that layer, and every part the read reported must equal the
 * mod's recipe for it (or read vanilla when the mod has no such part).
 * Several matching mods name none: a guess is worse than no name.
 */
export function matchInstalledMod(current, mods) {
  if (current?.phase !== 'ready' || current.status !== 'custom') return null
  if (current.sidebModel) {
    const matches = (mods || []).filter(mod =>
      current.sidebModel.sha256 && mod?.modifications?.sideb_model?.sha256 === current.sidebModel.sha256)
    return matches.length === 1 ? matches[0] : null
  }
  if (current.image || current.approximate || current.unknownLayers?.length) return null
  const matches = (mods || []).filter(mod => {
    const recipe = mod?.modifications
    if (!recipe || typeof recipe !== 'object' || recipe.image) return false
    if (!recipeCovers(recipe, current.colors)) return false
    return Object.entries(current.parts || {}).every(([partId, reading]) => {
      const partRecipe = recipe.parts?.[partId]
      if (partRecipe && Object.keys(partRecipe).length) {
        return readingStatus(reading) !== 'unknown' && recipeCovers(partRecipe, reading.colors)
      }
      return readingStatus(reading) === 'vanilla'
    })
  })
  return matches.length === 1 ? matches[0] : null
}

/**
 * Model swaps: which model is installed can't be read back from the file,
 * so the card says so instead of implying anything.
 */
export const MODEL_CURRENT = Object.freeze({
  label: "Can't detect",
  note: "Nucleus can't tell which model is installed. Pick one below to replace it, or × to put the vanilla one back.",
})

/** "64x64" for an installed image, or '' when the size is unknown. */
export function currentImageSize(current) {
  const w = current?.image?.width
  const h = current?.image?.height
  return w && h ? `${w}x${h}` : ''
}

/**
 * One card per unit part the read reported, in the unit's configured order
 * (`unitParts` = getUnitParts(fighter, type), each {id, name}). Parts the
 * read did not report (e.g. their file is missing) are left out rather than
 * shown as vanilla.
 */
export function currentPartCards(current, unitParts) {
  if (current?.phase !== 'ready' || !current.parts) return []
  return (unitParts || [])
    .filter(part => part && current.parts[part.id])
    .map(part => {
      const reading = current.parts[part.id]
      const status = readingStatus(reading)
      return {
        id: part.id,
        type: part,
        name: part.name || part.id,
        status,
        colors: status === 'unknown' ? null : (reading.colors || {}),
        label: STATUS_LABELS[status],
        isVanilla: status === 'vanilla',
      }
    })
}
