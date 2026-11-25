/**
 * usePlayClient - the Nucleus game client Play installs and keeps up to date (play/managed.py,
 * /api/play/client/managed/*).
 *
 *   const client = usePlayClient(visible, onChanged)
 *
 * job       the running install or update job as the job store has it (live progress), or null
 * install() / update() / cancel()   start or stop it; the backend runs it as a job (play_client_install)
 * check(force)   ask the signed client feed whether there is a newer client (at most every half hour
 *                unless forced); done once each time the page shows
 * checking  a check is under way
 * error     a refused request in plain words (another install running, no internet), cleared on the next try
 *
 * onChanged is called whenever what the shelf answer says about the client may have changed (it reloads
 * the shelf, which carries the client's status as `managed`).
 */
import { useCallback, useEffect, useState } from 'react'
import { api } from '../shared/transport/api'
import { useActiveJob, useJobEnd } from '../shared/jobs/useJobs'
import { playSound } from '../shared/audio/sounds'
import { INSTALL_KIND } from './playCards'

const BASE = '/api/play/client/managed'

export function usePlayClient(visible, onChanged) {
  const job = useActiveJob(INSTALL_KIND)
  const [error, setError] = useState(null)
  const [checking, setChecking] = useState(false)

  useJobEnd(INSTALL_KIND, (ended) => {
    if (ended.status === 'done') playSound('boop')
    onChanged?.()
  })

  const check = useCallback(async (force = false) => {
    setChecking(true)
    try {
      await api.post(`${BASE}/check`, { force })
    } catch (err) {
      if (err.status !== 404) setError(err.message || 'Nucleus could not check for a newer client.')
    } finally {
      setChecking(false)
      onChanged?.()
    }
  }, [onChanged])

  useEffect(() => { if (visible) check(false) }, [visible, check])

  const start = useCallback(async (action) => {
    setError(null)
    try {
      await api.post(`${BASE}/${action}`, {})
      playSound('start')
    } catch (err) {
      playSound('back')
      setError(err.message || 'Nucleus Unlocked could not be installed.')
    } finally {
      onChanged?.()
    }
  }, [onChanged])

  const cancel = useCallback(async () => {
    try {
      await api.post(`${BASE}/cancel`, {})
      playSound('back')
    } catch (err) {
      setError(err.message || 'The install could not be stopped.')
    }
  }, [])

  return {
    job, error, checking, check,
    install: () => start('install'),
    update: () => start('update'),
    cancel,
  }
}
