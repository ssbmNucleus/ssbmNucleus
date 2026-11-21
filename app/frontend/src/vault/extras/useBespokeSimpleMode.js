import { useState, useCallback } from 'react'
import { displayColor } from './editorRecipe.js'

/**
 * useBespokeSimpleMode - Simple/Advanced toggle for the bespoke extras editors
 * (LaserEditorModal, ShineEditorModal, EffectEditorPage).
 *
 * These editors do NOT store colors as a flat per-offset "RRGGBB" map the way
 * EffectEditorPage does -- each layer has its OWN storage format (RGBY for
 * the matrix layers, RGB 6-hex for the core/texture layers, plus exotic
 * 42_48 / CF / 070707 layers). The generic relativeRecolor macro emits plain
 * RGB hex and can't know a layer's on-disk format, so it can't be wired here
 * without corrupting the RGBY-format saves.
 *
 * Instead, Simple mode here shows ONE color picker whose choice is fanned out
 * to every controllable layer IN THAT LAYER'S NATIVE FORMAT via a `fanOut`
 * callback the editor supplies (the editor already knows its formats -- this
 * is exactly what its existing "Apply to all" preset buttons do, just driven
 * by a live picker instead of 6 fixed presets). Advanced mode is the editor's
 * existing per-layer pickers, byte-identical to before. Save/vault shape is
 * unchanged: `fanOut` writes into the SAME `colors` state the editor saves.
 *
 * @param {string} representativeHex current representative layer, "#RRGGBB" or "RRGGBB"
 * @param {Function} fanOut      (hex "#RRGGBB") => partial colors object in
 *                               each layer's native format, merged into state
 */
export function useBespokeSimpleMode(representativeHex, fanOut) {
  const [simpleMode, setSimpleMode] = useState(true)
  // The swatch follows the actual recipe when opening a mod or editing an
  // Advanced layer; keeping a second color state allowed it to go stale.
  const simpleColor = displayColor(representativeHex)

  const applySimpleColor = useCallback((hex) => {
    const h = (hex || '').startsWith('#') ? hex : `#${hex}`
    fanOut(h)
  }, [fanOut])

  return { simpleMode, setSimpleMode, simpleColor, applySimpleColor }
}
