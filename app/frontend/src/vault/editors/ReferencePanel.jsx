import { useRef, useState } from 'react'
import { extractPalette } from './colorUtils'

/**
 * ReferencePanel - load the picture you are copying and take its colors.
 *
 * Two ways in, because people work both ways: eyedrop a single pixel straight
 * off the reference, or pull its whole palette out at once and click swatches
 * as you paint. Either way the color lands in the same `drawColor` the canvas
 * tools use, so nothing here needs its own concept of "the current color".
 *
 * The reference is view-only scratch state: it is never saved with the costume
 * and never reaches the viewer.
 */
export default function ReferencePanel({ drawColor, setDrawColor, onPickColor }) {
  const fileInputRef = useRef(null)
  const imageRef = useRef(null)
  const [src, setSrc] = useState(null)
  const [name, setName] = useState('')
  const [palette, setPalette] = useState([])
  const [paletteSize, setPaletteSize] = useState(8)
  const [error, setError] = useState(null)

  const loadFile = (file) => {
    if (!file) return
    setError(null)
    setPalette([])
    setName(file.name)
    const reader = new FileReader()
    reader.onload = () => setSrc(String(reader.result))
    reader.onerror = () => setError('Could not read that image.')
    reader.readAsDataURL(file)
  }

  // The <img> is laid out at whatever size the panel gives it, so sample from
  // an offscreen canvas at the image's NATURAL size and scale the click into it
  // -- picking off the displayed element would sample a resampled pixel.
  const imageData = () => {
    const img = imageRef.current
    if (!img || !img.naturalWidth) return null
    const canvas = document.createElement('canvas')
    canvas.width = img.naturalWidth
    canvas.height = img.naturalHeight
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    ctx.drawImage(img, 0, 0)
    return ctx.getImageData(0, 0, canvas.width, canvas.height)
  }

  const pickAt = (event) => {
    const img = imageRef.current
    if (!img) return
    const rect = img.getBoundingClientRect()
    const x = Math.floor((event.clientX - rect.left) * (img.naturalWidth / rect.width))
    const y = Math.floor((event.clientY - rect.top) * (img.naturalHeight / rect.height))
    const data = imageData()
    if (!data) return
    const i = (Math.min(Math.max(y, 0), data.height - 1) * data.width +
               Math.min(Math.max(x, 0), data.width - 1)) * 4
    const hex = '#' + [data.data[i], data.data[i + 1], data.data[i + 2]]
      .map(c => c.toString(16).padStart(2, '0')).join('')
    onPickColor ? onPickColor(hex) : setDrawColor(hex)
  }

  const analyze = () => {
    const data = imageData()
    if (!data) { setError('Load a reference image first.'); return }
    const found = extractPalette(data, paletteSize)
    setPalette(found)
    if (!found.length) setError('No colors found in that image.')
  }

  const clear = () => {
    setSrc(null); setName(''); setPalette([]); setError(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  return (
    <div className="skin-creator-reference">
      <div className="reference-header">
        <span className="reference-title">Reference</span>
        <div className="reference-actions">
          <button type="button" onClick={() => fileInputRef.current?.click()}
            title="Load an image to copy colors from">
            {src ? 'Change' : 'Load image'}
          </button>
          {src && <button type="button" onClick={clear} title="Remove the reference image">Clear</button>}
        </div>
      </div>

      <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }}
        onChange={(e) => loadFile(e.target.files?.[0])} />

      {!src ? (
        <p className="reference-empty">
          Load a picture you want to match, then eyedrop its colors or pull out its palette.
        </p>
      ) : (
        <>
          <div className="reference-image-wrap" title="Click the image to pick that color">
            <img ref={imageRef} src={src} alt={name || 'Reference'} onClick={pickAt} draggable="false" />
          </div>
          <div className="reference-palette-bar">
            <button type="button" className="palette-analyze-btn" onClick={analyze}>
              Get palette
            </button>
            <input type="number" className="max-groups-input" min="2" max="16" value={paletteSize}
              aria-label="Palette size"
              onChange={(e) => setPaletteSize(Math.min(16, Math.max(2, parseInt(e.target.value) || 8)))}
              title="How many colors to pull out" />
          </div>
        </>
      )}

      {error && <div role="alert" className="reference-error">{error}</div>}

      {palette.length > 0 && (
        <div className="reference-swatches" role="group" aria-label="Reference palette">
          {palette.map(entry => (
            <button
              type="button"
              key={entry.color}
              className={`reference-swatch${drawColor?.toLowerCase() === entry.color ? ' selected' : ''}`}
              style={{ background: entry.color }}
              aria-label={`Use ${entry.color}`}
              title={`${entry.color} — click to paint with it`}
              onClick={() => (onPickColor ? onPickColor(entry.color) : setDrawColor(entry.color))}
            />
          ))}
        </div>
      )}
    </div>
  )
}
