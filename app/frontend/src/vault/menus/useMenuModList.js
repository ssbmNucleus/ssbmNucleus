/**
 * useMenuModList - list state + the card actions shared by every menu kind.
 *
 * Fetches the kind's list, and exposes rename / replace-image / export /
 * delete / patch, each hitting the endpoints named in the kind's registry
 * entry (menuKinds.js). `refreshKey` is bumped by the vault when the floating
 * Import button lands a menu mod, so a fresh card shows up without a manual
 * reload.
 *
 * Lists are cached per kind for the life of the page, so switching kinds (or
 * leaving and returning to Menus) renders the last known cards at once and
 * refreshes quietly behind them. Skeletons only appear the very first time a
 * kind is opened.
 */
import { useCallback, useEffect, useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm } from '../../shared/ui/appDialogs'
import { api } from '../../shared/transport/api'
import { backendMediaUrl } from '../../shared/config/config'

const listCache = new Map()   // kind.key -> mods[]

export default function useMenuModList(kind, refreshKey = 0, { onChanged } = {}) {
  const [mods, setMods] = useState(() => listCache.get(kind.key) || [])
  const [loading, setLoading] = useState(() => !listCache.has(kind.key))
  const [cacheBust, setCacheBust] = useState(0)

  const refresh = useCallback(async () => {
    try {
      const data = await api.get(kind.list)
      const next = data.mods || []
      listCache.set(kind.key, next)
      setMods(next)
    } catch (err) {
      console.error(`[menus] failed to list ${kind.key}:`, err)
    } finally {
      setLoading(false)
    }
  }, [kind])

  useEffect(() => {
    // Quiet refresh when we already have cards to show; skeleton otherwise.
    if (!listCache.has(kind.key)) setLoading(true)
    refresh()
  }, [refresh, refreshKey, kind.key])

  const bumpCache = () => setCacheBust(Date.now())

  const setModsCached = (updater) => {
    setMods((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      listCache.set(kind.key, next)
      return next
    })
  }

  const rename = async (mod, name) => {
    const trimmed = (name || '').trim()
    if (!trimmed || trimmed === mod.name) return
    await api.post(kind.rename(mod.id), { name: trimmed })
    playSound('boop')
    setModsCached((prev) => prev.map((m) => (m.id === mod.id ? { ...m, name: trimmed } : m)))
  }

  // Generic field update on the rename endpoint (backgrounds' scene toggle).
  const patch = async (mod, body) => {
    await api.post(kind.rename(mod.id), body)
    playSound('boop')
    setModsCached((prev) => prev.map((m) => (m.id === mod.id ? { ...m, ...body } : m)))
  }

  const replaceImage = async (mod, file) => {
    if (!file) return
    const fd = new FormData()
    fd.append('screenshot', file)
    await api.post(kind.screenshot(mod.id), fd)
    playSound('boop')
    bumpCache()
    await refresh()
  }

  const exportMod = (mod) => {
    const a = document.createElement('a')
    // an <a download> cannot send the token header -- put it in the query
    a.href = backendMediaUrl(kind.exportUrl(mod.id))
    a.download = ''
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  const remove = async (mod) => {
    const ok = await appConfirm(`Delete "${mod.name}"? This removes its files from your vault.`, {
      title: `Delete ${kind.singular}`,
      confirmText: 'Delete',
    })
    if (!ok) return false
    await api.post(kind.remove(mod.id))
    playSound('boop')
    // Drop the card immediately; the refresh confirms.
    setModsCached((prev) => prev.filter((m) => m.id !== mod.id))
    await refresh()
    onChanged?.()
    return true
  }

  return { mods, setMods: setModsCached, loading, cacheBust, bumpCache, refresh, rename, patch, replaceImage, exportMod, remove }
}
