/**
 * InterruptedJobsNotice - once per job, tells the user that something was
 * running when Nucleus last closed, and what was put back (core/jobs.py
 * recover_interrupted). A job the user has seen is not shown again.
 */
import { useEffect, useRef } from 'react'
import { appAlert } from '../ui/appDialogs'
import { interruptedNotice } from './interruptedJobs'
import { markJobSeen, useJobList } from './useJobs'

export default function InterruptedJobsNotice() {
  const jobs = useJobList()
  const shown = useRef(new Set())

  useEffect(() => {
    const notice = interruptedNotice(jobs, shown.current)
    if (!notice) return
    for (const id of notice.ids) shown.current.add(id)
    appAlert(notice.message, { title: 'Nucleus closed while this was running' })
      .then(() => Promise.all(notice.ids.map((id) => markJobSeen(id).catch(() => {}))))
  }, [jobs])

  return null
}
