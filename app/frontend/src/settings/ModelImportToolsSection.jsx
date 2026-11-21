/**
 * ModelImportToolsSection - "Model import tools": the Blender, Python and packages that importing a 3D model as a
 * costume runs on (Randall's chat, and the app MCP's import_model). Since 0.9.0 they are not in the installer: the
 * user downloads them here (or from Randall's import card), from the official sources, each file checked against its
 * pinned checksum. Shown in builds with the assistant (Settings.jsx), to everyone. The view is props-driven
 * (`ModelImportToolsView`); the data is useModelImportTools.js, the words modelImportTools.js.
 */
import { useState } from 'react'
import { playHoverSound, playSound } from '../shared/audio/sounds'
import { toolsView } from './modelImportTools'
import { useModelImportTools } from './useModelImportTools'

// The facts as chips (modelImportTools.js toolsView's words, shorter): "Download: about 779 MB" is "779 MB download",
// "Download: about 611 MB left of 779 MB" is "611 MB left of 779 MB", "Download: about 380 MB of 791 MB" (an update)
// is "380 MB to download", "On disk: about 1.6 GB" is "1.6 GB on disk".
export const chip = text => text
  .replace(/^Download: (?:about )?(.+ left of .+)$/, '$1')
  .replace(/^Download: (?:about )?(.+?) of .+$/, '$1 to download')
  .replace(/^Download: (?:about )?(.+)$/, '$1 download')
  .replace(/^On disk: (?:about )?(.+)$/, '$1 on disk')

export function ModelImportToolsView({ view, busy = false, confirming = false, onDownload, onCancel, onRemove,
  onConfirmRemove, onKeep }) {
  const facts = [view.downloadText, view.diskText].filter(Boolean)
  const { actions } = view
  return (
    <section className="settings-section model-tools-section">
      <div className="model-tools-head">
        <h3>Model import tools</h3>
        <p className={`model-tools-state is-${view.state}`} role="status">{view.stateText}
          {view.state === 'downloading' && view.percent !== null ? ` · ${view.percent}%` : ''}</p>
      </div>
      <p className="ai-card-lede">Blender and Python, for importing 3D models as costumes from Randall&apos;s chat or
        with import_model from your own AI.</p>
      {facts.length > 0 && view.state !== 'installed' && <div className="ai-chips">
        {facts.map(fact => <span key={fact} className="ai-chip">{chip(fact)}</span>)}
      </div>}
      {view.state === 'downloading' && <>
        <div className="update-progress-track model-tools-progress" aria-hidden="true">
          <div className="update-progress-fill" style={{ width: `${view.percent ?? 0}%` }} />
        </div>
        {view.detail && <p className="ai-card-hint">{view.detail}</p>}
      </>}
      {view.state === 'paused' && <p className="ai-card-hint">Stopped. What came down is kept, and Resume
        carries on from there.</p>}
      {view.state === 'update_needed' && <p className="ai-card-hint">This version of Nucleus needs newer tools.</p>}
      {view.error && <p className="update-status-error">{view.error}</p>}
      {view.requestError && <p className="update-status-error">{view.requestError}</p>}
      {confirming ? <div className="model-tools-actions">
        <span className="model-tools-confirm">Remove the tools? You can download them again.</span>
        <button type="button" className="btn-cancel" onClick={onKeep}>Keep</button>
        <button type="button" className="btn-confirm" disabled={busy} onClick={onConfirmRemove}>Remove</button>
      </div> : <div className="model-tools-actions">
        {actions.download && <button type="button" className="restore-button model-tools-go" disabled={busy}
          onMouseEnter={playHoverSound} onClick={onDownload}>{view.downloadLabel}</button>}
        {actions.update && <button type="button" className="restore-button model-tools-go" disabled={busy}
          onMouseEnter={playHoverSound} onClick={onDownload}>{view.updateLabel}</button>}
        {actions.cancel && <button type="button" className="btn-cancel" disabled={busy} onClick={onCancel}>Cancel</button>}
        {actions.remove && <button type="button" className="ai-quiet-button" disabled={busy} onClick={onRemove}>Remove</button>}
      </div>}
      {/* "Blender 4.3.2 from download.blender.org; …": semicolons, as a piece's label has commas of its own. */}
      {(view.sources.length > 0 || view.path) && <details className="ai-more">
        <summary>Details</summary>
        {view.state === 'installed' && view.diskText && <p>{view.diskText}</p>}
        {view.sources.length > 0 && <p>
          {view.sources.join('; ')}. Each file is checked against its pinned checksum before it is unpacked.
        </p>}
        {view.path && <p className="ai-more-path">In {view.path}</p>}
      </details>}
    </section>
  )
}

export default function ModelImportToolsSection() {
  const { tools, job, busy, requestError, start, cancel, remove } = useModelImportTools()
  const [confirming, setConfirming] = useState(false)
  const view = toolsView(tools, job, requestError)
  return <ModelImportToolsView view={view} busy={busy} confirming={confirming && view.actions.remove}
    onDownload={() => { playSound('start'); start() }}
    onCancel={() => cancel()}
    onRemove={() => setConfirming(true)}
    onKeep={() => setConfirming(false)}
    onConfirmRemove={() => { setConfirming(false); remove() }} />
}
