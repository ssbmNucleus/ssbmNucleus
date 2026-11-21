/**
 * unitParts - pure helpers for a unit's nested parts in the effect editor.
 *
 * A move is one extra whose saved recipe carries its parts under
 * `modifications.parts[<part id>]` (backend: core.extra_types.UNIT_PARTS,
 * vault/extras/unit_parts.py). The page editor keeps part colors in a
 * separate `{ [partId]: { [key]: 'RRGGBB' } }` state; these helpers load it
 * from a mod, fan a whole-effect color into it, and serialize it back in the
 * exact shape the backend installs from. No React, no network.
 */
import { relativeRecolorLayers, resolveDominantHue } from '../lib/relativeRecolor.js'

const CORE_SUFFIX = /_c1$/
const TINT_SUFFIX = /_c2$/

/** The layer keys a part recipe carries: its offset keys, plus labeled props. */
export function partKeys(partType) {
  const keys = [...Object.keys(partType?.offsets || {}),
    ...(partType?.properties || []).map(p => p.id)]
  return [...new Set(keys)]
}

/** Is this part a whole-texture recolor (one color) rather than color layers? */
export function isTexturePart(partType) {
  return partType?.format === 'texture_recolor'
}

/**
 * Part colors for an editor session: the mod's saved part values, else each
 * layer's vanilla, else the c1/c2 summary vanilla, else white.
 */
export function readPartColors(mod, partTypes) {
  const out = {}
  const saved = mod?.modifications?.parts || {}
  for (const type of partTypes) {
    const vanilla = type.vanilla || {}
    const mine = saved[type.id] || {}
    const colors = {}
    for (const key of partKeys(type)) {
      const fallback = vanilla[key] || (TINT_SUFFIX.test(key) ? vanilla.color2 : vanilla.color1) || 'FFFFFF'
      colors[key] = (mine[key]?.color || fallback).replace('#', '').toUpperCase()
    }
    out[type.id] = colors
  }
  return out
}

/**
 * `modifications.parts` for save: every layer of every part, as
 * `{ key: { color } }`. Unset keys fall back to the summary color the same
 * way the standalone editors fan out (_c1 → color1, _c2 → color2).
 */
export function serializePartColors(partColors, partTypes) {
  const parts = {}
  for (const type of partTypes) {
    const colors = partColors[type.id] || {}
    const recipe = {}
    for (const key of partKeys(type)) {
      const value = colors[key]
        || (CORE_SUFFIX.test(key) && colors.color1)
        || (TINT_SUFFIX.test(key) && colors.color2)
      if (value) recipe[key] = { color: value.replace('#', '').toUpperCase() }
    }
    if (Object.keys(recipe).length) parts[type.id] = recipe
  }
  return parts
}

/** A part layer's key in the flat preview map the pictogram reads. */
export function partPreviewKey(partId, key) {
  return `p_${partId}_${key}`
}

/** Flatten part colors into the pictogram's single color map. */
export function flattenPartColors(partColors) {
  const flat = {}
  for (const [partId, colors] of Object.entries(partColors || {})) {
    for (const [key, value] of Object.entries(colors)) flat[partPreviewKey(partId, key)] = value
  }
  return flat
}

/**
 * One whole-effect color applied to a part: texture parts take the color
 * itself; layer parts keep their relative brightness (the same macro the
 * standalone editors use).
 */
export function fanOutPart(targetHex, partType) {
  const rgb = (targetHex || '').replace('#', '').toUpperCase()
  if (isTexturePart(partType)) {
    return { [partType.properties?.[0]?.id || 'color1']: rgb }
  }
  const keys = partKeys(partType)
  const recolored = relativeRecolorLayers(`#${rgb}`, partType.vanilla || {}, resolveDominantHue(partType), keys)
  const out = {}
  for (const key of keys) out[key] = (recolored[key] || rgb).replace('#', '').toUpperCase()
  return out
}
