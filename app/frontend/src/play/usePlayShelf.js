/**
 * usePlayShelf - the shelf as the Play page reads it (GET /api/play/shelf), reloaded when
 * the page shows and when a game is added.
 *
 *   const { entries, env, error, reload } = usePlayShelf(visible)
 *
 * env is what every card needs besides its entry: { platform, client, managed, retailIso, slippiPath }
 * (managed: the installed Nucleus game client, play/managed.py status).
 * The Slippi Dolphin folder is the one the rest of Nucleus keeps (Settings, Setup).
 */
import { useCallback, useEffect, useState } from 'react'
import { api } from '../shared/transport/api'
import { useJobEnd } from '../shared/jobs/useJobs'

export const SLIPPI_PATH_KEY = 'slippi_dolphin_path'
export const SHELF_ADD_KIND = 'shelf_add'

export function readSlippiPath() {
  try { return localStorage.getItem(SLIPPI_PATH_KEY) || '' } catch { return '' }
}

export function usePlayShelf(visible = true) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const reload = useCallback(async () => {
    try {
      const answer = await api.get('/api/play/shelf')
      setData(answer)
      setError(null)
      return answer
    } catch (err) {
      setError(err.status === 404 ? 'Unlocked is not available in this build.' : (err.message || 'Unlocked could not load.'))
      return null
    }
  }, [])

  useEffect(() => { if (visible) reload() }, [visible, reload])
  useJobEnd(SHELF_ADD_KIND, () => { reload() })

  const env = {
    platform: data?.platform || { supported: true },
    client: data?.client || { set: false, valid: false },
    managed: data?.managed || null,
    retailIso: data?.retailIso || { set: false },
    gameSettings: data?.gameSettings || null,
    slippiPath: readSlippiPath(),
  }
  return { loaded: !!data, entries: data?.entries || [], env, error, reload }
}
