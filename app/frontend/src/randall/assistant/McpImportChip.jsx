/**
 * McpImportChip - while the user's own AI imports a model over MCP (import_model / fix_import, job kind
 * `mcp_model_import`), a small chip in the app header: "Your AI · Neos as Marth · putting it on the fighter · Cancel"
 * (a change: "Your AI · changing Neos on Marth · ..."). Cancel stops the import (nothing is saved); the chip then says
 * it stopped and goes. It sits in the header, between the wordmark and the tabs, so it never covers a page, the
 * Dolphin embed or a 3D viewer's controls, and it takes only the room they leave: its words shorten (the step first,
 * then the model's name, then the fighter), Cancel always shows, and the whole of it is in its tooltip. A Cancel that failed says so
 * where the step was. The view is props-driven (`McpImportChipView`); the state is mcpImport.js.
 */
import { playHoverSound, playSound } from '../../shared/audio/sounds'
import { useMcpImportChip } from './mcpImport'

export function McpImportChipView({ view, onCancel }) {
  if (!view) return null
  if (view.state === 'stopped') {
    return (
      <div className="mcp-import-chip is-stopped" role="status" aria-live="polite" title={view.title}>
        <span className="mcp-import-chip-note">{view.text}</span>
      </div>
    )
  }
  return (
    <div className={`mcp-import-chip is-${view.state}`} role="status" aria-live="polite" title={view.title}>
      <span className="mcp-import-chip-words">
        <span className="mcp-import-chip-lead">Your AI</span>
        <span className="mcp-import-chip-what">
          <span className="mcp-import-chip-model">{view.change ? `changing ${view.model}` : view.model}</span>
          {view.fighter && (
            <span className="mcp-import-chip-fighter">{`${view.change ? 'on' : 'as'} ${view.fighter}`}</span>
          )}
          {view.error
            ? <span className="mcp-import-chip-error">{view.error}</span>
            : view.step && <span className="mcp-import-chip-step">{view.step}</span>}
        </span>
      </span>
      <button type="button" className="mcp-import-chip-cancel" disabled={!view.canCancel}
        onMouseEnter={playHoverSound} onClick={onCancel}>Cancel</button>
    </div>
  )
}

export default function McpImportChip() {
  const { view, cancel } = useMcpImportChip()
  return <McpImportChipView view={view} onCancel={() => { playSound('back'); cancel() }} />
}
