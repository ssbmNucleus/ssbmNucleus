/**
 * LayersPanel — the layer stack for the texture being painted.
 *
 * Listed topmost-first, the way every editor shows a stack (the array itself is
 * bottom-up, which is the order it composites in). Layers are a paint-session
 * construct: the game only ever receives the flattened texture, so the stack
 * lives until you close the editor and is flattened into the DAT on save.
 */
import { BLEND_MODES } from './useLayers'

const Icon = {
  add: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>,
  duplicate: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>,
  remove: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>,
  up: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="18 15 12 9 6 15" /></svg>,
  down: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="6 9 12 15 18 9" /></svg>,
  merge: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="8 12 12 16 16 12" /><line x1="12" y1="4" x2="12" y2="16" /><line x1="4" y1="20" x2="20" y2="20" /></svg>,
  eye: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>,
  eyeOff: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
    <line x1="1" y1="1" x2="23" y2="23" /></svg>
}

export default function LayersPanel({
  layers, activeId, disabled,
  onSelect, onAdd, onDuplicate, onDelete, onMove, onMergeDown,
  onSetProp,      // discrete change: one undo step, pushes to the 3D viewer
  onBeginEdit,    // a slider/typing session is starting: take ONE undo step now
  onLiveProp,     // mid-drag: reflatten the canvas, don't re-encode for the viewer
  onEndEdit       // let go: publish the result once
}) {
  const active = layers.find(layer => layer.id === activeId) || null
  const topDown = [...layers].reverse()
  const index = layers.findIndex(layer => layer.id === activeId)
  const canGoUp = index >= 0 && index < layers.length - 1
  const canGoDown = index > 0

  if (!layers.length) {
    return <div className="layers-panel layers-panel--empty">Select a texture to paint on layers.</div>
  }

  return (
    <div className="layers-panel" inert={disabled || undefined}>
      <div className="layers-actions">
        <button className="toolbar-btn" onClick={onAdd} title="Add an empty layer above this one">{Icon.add}</button>
        <button className="toolbar-btn" onClick={() => onDuplicate(activeId)} title="Duplicate this layer">{Icon.duplicate}</button>
        <button className="toolbar-btn" onClick={() => onMove(activeId, 1)} disabled={!canGoUp}
          title="Move this layer up">{Icon.up}</button>
        <button className="toolbar-btn" onClick={() => onMove(activeId, -1)} disabled={!canGoDown}
          title="Move this layer down">{Icon.down}</button>
        <button className="toolbar-btn" onClick={() => onMergeDown(activeId)} disabled={!canGoDown}
          title="Merge this layer into the one below it">{Icon.merge}</button>
        <button className="toolbar-btn toolbar-btn--danger" onClick={() => onDelete(activeId)}
          disabled={layers.length <= 1} title="Delete this layer">{Icon.remove}</button>
      </div>

      <ul className="layers-list">
        {topDown.map(layer => (
          <li key={layer.id}
            className={`layers-row${layer.id === activeId ? ' layers-row--active' : ''}${layer.visible ? '' : ' layers-row--hidden'}`}
            onClick={() => onSelect(layer.id)}>
            <button className="layers-eye"
              onClick={(e) => { e.stopPropagation(); onSetProp(layer.id, { visible: !layer.visible }) }}
              title={layer.visible ? 'Hide this layer' : 'Show this layer'}>
              {layer.visible ? Icon.eye : Icon.eyeOff}
            </button>
            <input className="layers-name" value={layer.name}
              onClick={(e) => e.stopPropagation()}
              onFocus={onBeginEdit}
              onChange={(e) => onLiveProp(layer.id, { name: e.target.value })}
              title="Rename this layer" />
            {layer.blend !== 'source-over' && (
              <span className="layers-badge" title="Blend mode">
                {BLEND_MODES.find(mode => mode.id === layer.blend)?.name}
              </span>
            )}
            {layer.opacity < 1 && <span className="layers-badge">{Math.round(layer.opacity * 100)}%</span>}
          </li>
        ))}
      </ul>

      {active && (
        <div className="layers-properties">
          <label className="layers-field">
            <span>Blend</span>
            <select value={active.blend} onChange={(e) => onSetProp(active.id, { blend: e.target.value })}>
              {BLEND_MODES.map(mode => <option key={mode.id} value={mode.id}>{mode.name}</option>)}
            </select>
          </label>
          <label className="layers-field">
            <span>Opacity</span>
            <input type="range" min="0" max="100" value={Math.round(active.opacity * 100)}
              onPointerDown={onBeginEdit}
              onChange={(e) => onLiveProp(active.id, { opacity: Number(e.target.value) / 100 })}
              onPointerUp={onEndEdit} onBlur={onEndEdit} />
            <span className="layers-value">{Math.round(active.opacity * 100)}</span>
          </label>
        </div>
      )}
      <p className="layers-note">Layers last for this editing session — the saved costume gets the flattened texture.</p>
    </div>
  )
}
