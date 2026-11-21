// The download box on an import_model card whose reply was `needs_tools`: the tools the import runs on (Blender,
// Python and its packages) are not downloaded yet, or this version of the app needs newer ones. Its button starts the
// same download as Settings > Model import tools, shows its progress, and once the tools are in it says the import
// can be asked for again. The view is props-driven (`ImportToolsDownloadView`); the data is the shared hook.
import { chatToolsView, importToolsNeed } from '../../settings/modelImportTools'
import { useModelImportTools } from '../../settings/useModelImportTools'

export function ImportToolsDownloadView({ view, busy = false, onStart, onCancel }) {
  return <div className={`assistant-studio-tools is-${view.state}`}>
    {view.state === 'downloading' && <>
      <p className="assistant-studio-facts" role="status">Downloading the tools{view.percent !== null ? ` · ${view.percent}%` : ''}</p>
      <div className="assistant-studio-tools-track" aria-hidden="true">
        <div className="assistant-studio-tools-fill" style={{ width: `${view.percent ?? 0}%` }} />
      </div>
      {view.detail && <p className="assistant-studio-hint">{view.detail}</p>}
    </>}
    {view.statusText && <p className="assistant-studio-facts" role="status">{view.statusText}</p>}
    {view.error && <p className="assistant-studio-hint assistant-studio-tools-error">{view.error}</p>}
    {view.requestError && <p className="assistant-studio-hint assistant-studio-tools-error">{view.requestError}</p>}
    {(view.canStart || view.canCancel) && <div className="assistant-studio-tools-actions">
      {view.canStart && <button type="button" className="assistant-studio-tools-button" disabled={busy}
        onClick={onStart}>{view.startLabel}</button>}
      {view.canCancel && <button type="button" className="assistant-studio-tools-cancel" disabled={busy}
        onClick={onCancel}>Cancel</button>}
    </div>}
    {view.note && <p className={view.state === 'installed' ? 'assistant-studio-saved' : 'assistant-studio-hint'}>{view.note}</p>}
  </div>
}

/** `result`: the import_model reply (status `needs_tools`, its `tools`). */
export default function ImportToolsDownload({ result }) {
  const { tools, job, busy, requestError, start, cancel } = useModelImportTools()
  return <ImportToolsDownloadView view={chatToolsView(importToolsNeed(result), tools, job, requestError)} busy={busy}
    onStart={() => start()} onCancel={() => cancel()} />
}
