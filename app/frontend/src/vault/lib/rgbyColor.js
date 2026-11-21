/**
 * RGBY Color Conversion Utilities
 *
 * RGBY is a 16-bit color format used in Super Smash Bros. Melee for effects.
 * Format: 2 bytes representing color in a packed format.
 *
 * Known RGBY values:
 * FC 00 = Red       | 0F F0 = Green      | 00 FF = Blue
 * FF FF = White     | 00 10 = Black      | FC 1F = Magenta
 * 0F 0F = Turquoise | BB B1 = Yellow     | A5 0F = Purple
 */

/**
 * Convert RGBY (16-bit) to approximate RGB
 * RGBY format appears to be similar to RGB565 with some variations
 *
 * @param {string} rgby - 4-character hex string (e.g., "FC00")
 * @returns {{ r: number, g: number, b: number, hex: string }}
 */
export function rgbyToRgb(rgby) {
  // Normalize input
  const hex = rgby.replace(/\s/g, '').toUpperCase()
  if (hex.length !== 4) {
    return { r: 128, g: 128, b: 128, hex: '#808080' }
  }

  // Parse the two bytes
  const byte1 = parseInt(hex.substring(0, 2), 16) // RG byte
  const byte2 = parseInt(hex.substring(2, 4), 16) // BY byte

  // Extract components (approximate RGB565-like format)
  // High nibble of byte1 = Red intensity
  // Low nibble of byte1 + high nibble of byte2 = Green intensity
  // Low nibble of byte2 = Blue intensity

  const r = (byte1 >> 4) & 0x0F
  const g = ((byte1 & 0x0F) + ((byte2 >> 4) & 0x0F)) / 2
  const b = byte2 & 0x0F

  // Scale from 0-15 to 0-255
  const red = Math.round((r / 15) * 255)
  const green = Math.round((g / 15) * 255)
  const blue = Math.round((b / 15) * 255)

  return {
    r: red,
    g: green,
    b: blue,
    hex: `#${red.toString(16).padStart(2, '0')}${green.toString(16).padStart(2, '0')}${blue.toString(16).padStart(2, '0')}`
  }
}

/**
 * Convert RGB to RGBY (16-bit)
 *
 * @param {number} r - Red (0-255)
 * @param {number} g - Green (0-255)
 * @param {number} b - Blue (0-255)
 * @returns {string} 4-character RGBY hex string
 */
export function rgbToRgby(r, g, b) {
  // Scale from 0-255 to 0-15
  const red = Math.round((r / 255) * 15)
  const green = Math.round((g / 255) * 15)
  const blue = Math.round((b / 255) * 15)

  // Pack into RGBY format
  // Byte 1: High nibble = R, Low nibble = G (high part)
  // Byte 2: High nibble = G (low part) + brightness, Low nibble = B
  const byte1 = ((red & 0x0F) << 4) | (green & 0x0F)
  const byte2 = ((green & 0x0F) << 4) | (blue & 0x0F)

  return byte1.toString(16).padStart(2, '0').toUpperCase() +
         byte2.toString(16).padStart(2, '0').toUpperCase()
}

/**
 * Convert HEX color to RGBY
 *
 * @param {string} hex - Hex color (e.g., "#FF0000" or "FF0000")
 * @returns {string} 4-character RGBY hex string
 */
export function hexToRgby(hex) {
  const clean = hex.replace('#', '')
  const r = parseInt(clean.substring(0, 2), 16)
  const g = parseInt(clean.substring(2, 4), 16)
  const b = parseInt(clean.substring(4, 6), 16)
  return rgbToRgby(r, g, b)
}

/**
 * Convert RGBY to HEX color
 *
 * @param {string} rgby - 4-character RGBY hex string
 * @returns {string} Hex color string with # prefix
 */
export function rgbyToHex(rgby) {
  return rgbyToRgb(rgby).hex
}

/**
 * Format RGBY for display (with space between bytes)
 *
 * @param {string} rgby - 4-character RGBY hex string
 * @returns {string} Formatted string (e.g., "FC 00")
 */
export function formatRgby(rgby) {
  const clean = rgby.replace(/\s/g, '').toUpperCase()
  if (clean.length !== 4) return rgby
  return `${clean.substring(0, 2)} ${clean.substring(2, 4)}`
}

