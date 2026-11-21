// Nested sibling texture extra color (task #12 migration, 2026-07-02):
// upb.fire / falcon_punch.fire may be saved as the NEW {color: "RRGGBB"}
// shape or the OLD {hue: degrees} shape (back-compat, see
// backend/vault/extras/textures.py). This resolves either to a
// display hex color for the card preview's tint, matching
// EffectEditorPage.jsx's hueToHex conversion.
function hueToHex(hue) {
  const h = (hue % 360) / 360
  const s = 1
  const l = 0.5
  const hue2rgb = (p, q, t) => {
    if (t < 0) t += 1
    if (t > 1) t -= 1
    if (t < 1 / 6) return p + (q - p) * 6 * t
    if (t < 1 / 2) return q
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6
    return p
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  const r = Math.round(hue2rgb(p, q, h + 1 / 3) * 255)
  const g = Math.round(hue2rgb(p, q, h) * 255)
  const b = Math.round(hue2rgb(p, q, h - 1 / 3) * 255)
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`
}

export function nestedTextureHex(fireMod, fallback) {
  if (fireMod?.color) return `#${fireMod.color}`
  if (fireMod?.hue !== undefined && fireMod?.hue !== null) return hueToHex(fireMod.hue)
  return fallback
}
