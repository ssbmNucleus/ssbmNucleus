/** The once-per-job notice, before the component presents it and acknowledges it. */
export function interruptedNotice(jobs, shown) {
  const fresh = jobs.filter(job => job.status === 'interrupted' && !job.seen && !shown.has(job.id))
  if (fresh.length === 0) return null
  return {
    ids: fresh.map(job => job.id),
    message: fresh.map(job => {
      const notes = (job.notes || []).join(' ')
      return `${job.label || 'A task'} was stopped when Nucleus closed.${notes ? ` ${notes}` : ''}`
    }).join('\n\n'),
  }
}
