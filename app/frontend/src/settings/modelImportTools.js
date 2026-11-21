/**
 * modelImportTools.js - the model import's tools (Blender, Python and the packages rigswap runs on), a download the
 * user starts from Settings or from Randall's import card. Pure helpers: the backend's status (GET
 * /api/assistant/model-import-tools, backend randall/model_import/tools) and the live download job (kind
 * `model_import_tools`, core/jobs.py) read into what a card shows. The hook is useModelImportTools.js; the cards are
 * ModelImportToolsSection.jsx (Settings) and randall/assistant/ImportToolsDownload.jsx (the import card).
 */

export const KIND = 'model_import_tools'
export const TOOLS_URL = '/api/assistant/model-import-tools'

const ACTIVE = new Set(['queued', 'running'])
const MB = 1000 * 1000
const GB = 1000 * MB

/** "750 MB", "1.6 GB", "under 1 MB"; null when there is no size. Decimal units, as download sizes are given. */
export function sizeText(bytes) {
  const value = Number(bytes)
  if (!Number.isFinite(value) || value <= 0) return null
  if (value < MB) return 'under 1 MB'
  if (value < GB) return `${Math.round(value / MB)} MB`
  return `${(value / GB).toFixed(1).replace(/\.0$/, '')} GB`
}

/** How much of a download is in: "168 of 779 MB" (one unit when both are in MB), else "168 MB of 1.1 GB"; null
 * without a total. */
export function partText(done, total) {
  const have = Math.max(0, Number(done) || 0)
  const all = Number(total)
  if (!Number.isFinite(all) || all <= 0) return null
  if (all < GB && have >= MB) return `${Math.round(have / MB)} of ${Math.round(all / MB)} MB`
  return `${sizeText(have) || '0 MB'} of ${sizeText(all)}`
}

/** A job record's progress as a whole percent, or null when it gave none. */
export function jobPercent(job) {
  const fraction = Number(job?.progress)
  if (job?.progress === null || job?.progress === undefined || !Number.isFinite(fraction)) return null
  return Math.max(0, Math.min(100, Math.round(fraction * 100)))
}

export const isActiveJob = job => Boolean(job && ACTIVE.has(job.status))

const STATE_TEXT = {
  loading: 'Checking…',
  not_installed: 'Not installed',
  installed: 'Installed',
  update_needed: 'Update needed',
  downloading: 'Downloading',
  // A download that was cancelled (or stopped when the app closed) with part of it kept: Resume carries on from it.
  paused: 'Paused',
  failed: 'The download failed',
  unsupported: 'Not available on this computer',
}

const pieces = tools => (Array.isArray(tools?.pieces) ? tools.pieces : []).filter(piece => piece && typeof piece === 'object')

/** "Blender 4.3.2 from download.blender.org" for each piece the tools are made of. A source may carry its own
 * parentheses ("PyPI (files.pythonhosted.org)"), so it is never wrapped in more. */
export function sourceLines(tools) {
  return pieces(tools).map(piece => {
    const label = typeof piece.label === 'string' && piece.label.trim() ? piece.label.trim() : String(piece.name || '')
    const source = typeof piece.source === 'string' && piece.source.trim() ? piece.source.trim() : ''
    return source ? `${label} from ${source}` : label
  }).filter(Boolean)
}

/**
 * What the Settings card shows: the backend's status (`tools`, null while it loads) and the live download job from
 * the job store (`job`, the newest queued/running one, null when none). The live job wins over the status, which may
 * be older. `requestError` is a request of the card's own that failed (a start that was refused).
 */
export function toolsView(tools, job = null, requestError = null) {
  const live = isActiveJob(job) ? job : isActiveJob(tools?.job) ? tools.job : null
  let state = tools ? String(tools.state || 'not_installed') : 'loading'
  if (live) state = 'downloading'
  if (tools && tools.supported === false) state = 'unsupported'
  if (!STATE_TEXT[state]) state = 'not_installed'
  // paused: part of what is left to download is on disk (`downloaded_bytes`); `needed_bytes` is the rest.
  const downloaded = Math.max(0, Number(tools?.downloaded_bytes) || 0)
  if (state === 'paused' && !downloaded) state = 'not_installed'
  const anyInstalled = pieces(tools).some(piece => piece.installed)
  const needed = sizeText(tools?.needed_bytes) || sizeText(tools?.download_bytes)
  const total = sizeText(tools?.download_bytes)
  const wanted = downloaded + Math.max(0, Number(tools?.needed_bytes) || 0)
  const disk = sizeText(tools?.disk_bytes)
  const estimated = state !== 'installed' || Boolean(tools?.disk_estimated)
  const error = state === 'failed' ? (typeof tools?.error === 'string' && tools.error.trim()) || 'It stopped before it finished.' : null
  const downloadText = !total ? null
    : state === 'paused' ? `Download: about ${needed} left of ${sizeText(wanted)}`
      : state === 'update_needed' && needed !== total ? `Download: about ${needed} of ${total}`
        : `Download: about ${total}`
  return {
    state,
    stateText: state === 'paused' ? `Paused · ${partText(downloaded, wanted)}` : STATE_TEXT[state],
    downloadText,
    diskText: disk ? `On disk: ${estimated ? 'about ' : ''}${disk}` : null,
    sources: sourceLines(tools),
    percent: live ? jobPercent(live) : null,
    detail: live && typeof live.detail === 'string' && live.detail.trim() ? live.detail.trim() : null,
    jobId: live?.id || null,
    error,
    requestError: requestError ? String(requestError) : null,
    path: state === 'installed' || state === 'update_needed' ? (tools?.path || null) : null,
    actions: {
      download: state === 'not_installed' || state === 'failed' || state === 'paused',
      update: state === 'update_needed',
      cancel: state === 'downloading',
      remove: (state === 'installed' || state === 'update_needed'
        || ((state === 'failed' || state === 'paused') && anyInstalled)),
    },
    downloadLabel: state === 'failed' ? 'Try again' : state === 'paused' ? (needed ? `Resume (${needed})` : 'Resume')
      : needed ? `Download (${needed})` : 'Download',
    updateLabel: needed ? `Update (${needed})` : 'Update',
  }
}

/** What an import_model reply that needs the tools carries (backend import_job: status `needs_tools`, `tools`). */
export function importToolsNeed(result) {
  const r = result && typeof result === 'object' ? result : {}
  if (r.status !== 'needs_tools') return null
  const tools = r.tools && typeof r.tools === 'object' ? r.tools : {}
  return {
    state: tools.state === 'update_needed' ? 'update_needed' : 'not_installed',
    neededBytes: Number(tools.needed_bytes) || Number(tools.download_bytes) || 0,
    downloadBytes: Number(tools.download_bytes) || 0,
    diskBytes: Number(tools.disk_bytes) || 0,
  }
}

/**
 * What the import card's download box shows for a reply that needs the tools (`need`, `importToolsNeed`): the live
 * status when it is known (`tools`, `job`), else the reply's own. Once the tools are installed it says the import can
 * be asked for again.
 */
export function chatToolsView(need, tools = null, job = null, requestError = null) {
  const view = toolsView(tools, job, requestError)
  const size = sizeText(tools ? (tools.needed_bytes || tools.download_bytes) : need?.neededBytes || need?.downloadBytes)
  const fallback = need?.state === 'update_needed' ? 'update_needed' : 'not_installed'
  const state = view.state === 'loading' ? fallback : view.state
  const label = state === 'update_needed' ? 'Update the tools' : state === 'failed' ? 'Try the download again'
    : state === 'paused' ? 'Resume the download' : 'Download the tools'
  return {
    state,
    // paused: how much is already in ("Paused · 168 of 779 MB"), as on the Settings card.
    statusText: state === 'paused' ? view.stateText : null,
    percent: view.percent,
    detail: view.detail,
    error: view.error,
    requestError: view.requestError,
    canStart: state === 'not_installed' || state === 'update_needed' || state === 'failed' || state === 'paused',
    canCancel: state === 'downloading',
    startLabel: size ? `${label} (about ${size})` : label,
    note: state === 'installed' ? 'The tools are installed. Ask Randall to import it again.'
      : state === 'unsupported' ? 'Model import is not available on this computer.'
        : state === 'downloading' ? null
          : 'A one-time download. You can also manage it in Settings, under AI.',
  }
}
