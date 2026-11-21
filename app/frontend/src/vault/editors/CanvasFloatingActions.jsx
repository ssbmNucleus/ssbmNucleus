import { useRef } from 'react'

// Floating Import/Export buttons over the paint canvas.
export default function CanvasFloatingActions({ onImport, onExport }) {
  const textureImportRef = useRef(null)

  return (
    <div className="canvas-floating-actions" onMouseDown={event => event.stopPropagation()} onMouseMove={event => event.stopPropagation()}>
      <input
        ref={textureImportRef}
        type="file"
        accept="image/png,image/jpeg,image/gif"
        style={{ display: 'none' }}
        onChange={onImport}
      />
      <button
        className="canvas-float-btn"
        onClick={() => textureImportRef.current?.click()}
        title="Import texture from file"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/>
          <line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
        Import
      </button>
      <button
        className="canvas-float-btn"
        onClick={onExport}
        title="Export texture as PNG"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Export
      </button>
    </div>
  )
}
