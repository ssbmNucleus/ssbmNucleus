/** Background scans leave expanded replay months alone unless their contents changed. */
export function replayScanNeedsRefresh(job, startedId) {
  const result = job.result || {}
  return Boolean(job.id === startedId || result.added || result.updated || result.removed)
}

/** A manual combo pass or one that analyzed games reloads the first page. */
export function comboScanNeedsRefresh(job, startedId) {
  return Boolean(job.id === startedId || job.result?.total)
}
