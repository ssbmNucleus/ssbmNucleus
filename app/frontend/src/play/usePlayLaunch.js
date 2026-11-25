/**
 * usePlayLaunch - starting games and following the play_launch job (play/launch.py).
 *
 *   const { active, lastByEntry, errors, launch, openGameSettings } = usePlayLaunch(onEnded)
 *
 * active        the running play_launch job (one at a time), or null
 * lastByEntry   each entry's newest ended play_launch job while Play has been open
 * errors        each entry's refused start (a 400 saying what to set up), cleared on the next try
 * setError      (entryId, message|null): show another refusal on a card (the entry menu's)
 */
import { useCallback, useState } from 'react'
import { api } from '../shared/transport/api'
import { useActiveJob, useJobEnd } from '../shared/jobs/useJobs'
import { playSound } from '../shared/audio/sounds'
import { readSlippiPath } from './usePlayShelf'

export const LAUNCH_KIND = 'play_launch'
export const SETTINGS_KEY = '__settings__'

export function usePlayLaunch(onEnded) {
  const active = useActiveJob(LAUNCH_KIND)
  const [lastByEntry, setLastByEntry] = useState({})
  const [errors, setErrors] = useState({})

  useJobEnd(LAUNCH_KIND, (job) => {
    const key = job.params?.entryId || SETTINGS_KEY
    setLastByEntry((current) => ({ ...current, [key]: job }))
    if (onEnded) onEnded(job)
  })

  const setError = (key, message) => setErrors((current) => ({ ...current, [key]: message }))

  const launch = useCallback(async (entry, target) => {
    setError(entry.id, null)
    try {
      await api.post(`/api/play/launch/${encodeURIComponent(entry.id)}`, { target, slippiPath: readSlippiPath() })
      playSound('start')
    } catch (err) {
      playSound('back')
      setError(entry.id, err.message || 'The game could not start.')
    }
  }, [])

  const openGameSettings = useCallback(async () => {
    setError(SETTINGS_KEY, null)
    try {
      await api.post('/api/play/settings-window', {})
      playSound('boop')
    } catch (err) {
      playSound('back')
      setError(SETTINGS_KEY, err.message || 'The settings window could not open.')
    }
  }, [])

  const clearErrors = useCallback(() => setErrors({}), [])

  return { active, lastByEntry, errors, launch, openGameSettings, clearErrors, setError }
}
