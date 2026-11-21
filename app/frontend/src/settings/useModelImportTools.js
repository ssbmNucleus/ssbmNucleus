/**
 * useModelImportTools.js - the model import's tools as a card reads them: the backend's status (GET
 * /api/assistant/model-import-tools), the live download job from the window's job store (kind `model_import_tools`)
 * and the three requests (start, cancel, remove). The Settings card (ModelImportToolsSection.jsx) and Randall's
 * import card (randall/assistant/ImportToolsDownload.jsx) both use it, so a download started in one shows in the
 * other. modelImportTools.js turns what it returns into what a card shows.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../shared/transport/api'
import { refreshJob, useActiveJob, useJobEnd } from '../shared/jobs/useJobs'
import { KIND, TOOLS_URL } from './modelImportTools'

const POLL_MS = 3000   // only while the status says downloading and the job store has no record of it yet

export function useModelImportTools() {
  const [tools, setTools] = useState(null)
  const [busy, setBusy] = useState(false)
  const [requestError, setRequestError] = useState(null)
  const job = useActiveJob(KIND)
  const live = useRef(true)

  const refresh = useCallback(async () => {
    try {
      const data = await api.get(TOOLS_URL)
      if (live.current) setTools(data?.tools || null)
    } catch (err) {
      if (live.current) setRequestError(err?.message || 'Could not read the tools\' status.')
    }
  }, [])

  useEffect(() => {
    live.current = true
    refresh()
    return () => { live.current = false }
  }, [refresh])

  // A download that ends (done, failed, cancelled) changes what is installed: read the status again.
  useJobEnd(KIND, () => { refresh() })

  // The status says a download runs that the job store does not show (its socket is not up yet): look again shortly.
  useEffect(() => {
    if (tools?.state !== 'downloading' || job) return undefined
    const timer = setTimeout(refresh, POLL_MS)
    return () => clearTimeout(timer)
  }, [tools, job, refresh])

  const request = useCallback(async (path, after) => {
    setBusy(true)
    setRequestError(null)
    try {
      const data = await api.post(`${TOOLS_URL}/${path}`)
      if (after) after(data)
      return data
    } catch (err) {
      if (live.current) setRequestError(err?.message || 'That did not work.')
      // 409: a download already runs (another card started it): show that one.
      if (err?.status === 409 && err?.data?.job_id) refreshJob(err.data.job_id).catch(() => {})
      return null
    } finally {
      if (live.current) setBusy(false)
      refresh()
    }
  }, [refresh])

  const start = useCallback(() => request('start', data => {
    if (data?.job_id) refreshJob(data.job_id).catch(() => {})
  }), [request])
  const cancel = useCallback(() => request('cancel'), [request])
  const remove = useCallback(() => request('remove', data => {
    if (data?.tools && live.current) setTools(data.tools)
  }), [request])

  return { tools, job, busy, requestError, start, cancel, remove, refresh }
}
