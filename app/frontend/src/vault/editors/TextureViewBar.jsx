// The bar under the paint canvas: texture name and size, the show-on-model
// probe, hand tool, zoom, fit, and the panel-layout reset.
export default function TextureViewBar({
  modelTextures, selectedTextureIndex, highlighting, flashTexture, selectedTextureId,
  canvasOwner, hand, setHand, zoomBy, zoom,
  actualSize, fit, resetSizes,
}) {
  return (
    <div className="texture-view-bar">
      <span className="texture-view-info" title={modelTextures[selectedTextureIndex]?.name}>
        {modelTextures[selectedTextureIndex]?.name || 'Texture'}
        {modelTextures[selectedTextureIndex] && <small>{modelTextures[selectedTextureIndex].width} × {modelTextures[selectedTextureIndex].height} px</small>}
      </span>
      <div className="texture-view-controls">
        <button type="button" aria-label="Show this texture on the model"
          className={highlighting ? 'is-highlighting' : ''}
          onClick={() => flashTexture(selectedTextureId)}
          disabled={!selectedTextureId || canvasOwner !== selectedTextureId}
          title="Flash this texture on the 3D model to see where it is used">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
            <circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/>
            <path d="M12 1v3M12 20v3M1 12h3M20 12h3"/>
          </svg>
        </button>
        <button type="button" aria-label="Pan texture" aria-pressed={hand} onClick={() => setHand(!hand)} title="Hand tool (or hold Space and drag)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M8 13V6a1.5 1.5 0 0 1 3 0v5-7a1.5 1.5 0 0 1 3 0v7-5a1.5 1.5 0 0 1 3 0v6-3a1.5 1.5 0 0 1 3 0v7c0 4-2 6-6 6h-1c-2 0-4-1-5-3l-4-6a1.5 1.5 0 0 1 2-2l2 2Z"/></svg>
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => zoomBy(0.8)} disabled={zoom <= 0.05}>−</button>
        <button type="button" className="texture-zoom-value" onClick={actualSize} title="Actual size (1)">{Math.round(zoom * 100)}%</button>
        <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1.25)} disabled={zoom >= 64}>+</button>
        <button type="button" onClick={fit} title="Fit texture (0)">Fit</button>
        <button type="button" onClick={resetSizes} title="Restore panel sizes" aria-label="Reset editor layout">↺</button>
      </div>
    </div>
  )
}
