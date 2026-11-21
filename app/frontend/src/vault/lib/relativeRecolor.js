/**
 * relativeRecolor - the shared "Simple Mode" macro for extras editors.
 *
 * Simple Mode shows ONE color picker per extra whose choice drives ALL layers
 * via a RELATIVE HUE ROTATION: each layer's vanilla color is rotated by
 * (targetHue - extra's vanilla dominant hue), while that layer's OWN
 * saturation and value are preserved. So a pale white core stays pale, dark
 * smoke stays dark -- it is never a flat fill. This is a pure client-side
 * macro that fills the SAME `modifications` object the per-layer (Advanced)
 * pickers fill; there is no save/vault/backend difference.
 *
 * Used by the extras effect editor (extras/EffectEditorPage.jsx) and unit parts (extras/unitParts.js).
 * HSV (not HSL) is used deliberately: "preserve S/V" is the design contract
 * (per docs/EXTRAS_MISSION_TEMPLATE.md editor-polish pattern + task #9/#12).
 */

// --- HSV <-> RGB (self-contained; hex in/out, no '#') -----------------------

export function hexToRgbTriplet(hex) {
  const h = (hex || '').replace('#', '')
  if (h.length < 6) return null
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  }
}

export function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const d = max - min
  let h = 0
  if (d !== 0) {
    if (max === r) h = ((g - b) / d) % 6
    else if (max === g) h = (b - r) / d + 2
    else h = (r - g) / d + 4
    h *= 60
    if (h < 0) h += 360
  }
  const s = max === 0 ? 0 : d / max
  return { h, s, v: max }
}

export function hsvToHex(h, s, v) {
  h = ((h % 360) + 360) % 360
  const c = v * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = v - c
  let r = 0, g = 0, b = 0
  if (h < 60) { r = c; g = x }
  else if (h < 120) { r = x; g = c }
  else if (h < 180) { g = c; b = x }
  else if (h < 240) { g = x; b = c }
  else if (h < 300) { r = x; b = c }
  else { r = c; b = x }
  const to = (n) => {
    const q = Math.round((n + m) * 255)
    const hh = Math.max(0, Math.min(255, q)).toString(16)
    return hh.length === 1 ? '0' + hh : hh
  }
  return `${to(r)}${to(g)}${to(b)}`.toUpperCase()
}

// --- Dominant-hue detection -------------------------------------------------

/**
 * Compute an extra's vanilla dominant hue from its config vanilla values.
 * Saturation-weighted average (skips near-white / near-gray swatches, which
 * carry no meaningful hue and would drag the average). Returns null if every
 * vanilla swatch is achromatic -- callers should fall back to a config
 * `vanillaDominantHue`/`vanillaHue` constant, or 0.
 *
 * `vanilla` is the extraType.vanilla map (layerKey -> "RRGGBB"). We consider
 * every value that is a 6-hex string; color1/color2 summary swatches count
 * too (they mirror the dominant layers), which is harmless for a weighted avg.
 *
 * @param {Object} vanilla   extraType.vanilla
 * @param {Object} [opts]
 * @param {number} [opts.satFloor=0.15]  ignore swatches below this saturation
 * @param {number} [opts.valFloor=0.10]  ignore near-black swatches
 * @returns {number|null} hue in [0,360) or null
 */
export function computeDominantHue(vanilla, opts = {}) {
  const satFloor = opts.satFloor ?? 0.15
  const valFloor = opts.valFloor ?? 0.10
  if (!vanilla) return null
  let sumSin = 0, sumCos = 0, wsum = 0
  for (const key of Object.keys(vanilla)) {
    const val = vanilla[key]
    if (typeof val !== 'string') continue
    const rgb = hexToRgbTriplet(val)
    if (!rgb) continue
    const { h, s, v } = rgbToHsv(rgb.r, rgb.g, rgb.b)
    if (s < satFloor || v < valFloor) continue // skip whites/grays/blacks
    const w = s * v // weight by chroma-ish
    const rad = (h * Math.PI) / 180
    sumSin += Math.sin(rad) * w
    sumCos += Math.cos(rad) * w
    wsum += w
  }
  if (wsum === 0) return null
  let ang = (Math.atan2(sumSin, sumCos) * 180) / Math.PI
  if (ang < 0) ang += 360
  return ang
}

/**
 * Resolve the vanilla dominant hue for an extraType: prefer an explicit config
 * constant (charge_ball's `vanillaDominantHue`, texture extras' `vanillaHue`),
 * else compute saturation-weighted from vanilla values, else 0.
 */
export function resolveDominantHue(extraType) {
  if (!extraType) return 0
  if (typeof extraType.vanillaDominantHue === 'number') return extraType.vanillaDominantHue
  if (typeof extraType.vanillaHue === 'number') return extraType.vanillaHue
  const computed = computeDominantHue(extraType.vanilla)
  return computed == null ? 0 : computed
}

// --- The macro ---------------------------------------------------------------

/**
 * Given a single target color and the extra's vanilla layer map, return a new
 * per-layer color map (layerKey -> "RRGGBB") where every layer is the vanilla
 * color hue-rotated by (targetHue - dominantHue), preserving each layer's own
 * S and V. Achromatic vanilla layers (white core, gray smoke) are left as-is
 * (rotating a hueless color does nothing) so cores/greys stay neutral.
 *
 * @param {string} targetHex  e.g. "00FF00" or "#00FF00"
 * @param {Object} vanilla    extraType.vanilla (layerKey -> "RRGGBB")
 * @param {number} dominantHue vanilla dominant hue (see resolveDominantHue)
 * @param {string[]} [keys]   which layer keys to fill; defaults to all string
 *                            vanilla keys
 * @returns {Object} layerKey -> "RRGGBB"
 */
export function relativeRecolorLayers(targetHex, vanilla, dominantHue, keys) {
  const tgt = hexToRgbTriplet(targetHex)
  const out = {}
  if (!tgt || !vanilla) return out
  const targetHue = rgbToHsv(tgt.r, tgt.g, tgt.b).h
  const delta = targetHue - (dominantHue || 0)
  const layerKeys = keys || Object.keys(vanilla).filter((k) => typeof vanilla[k] === 'string')
  for (const key of layerKeys) {
    const van = vanilla[key]
    const rgb = hexToRgbTriplet(van)
    if (!rgb) continue
    const { h, s, v } = rgbToHsv(rgb.r, rgb.g, rgb.b)
    // Achromatic layers (s ~ 0): no hue to rotate -> keep vanilla. This keeps
    // white cores white and grey smoke grey, exactly as vanilla intended.
    if (s < 0.04) {
      out[key] = (van || '').replace('#', '').toUpperCase()
      continue
    }
    out[key] = hsvToHex(h + delta, s, v)
  }
  return out
}
