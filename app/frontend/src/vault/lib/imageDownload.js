/**
 * Save an image the app is already showing (a portrait, a stock icon, a stage
 * preview) out to a file.
 *
 * An anchor's `download` attribute is only honoured for a same-origin href, and
 * these images live on the backend (127.0.0.1:<port>) while the app itself runs
 * from file:// -- a plain link would open the image instead of saving it. So the
 * bytes are fetched first and handed over as a blob URL, which keeps the
 * filename we picked. Electron then prompts for where to put it.
 */
import { backendMediaUrl } from '../../shared/config/config.js'

/** Trim a name down to what every filesystem accepts. */
export function safeFilePart(value, fallback = 'export') {
  const cleaned = String(value ?? '')
    .trim()
    .replace(/[^\w.-]+/g, '_')
    .replace(/^[_.]+/, '')
    .replace(/[_.]+$/, '')
  return cleaned || fallback
}

/** `.png` unless the source URL names another image type. */
export function imageExtension(url) {
  const path = String(url || '').split(/[?#]/)[0]
  const match = /\.(png|jpe?g|gif|webp|bmp|tga)$/i.exec(path)
  return match ? `.${match[1].toLowerCase()}` : '.png'
}

/** Build `<parts joined by _><ext>`, dropping empty parts. */
export function imageFilename(parts, url) {
  const stem = parts.filter(Boolean).map((p) => safeFilePart(p)).filter(Boolean).join('_')
  return `${stem || 'image'}${imageExtension(url)}`
}

export async function downloadImage(src, filename) {
  if (!src) throw new Error('There is no image here to export')
  // A just-rendered preview is already a data: URI; fetch reads those directly.
  const href = src.startsWith('data:') ? src : backendMediaUrl(src)
  const response = await fetch(href)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  try { link.click() } finally { link.remove(); URL.revokeObjectURL(url) }
}
