import { SCAN_CATEGORIES } from './isoScanResultModel.js'

export function elapsedTime(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

// A phase that says nothing for this long gets a line about it -- long enough
// that a slow-but-working step is not accused of stalling.
const QUIET_NOTICE_MS = 45000

export function scanProgressView(progress = {}, 
  { importing = false, count = 0, cancelling = false, quietFor = 0 } = {}) {
  const status = importing ? 'importing' : progress.status
  // Old backends only expose a diagnostic message; keep their useful counts,
  // without showing renderer worker counts or repeating the phase heading.
  const legacy = String(progress.message || '').match(/(\d+)\/(\d+)/)
  const current = progress.current ?? (legacy ? Number(legacy[1]) : null)
  const total = progress.total ?? (legacy ? Number(legacy[2]) : null)
  const hasCount = Number.isFinite(current) && Number.isFinite(total) && total > 0
  const pair = hasCount ? `${Math.min(current, total)} of ${total}` : ''
  const reconnecting = /reconnecting/i.test(progress.message || '')
  const emptyPreviews = status === 'csp' && total === 0
  const customCategories = SCAN_CATEGORIES.filter(category =>
    Array.isArray(progress.categories) ? progress.categories.includes(category.key) :
      (category.key === 'das' && /(?:DAS|stage) variants/i.test(progress.message || '')))
  const customTitle = customCategories.length > 1
    ? customCategories.map(category => category.label).join(' & ')
    : customCategories.length === 1 ? `Importing ${customCategories[0].label.toLowerCase()}` : 'Importing custom content'
  const titles = { pending: 'Preparing scan', custom: customTitle,
    extracting: 'Reading ISO', scanning: 'Checking character skins', slippi: 'Checking Slippi safety',
    csp: current === 0 ? 'Preparing previews' : 'Creating previews', importing: 'Adding to your vault' }
  let title = reconnecting ? 'Reconnecting' : emptyPreviews ? 'Finishing scan' : titles[status] || 'Scanning'
  let detail = emptyPreviews ? '' : ({
    extracting: hasCount && total > 1 ? `ISO ${pair}` : '',
    scanning: pair ? `${pair} files` : '',
    slippi: pair ? `${pair} character skins` : '',
    csp: pair ? `${pair} previews` : '',
    custom: hasCount && total > 1 ? `Import ${pair}` : '',
    importing: `${count} character skin${count === 1 ? '' : 's'}`,
  }[status] || '')
  const percent = !reconnecting && !emptyPreviews && ['extracting', 'scanning', 'slippi', 'csp'].includes(status)
    && Number.isFinite(progress.percent) ? Math.round(Math.min(100, Math.max(0, progress.percent))) : null
  // The custom-content pass builds a temporary m-ex project per ISO and
  // reports nothing while it runs -- minutes, by design. Warning that no
  // progress has arrived reads as a crash there, so it keeps whatever count it
  // has, or is told to hold on. Phases that normally tick still get the warning.
  if (!cancelling && !importing && quietFor >= QUIET_NOTICE_MS) {
    detail = status === 'custom'
      ? (detail || 'Still working — this can take a few minutes')
      : `No new progress for ${elapsedTime(quietFor)}`
  }
  if (cancelling) {
    title = status === 'custom' ? 'Finishing current import' : 'Stopping scan'
    detail = ''
  }
  return { title, detail, percent: cancelling ? null : percent }
}
