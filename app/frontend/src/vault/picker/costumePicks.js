// What the fighter/costume picker (CostumePicker.jsx) offers and what a pick is.
// Pure: no React, no fetch, no backend URL (paths are backend-relative; the
// component turns them into URLs). Extensioned imports so node's test runner loads it.
import { DEFAULT_CHARACTERS } from '../../shared/data/defaultCharacters.js'

/** The 26 Melee fighters, in the Vault's own order (StorageViewer sorts them by name). */
export const ROSTER = Object.keys(DEFAULT_CHARACTERS).sort()

const part = encodeURIComponent
/** The fighter's character-select icon, extracted from the user's ISO at setup (as the Vault grid shows it). */
export const cssIconPath = (character) => `/vanilla/${part(character)}/css_icon.png`
/** A stock costume's portrait, e.g. /vanilla/Fox/PlFxOr/csp.png. */
export const stockPortraitPath = (character, code) => `/vanilla/${part(character)}/${part(code)}/csp.png`
/** A vault costume's portrait, as the Vault's skin cards build it. */
export const vaultPortraitPath = (character, skin) =>
  `/storage/${part(character)}/${part(skin.csp_filename || `${skin.id}_csp.png`)}`

/** The fighters to offer, in roster order: `only` (a list the backend serves) narrows it, `exclude` drops names. */
export function rosterOf({ only, exclude = [] } = {}) {
  const allowed = Array.isArray(only) && only.length ? new Set(only) : null
  return ROSTER.filter((name) => (!allowed || allowed.has(name)) && !exclude.includes(name))
}

/** A fighter's visible vault costumes as picks (`kind: 'vault'`), in vault order. Nana rows are hidden ones. */
export function vaultCostumes(metadata, character) {
  const skins = metadata?.characters?.[character]?.skins
  return (Array.isArray(skins) ? skins : [])
    .filter((skin) => skin && skin.id && skin.visible !== false)
    .map((skin) => ({
      kind: 'vault', character, id: skin.id,
      name: skin.color || skin.name || skin.id,
      image: skin.has_csp === false ? null : vaultPortraitPath(character, skin),
    }))
}

/** `GET /api/mex/vanilla/costumes/<character>` rows as picks (`kind: 'stock'`), in the game's CSS order. */
export function stockCostumes(rows, character) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => row && typeof row.code === 'string' && row.code)
    .map((row) => ({
      kind: 'stock', character, code: row.code,
      color: row.colorCode || row.code.slice(-2),
      name: row.colorName || row.colorCode || row.code,
      image: row.hasCsp === false ? null : stockPortraitPath(character, row.code),
    }))
}

/**
 * "AI Choice": the model import's first tile. It means "let Randall pick the
 * fighter", so the pick carries no `character` and sends no `fighter`. Melee has
 * no random icon and the app extracts no locked-slot icon from the user's ISO, so
 * the tile draws a "?" (GalleryGrid `glyph`) in the fighters' frame.
 */
export const AI_CHOICE = 'AI Choice'
export const AI_VALUE = '__ai_choice__'
export const aiPick = () => ({ kind: 'fighter', auto: true, character: '', image: null })
const AI_WORDS = 'ai choice random auto automatic any randall picks'

/** The grid value of a pick: `v:<skin id>`, `s:<costume code>`, or the fighter's name. */
export function pickValue(pick) {
  if (!pick) return ''
  if (pick.auto) return AI_VALUE
  if (pick.kind === 'vault') return `v:${pick.id}`
  if (pick.kind === 'stock') return `s:${pick.code}`
  return pick.character || ''
}

/** "Fox · Blue Hoodie", "Fox · Orange (stock)", or the fighter's name. */
export function pickLabel(pick) {
  if (pick?.auto) return AI_CHOICE
  if (!pick?.character) return ''
  if (pick.kind === 'vault') return `${pick.character} · ${pick.name}`
  if (pick.kind === 'stock') return `${pick.character} · ${pick.name} (stock)`
  return pick.character
}

/** Grid options for one fighter's costumes: the vault's first, then the stock slots (badged). */
export function costumeOptions(vault, stock, url = (path) => path) {
  return [
    ...vault.map((pick) => ({ value: pickValue(pick), label: pick.name, icon: pick.image ? url(pick.image) : undefined })),
    ...stock.map((pick) => ({ value: pickValue(pick), label: pick.name, icon: pick.image ? url(pick.image) : undefined, badge: 'Stock' })),
  ]
}

/** Grid options for the fighters; `counts` badges each with its vault costume count. */
export function fighterOptions(fighters, { metadata, counts = false, url = (path) => path, auto = false } = {}) {
  const first = auto ? [{ value: AI_VALUE, label: AI_CHOICE, glyph: '?', keywords: AI_WORDS }] : []
  return first.concat(fighters.map((character) => {
    const count = counts ? vaultCostumes(metadata, character).length : 0
    return { value: character, label: character, icon: url(cssIconPath(character)), ...(count ? { badge: String(count) } : {}) }
  }))
}

/** Options whose label contains `query` (case-insensitive, trimmed); all of them for an empty query. */
export function filterOptions(options, query) {
  const q = String(query || '').trim().toLowerCase()
  return q ? options.filter((option) => `${option.label} ${option.keywords || ''}`.toLowerCase().includes(q)) : options
}
