import HexagonLoader from '../../shared/ui/HexagonLoader'

// Working rows speak the typing bubble's cadence rather than carrying their own
// spinner: one pulse in the thread instead of two languages disagreeing. The
// 22px hexagon was animated but too small to read as activity.
export function DownloadActivity({ preparing = false, label = preparing ? 'Preparing download' : 'Downloading' }) {
  return <div className="assistant-download-activity" role="status">
    <span>{label}</span>
    <span className="assistant-work-pulse" aria-hidden="true"><i /></span>
  </div>
}

export default function DownloadProgress({ tool }) {
  const result = tool.result || {}
  const total = Math.max(0, result.total_count || 0)
  const completed = Math.min(total, Math.max(0, result.completed_count || 0))
  const failed = result.downloads?.filter(item => item.status === 'error').length || 0
  const active = tool.status === 'running' && !result.cancelled && completed < total
  const stopped = result.cancelled || ['cancelled', 'interrupted', 'error'].includes(tool.status)
  const label = stopped ? 'Downloads stopped' : active ? 'Downloading to vault' : 'Downloads finished'
  return <div className={`assistant-download-progress ${active ? 'is-active' : ''}`}>
    {active && <HexagonLoader size={44} label="Downloads processed"
      progress={completed > 0 ? completed / total * 100 : null}
      centerLabel={`${completed}/${total}`} />}
    <div role="status">
      <span>{label}</span>
      <small>{completed} of {total} processed{failed > 0 ? ` · ${failed} failed` : ''}</small>
    </div>
  </div>
}
