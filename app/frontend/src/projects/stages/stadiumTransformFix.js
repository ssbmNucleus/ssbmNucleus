/** Convert DAS import transformFix reports into one user-facing notice.
 *
 * Only speaks up when something actually happened to the file. A skin that
 * shipped its own per-transformation art says so with the "4 forms" badge on
 * the card; it does not need a notice, and neither does a clean check. */
export function summarizeTransformFixResults(results) {
  const checked = (results || []).filter(item => item?.transformFix?.status)
  if (checked.length === 0) return null

  const counts = checked.reduce((all, item) => {
    const status = item.transformFix.status
    all[status] = (all[status] || 0) + 1
    return all
  }, {})
  const repaired = counts.repaired || 0
  const clean = counts.clean || 0
  const flagged = counts.flagged || 0
  const errors = (counts.error || 0) + (counts.skipped || 0)
  const actionCount = checked.reduce(
    (total, item) => total + (item.transformFix.actions?.length || 0), 0)

  if (flagged || errors) {
    const names = checked
      .filter(item => ['flagged', 'error', 'skipped'].includes(item.transformFix.status))
      .map(item => item.name)
      .filter(Boolean)
      .join(', ')
    return {
      tone: 'warning',
      title: 'Stadium transformation check needs attention',
      message: `${flagged + errors} import${flagged + errors === 1 ? '' : 's'} could not be safely repaired${names ? `: ${names}` : ''}. The stage was imported; test a transformation before sharing the build.`
    }
  }

  if (repaired) {
    const detail = actionCount > 0
      ? ` ${actionCount} geometry move${actionCount === 1 ? '' : 's'} applied.`
      : ''
    const summary = checked.length === 1
      ? 'This Stadium passed the transformation check and was repaired.'
      : `${checked.length} Stadium imports passed the transformation check; ${repaired} repaired and ${clean} already clean.`
    return {
      tone: 'success',
      title: 'Stadium transformation visibility fixed',
      message: `${summary}${detail}`
    }
  }

  return null   // nothing was wrong and nothing was changed -- stay quiet
}
