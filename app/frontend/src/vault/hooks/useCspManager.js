/**
 * useCspManager Hook
 *
 * State + actions for the Portraits ("Manage CSPs") modal: which of a costume's
 * portraits is active, adding an alternate, removing one, replacing the
 * original. Every action hits the backend immediately and then re-reads the
 * skin from metadata, so there is no pending/save state.
 *
 * The vault stores alternates as a FLAT list mixing SD and HD entries paired by
 * `pose_name` (see vault/routes/storage_costumes/csp.py manage_csp). `groupPortraits` folds that
 * into one card per portrait once, here, so the modal only renders.
 */

import { useMemo, useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { API_URL } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'
import { groupPortraits } from './cspPortraits.js'

export function useCspManager({
  onRefresh,
  onUpdateEditingItemAlts,
  onUpdateEditingItemActiveCsp,
  onUpdateEditingItemData,
}) {
  const [showCspManager, setShowCspManager] = useState(false)
  const [cspManagerSkin, setCspManagerSkin] = useState(null) // Current skin being edited
  const [alternativeCsps, setAlternativeCsps] = useState([]) // [{ id, url, poseName, isHd, timestamp }]
  const [lastImageUpdate, setLastImageUpdate] = useState(Date.now()) // For cache-busting images
  const [busy, setBusy] = useState(false) // a request is in flight; the modal disables clicks
  const baseUrl = API_URL.replace('/api/mex', '')

  const mapAlternateCsps = (character, skin) => (
    (skin.alternate_csps || []).map(alt => ({
      id: alt.id,
      url: `${baseUrl}/storage/${character}/${alt.filename}`,
      poseName: alt.pose_name,
      isHd: alt.is_hd,
      timestamp: alt.timestamp,
      file: null
    }))
  )

  const buildManagedSkinData = (character, skin) => ({
    ...skin,
    character,
    cspUrl: `${baseUrl}/storage/${character}/${skin.csp_filename || `${skin.id}_csp.png`}`,
    hdCspUrl: skin.has_hd_csp
      ? `${baseUrl}/storage/${character}/${skin.hd_csp_filename || `${skin.id}_csp_hd.png`}`
      : null,
    stockUrl: skin.has_stock
      ? `${baseUrl}/storage/${character}/${skin.id}_stc.png`
      : null,
    active_csp_id: skin.active_csp_id || null,
    alternateCsps: mapAlternateCsps(character, skin)
  })

  const getManagedSkinFromMetadata = (metadata, character, skinId) => {
    const canonical = metadata?.characters?.[character]?.skins || []
    let skin = canonical.find(item => item.id === skinId && item.type !== 'folder')
    if (skin) return skin

    const customMatch = typeof character === 'string'
      ? character.match(/^custom_characters\/([^/]+)\/(skins|costumes)$/)
      : null
    if (!customMatch) return null

    const [, slug, bucket] = customMatch
    const entry = (metadata?.custom_characters || []).find(item => item.slug === slug)
    const list = bucket === 'costumes' ? entry?.costume_meta : entry?.added_skins
    return (list || []).find(item => item.id === skinId && item.type !== 'folder') || null
  }

  const refreshManagedSkinState = async (
    character = cspManagerSkin?.character,
    skinId = cspManagerSkin?.id,
    { refreshParent = true } = {}
  ) => {
    if (!character || !skinId) return null

    if (refreshParent && onRefresh) {
      await onRefresh()
    }

    const data = await api.get('/storage/metadata')

    const skin = getManagedSkinFromMetadata(data.metadata, character, skinId)
    if (!skin) {
      return null
    }

    const managedSkinData = buildManagedSkinData(character, skin)
    const isCurrentManagedSkin = cspManagerSkin?.character === character && cspManagerSkin?.id === skinId

    if (isCurrentManagedSkin) {
      setCspManagerSkin(prev => prev ? { ...prev, ...managedSkinData } : prev)
      setAlternativeCsps(managedSkinData.alternateCsps)
    }

    if (onUpdateEditingItemData) {
      onUpdateEditingItemData(managedSkinData)
    }

    return managedSkinData
  }

  // Open the Portraits modal for a skin (skinData = the edit modal's item data)
  const openCspManager = (skinData) => {
    setCspManagerSkin(skinData)
    setAlternativeCsps((skinData.alternateCsps || []).map(alt => ({ ...alt, file: null })))
    setShowCspManager(true)
  }

  const closeCspManager = () => {
    playSound('back')
    setShowCspManager(false)
    setCspManagerSkin(null)
    setAlternativeCsps([])
  }

  const portraits = useMemo(
    () => groupPortraits(cspManagerSkin, alternativeCsps),
    [cspManagerSkin, alternativeCsps])

  const manageUrl = () =>
    `/storage/costumes/${encodeURIComponent(cspManagerSkin.character)}/${encodeURIComponent(cspManagerSkin.id)}/csp/manage`

  // Run one action against the backend, then re-read the skin. Errors surface
  // as alerts (same as before); the modal stays open.
  const run = async (label, fn) => {
    if (!cspManagerSkin || busy) return
    setBusy(true)
    try {
      await fn()
      setLastImageUpdate(Date.now())
      await refreshManagedSkinState(cspManagerSkin.character, cspManagerSkin.id)
    } catch (err) {
      playSound('error')
      alert(`Error ${label}: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  // Make a portrait the one the game uses: the original (action 'reset') or an
  // alternate (action 'swap'; the backend prefers the SD member of the group).
  const handleSetActivePortrait = (portrait) => run('setting active portrait', async () => {
    const body = portrait.kind === 'original'
      ? { action: 'reset' }
      : { action: 'swap', altId: portrait.sdId || portrait.hdId }
    const data = await api.post(manageUrl(), body)
    const activeId = data.activeCspId ?? null
    setCspManagerSkin(prev => prev ? { ...prev, active_csp_id: activeId } : prev)
    if (onUpdateEditingItemActiveCsp) onUpdateEditingItemActiveCsp(activeId)
  })

  // Remove an alternate portrait -- BOTH its SD and HD files. If it was the
  // active one, fall back to the original first so active_csp_id never dangles.
  const handleRemovePortrait = (portrait) => run('removing portrait', async () => {
    if (portrait.kind !== 'alt') return
    if (portrait.isActive) {
      await api.post(manageUrl(), { action: 'reset' })
      setCspManagerSkin(prev => prev ? { ...prev, active_csp_id: null } : prev)
      if (onUpdateEditingItemActiveCsp) onUpdateEditingItemActiveCsp(null)
    }
    const ids = [portrait.sdId, portrait.hdId].filter(Boolean)
    for (const altId of ids) {
      await api.post(manageUrl(), { action: 'remove', altId })
    }
    setAlternativeCsps(prev => prev.filter(a => !ids.includes(a.id)))
    if (onUpdateEditingItemAlts) {
      onUpdateEditingItemAlts(prev => prev.filter(a => !ids.includes(a.id)))
    }
  })

  // Replace the ORIGINAL portrait with one image; the backend derives the
  // in-game SD + the HD preview (`auto`).
  const handleUploadMainCsp = ({ file }) => run('uploading portrait', async () => {
    if (!file) return
    const formData = new FormData()
    formData.append('character', cspManagerSkin.character)
    formData.append('skinId', cspManagerSkin.id)
    formData.append('csp', file)
    formData.append('auto', 'true')
    await api.post('/storage/costumes/update-csp', formData)
    playSound('camera')
  })

  // Add an alternate portrait from one image (SD + HD pair, grouped by filename).
  const handleUploadAltCsp = ({ file }) => run('adding portrait', async () => {
    if (!file) return
    const formData = new FormData()
    formData.append('action', 'add')
    formData.append('file', file)
    formData.append('auto', 'true')
    await api.post(manageUrl(), formData)
    playSound('camera')
  })

  return {
    // State
    showCspManager,
    setShowCspManager,
    cspManagerSkin,
    setCspManagerSkin,
    alternativeCsps,
    setAlternativeCsps,
    lastImageUpdate,
    setLastImageUpdate,
    portraits,
    busy,

    // Handlers
    openCspManager,
    closeCspManager,
    handleSetActivePortrait,
    handleRemovePortrait,
    handleUploadMainCsp,
    handleUploadAltCsp,
    refreshManagedSkinState,
  }
}
