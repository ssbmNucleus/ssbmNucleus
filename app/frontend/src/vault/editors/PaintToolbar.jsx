// Toolbar above the paint canvas: undo/redo, color picker, tools, brush size.
export default function PaintToolbar({
  undo,
  redo,
  canUndo,
  canRedo,
  drawColor,
  setDrawColor,
  activeTool,
  setActiveTool,
  brushSize,
  setBrushSize,
  replaceTolerance,
  setReplaceTolerance,
  selection,
  clearSelection
}) {
  return (
    <div className="skin-creator-toolbar">
      {/* Undo/Redo */}
      <button
        className="toolbar-btn"
        onClick={undo}
        disabled={!canUndo}
        title="Undo (Ctrl+Z)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/>
        </svg>
      </button>
      <button
        className="toolbar-btn"
        onClick={redo}
        disabled={!canRedo}
        title="Redo (Ctrl+Y)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 7v6h-6"/><path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3l3 2.7"/>
        </svg>
      </button>

      <div className="toolbar-separator"></div>

      {/* Color Picker */}
      <div className="color-picker-wrapper">
        <input
          type="color"
          className="color-picker"
          value={drawColor}
          onChange={(e) => setDrawColor(e.target.value)}
          title="Draw Color"
        />
      </div>

      <div className="toolbar-separator"></div>

      {/* Tools */}
      <button
        className={`toolbar-btn ${activeTool === 'pencil' ? 'active' : ''}`}
        onClick={() => setActiveTool('pencil')}
        title="Pencil (draw)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>
        </svg>
      </button>
      <button
        className={`toolbar-btn ${activeTool === 'eraser' ? 'active' : ''}`}
        onClick={() => setActiveTool('eraser')}
        title="Eraser"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/>
          <path d="M22 21H7"/><path d="m5 11 9 9"/>
        </svg>
      </button>
      <button
        className={`toolbar-btn ${activeTool === 'fill' ? 'active' : ''}`}
        onClick={() => setActiveTool('fill')}
        title="Fill Bucket"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2c.8.8 2 .8 2.8 0L19 11Z"/>
          <path d="m5 2 5 5"/><path d="M2 13h15"/><path d="M22 20a2 2 0 1 1-4 0c0-1.6 1.7-2.4 2-4 .3 1.6 2 2.4 2 4Z"/>
        </svg>
      </button>
      <button
        className={`toolbar-btn ${activeTool === 'replace' ? 'active' : ''}`}
        onClick={() => setActiveTool('replace')}
        title="Replace color (recolor every pixel of the color you click)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 7h11a4 4 0 0 1 0 8H8"/><path d="m11 12-3 3 3 3"/>
          <rect x="16" y="3" width="5" height="5" rx="1"/>
        </svg>
      </button>
      <button
        className={`toolbar-btn ${activeTool === 'select' ? 'active' : ''}`}
        onClick={() => setActiveTool('select')}
        title="Select an area — other tools then only paint inside it. Drag inside to move it, an edge or corner to resize, Shift to square it off. Ctrl+A all, Ctrl+D none."
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
             strokeDasharray="4 3">
          <rect x="3" y="3" width="18" height="18" rx="1"/>
        </svg>
      </button>
      <button
        className={`toolbar-btn ${activeTool === 'eyedropper' ? 'active' : ''}`}
        onClick={() => setActiveTool('eyedropper')}
        title="Eyedropper (pick color)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="m2 22 1-1h3l9-9"/><path d="M3 21v-3l9-9"/>
          <path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3l.4.4Z"/>
        </svg>
      </button>

      <div className="toolbar-separator"></div>

      {/* Replace tolerance rides in the Size slot: the two tools never share a
          moment, and the toolbar has no room for both. */}
      {activeTool === 'replace' ? (
        <>
          <span className="toolbar-label">Match:</span>
          <input
            type="range"
            className="brush-size-slider"
            min="0"
            max="64"
            value={replaceTolerance}
            onChange={(e) => setReplaceTolerance(parseInt(e.target.value))}
            title="How close a color has to be to count as the same color (0 = exact)"
          />
          <span className="brush-size-value">{replaceTolerance}</span>
        </>
      ) : (
        <>
          <span className="toolbar-label">Size:</span>
          <input
            type="range"
            className="brush-size-slider"
            min="1"
            max="20"
            value={brushSize}
            onChange={(e) => setBrushSize(parseInt(e.target.value))}
            title="Brush Size"
          />
          <span className="brush-size-value">{brushSize}</span>
        </>
      )}

      {selection && (
        <>
          <div className="toolbar-separator"></div>
          <span className="toolbar-label toolbar-selection-size">
            {selection.w} × {selection.h}
          </span>
          <button className="toolbar-btn" onClick={clearSelection}
            title="Clear the selection — paint the whole texture again (Ctrl+D)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="1" strokeDasharray="4 3"/>
              <path d="m9 9 6 6M15 9l-6 6"/>
            </svg>
          </button>
        </>
      )}
    </div>
  )
}
