/**
 * MenuMode - Menus tab of the MexPanel (installation UI).
 *
 * Mirrors the character extras pattern:
 * - Sidebar starts with CSS / SSS (like character list)
 * - Click CSS → sidebar becomes submod types (Icon Grid, Doors, Background)
 * - Click a submod type → right panel shows "Currently in MEX" + "Available to Import"
 */
import { useState, useEffect, useCallback } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { backendMediaUrl } from '../shared/config/config'
import SssLayoutEditor from './menus/SssLayoutEditor'
import CssLayoutEditor from './menus/CssLayoutEditor'
import HexagonLoader from '../shared/ui/HexagonLoader'
import PaginationBar from '../shared/ui/PaginationBar'
import usePagination from '../shared/hooks/usePagination'
import { MusicIcon } from '../shared/ui/Icons'
import { api } from '../shared/transport/api'
import { appConfirm } from '../shared/ui/appDialogs'
import { installedPreviewCandidates, partialIconText, slotDisplay, CHECKED_SLOTS } from './menuInstalledDisplay'

const MENU_TYPES = [
  { key: 'css', name: 'Character Select Screen', short: 'CSS' },
  { key: 'sss', name: 'Stage Select Screen', short: 'SSS' },
  { key: 'hud', name: 'In-Game HUD', short: 'HUD', noLayout: true },
]

const CSS_SUBMOD_TYPES = [
  { key: 'icon_grid', name: 'Icon Grid', description: 'Character portraits on the CSS banner' },
  { key: 'doors', name: 'Doors', description: 'Character panel door animations' },
  { key: 'background', name: 'Background', description: 'CSS background and stage art' },
]

const SSS_SUBMOD_TYPES = [
  { key: 'background', name: 'Background', description: 'SSS background model and animations' },
]

const HUD_SUBMOD_TYPES = [
  { key: 'pause_screen', name: 'Pause Screen', description: 'In-game pause overlay textures' },
  { key: 'percent_font', name: 'Percent Font', description: 'Damage percent digits and HUD typeface' },
  { key: 'ready_go', name: 'Ready / Go / Game', description: 'Match start/end word banners' },
]

// The installed mod's picture: the install-time snapshot, then the vault
// URLs; a vault mod that was edited away or deleted ends on the name
// placeholder rather than a broken image.
function InstalledModPreview({ mod }) {
  const candidates = installedPreviewCandidates(mod)
  // remembers which URL list the failures belong to, so a new install
  // starts again from its first candidate
  const [failed, setFailed] = useState({ key: '', count: 0 })
  const candidatesKey = candidates.join('|')
  const src = candidates[failed.key === candidatesKey ? failed.count : 0]
  if (!src) {
    return <div className="menu-mod-placeholder">{mod?.name?.[0] || '?'}</div>
  }
  return (
    <img
      key={src}
      src={backendMediaUrl(src)}
      alt={mod.name}
      onError={() => setFailed((f) => ({
        key: candidatesKey,
        count: (f.key === candidatesKey ? f.count : 0) + 1,
      }))}
    />
  )
}

export default function MenuMode({ mode, onModeChange, onOpenMenuMusic, projectPath }) {
  const [selectedMenu, setSelectedMenu] = useState(null)
  const [selectedSubmod, setSelectedSubmod] = useState(null)
  const [selectedMod, setSelectedMod] = useState(null)
  const [iconGridMods, setIconGridMods] = useState([])
  const [bgMods, setBgMods] = useState([])
  const [doorMods, setDoorMods] = useState([])
  const [pauseMods, setPauseMods] = useState([])
  const [percentMods, setPercentMods] = useState([])
  const [readygoMods, setReadygoMods] = useState([])
  const [loading, setLoading] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [installMessage, setInstallMessage] = useState('')
  const [installProgress, setInstallProgress] = useState(null) // { current, total, character }
  // "menu:submod" -> mod. The menu HAS to be part of the key: CSS and SSS
  // both have a 'background' submod, and a shared 'background' slot made
  // installing one screen's background look like it removed the other's.
  const [installedMods, setInstalledMods] = useState({})
  // Whether the project's CSS background is custom (the backend also detects
  // installs made before the per-project record existed).
  const [cssBgCustom, setCssBgCustom] = useState(false)
  const [restoring, setRestoring] = useState(false)

  // Bumped by 'nucleus:project-changed' (e.g. an assistant tool edited the
  // project) so the record below is re-read.
  const [projectEpoch, setProjectEpoch] = useState(0)
  useEffect(() => {
    const changed = () => setProjectEpoch((n) => n + 1)
    window.addEventListener('nucleus:project-changed', changed)
    return () => window.removeEventListener('nucleus:project-changed', changed)
  }, [])

  // The backend records every install per project (nucleus_menus.json), so
  // re-entering the tab shows what is really in the build instead of the
  // vanilla default it used to fall back to once this component unmounted.
  // Re-read whenever the open project changes: the tab stays mounted across
  // project switches and used to keep showing the previous project's slots.
  useEffect(() => {
    // A different project: never show the old project's slots meanwhile.
    setInstalledMods({})
  }, [projectPath])

  useEffect(() => {
    let cancelled = false
    api.get('/menus/installed')
      .then((data) => { if (!cancelled && data?.installed) setInstalledMods(data.installed) })
      .catch((err) => console.error('Failed to fetch installed menu mods:', err))
    return () => { cancelled = true }
  }, [projectPath, projectEpoch])

  useEffect(() => { setCssBgCustom(false) }, [projectPath])

  // The open menu's slots are also read from the project files (a pre-modded
  // ISO, or edits made outside the app). That takes seconds on a cache miss,
  // so it runs per menu page and never blocks: the record shows first and
  // the check refines it.
  const [slotVerification, setSlotVerification] = useState({})
  const [slotVerifying, setSlotVerifying] = useState(false)
  const [checkNonce, setCheckNonce] = useState(0)
  useEffect(() => { setSlotVerification({}) }, [projectPath])

  useEffect(() => {
    const checked = CHECKED_SLOTS[selectedMenu]
    if (!checked) return
    let cancelled = false
    setSlotVerifying(true)
    api.get('/menus/installed', { query: { verify: selectedMenu } })
      .then((data) => {
        if (cancelled) return
        if (data?.installed) {
          // only the checked slots: another install may have landed while
          // this (slow) check ran
          setInstalledMods((prev) => {
            const next = { ...prev }
            for (const key of checked) {
              if (data.installed[key]) next[key] = data.installed[key]
              else delete next[key]
            }
            return next
          })
        }
        const verification = data?.verification && typeof data.verification === 'object' ? data.verification : {}
        setSlotVerification((prev) => {
          const next = { ...prev }
          for (const key of checked) {
            if (verification[key]) next[key] = verification[key]
            else delete next[key]
          }
          return next
        })
      })
      .catch((err) => console.error('Failed to check menu slots:', err))
      .finally(() => { if (!cancelled) setSlotVerifying(false) })
    return () => { cancelled = true; setSlotVerifying(false) }
  }, [selectedMenu, projectPath, projectEpoch, checkNonce])

  // A write to the project makes the last check result stale.
  const recheckSlots = (...keys) => {
    setSlotVerification((prev) => {
      const next = { ...prev }
      for (const key of keys) delete next[key]
      return next
    })
    setCheckNonce((n) => n + 1)
  }

  useEffect(() => {
    if (selectedMenu !== 'css' || selectedSubmod !== 'background') return
    let cancelled = false
    api.get('/menus/css/background/status')
      .then((data) => { if (!cancelled) setCssBgCustom(!!data?.custom) })
      .catch((err) => console.error('Failed to fetch CSS background status:', err))
    return () => { cancelled = true }
  }, [selectedMenu, selectedSubmod, projectPath, projectEpoch])

  // Percent Font / Ready-Go: put that category's vanilla pictures back.
  const handleRestoreVanillaHud = async (submod) => {
    const label = submod === 'ready_go' ? 'Ready / Go / Game graphics' : 'percent font'
    const confirmed = await appConfirm(
      `Put the vanilla ${label} back into this project? `
      + 'Only these HUD textures change; stock icons and everything else stay as they are.',
      { title: 'Restore Vanilla', confirmText: 'Restore' },
    )
    if (!confirmed) return
    setRestoring(true)
    setInstallMessage('')
    try {
      const data = await api.post('/menus/percent/restore-vanilla', { slot: submod })
      playSound('newSkin')
      setInstallMessage(`✓ ${data.message}`)
      setInstalledMods(prev => {
        const next = { ...prev }
        delete next[`hud:${submod}`]
        return next
      })
      recheckSlots('hud:percent_font', 'hud:ready_go')
    } catch (err) {
      playSound('error')
      setInstallMessage(`✗ ${err.message}`)
    } finally {
      setRestoring(false)
      setTimeout(() => setInstallMessage(''), 6000)
    }
  }

  const handleRestoreVanillaCssBg = async () => {
    const confirmed = await appConfirm(
      'Put the vanilla character select background back into this project? '
      + 'Only the CSS background changes; icons, doors, characters, stages and music stay as they are.',
      { title: 'Restore Vanilla Background', confirmText: 'Restore' },
    )
    if (!confirmed) return
    setRestoring(true)
    setInstallMessage('')
    try {
      const data = await api.post('/menus/css/background/restore-vanilla')
      playSound('newSkin')
      setInstallMessage(`✓ ${data.message}`)
      setCssBgCustom(false)
      setInstalledMods(prev => {
        const next = { ...prev }
        delete next['css:background']
        return next
      })
      recheckSlots('css:background')
    } catch (err) {
      playSound('error')
      setInstallMessage(`✗ ${err.message}`)
    } finally {
      setRestoring(false)
      setTimeout(() => setInstallMessage(''), 6000)
    }
  }

  const fetchIconGridMods = useCallback(async () => {
    try {
      const data = await api.get('/menus/css/icon_grid/list')
      setIconGridMods(data.mods || [])
    } catch (err) {
      console.error('Failed to fetch icon grid mods:', err)
    }
  }, [])

  const fetchBgMods = useCallback(async () => {
    try {
      const data = await api.get('/menus/background/list')
      setBgMods(data.mods || [])
    } catch (err) {
      console.error('Failed to fetch background mods:', err)
    }
  }, [])

  const fetchDoorMods = useCallback(async () => {
    try {
      const data = await api.get('/menus/css/doors/list')
      setDoorMods(data.mods || [])
    } catch (err) {
      console.error('Failed to fetch door mods:', err)
    }
  }, [])

  const fetchPauseMods = useCallback(async () => {
    try {
      const data = await api.get('/menus/pause/list')
      setPauseMods(data.mods || [])
    } catch (err) {
      console.error('Failed to fetch pause mods:', err)
    }
  }, [])

  const fetchPercentMods = useCallback(async () => {
    try {
      const data = await api.get('/menus/percent/list?category=percent')
      setPercentMods(data.mods || [])
    } catch (err) {
      console.error('Failed to fetch percent mods:', err)
    }
  }, [])

  const fetchReadygoMods = useCallback(async () => {
    try {
      const data = await api.get('/menus/percent/list?category=readygo')
      setReadygoMods(data.mods || [])
    } catch (err) {
      console.error('Failed to fetch ready/go mods:', err)
    }
  }, [])

  // One loading flag covering ALL of the selected menu's fetches - previously
  // only the icon-grid fetch toggled it, so pause/doors/background lists
  // flashed "No mods in vault" and then popped in
  useEffect(() => {
    let fetches = []
    if (selectedMenu === 'css') fetches = [fetchIconGridMods(), fetchBgMods(), fetchDoorMods()]
    if (selectedMenu === 'sss') fetches = [fetchBgMods()]
    if (selectedMenu === 'hud') fetches = [fetchPauseMods(), fetchPercentMods(), fetchReadygoMods()]
    if (fetches.length === 0) return

    let cancelled = false
    setLoading(true)
    Promise.all(fetches).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedMenu, fetchIconGridMods, fetchBgMods, fetchDoorMods, fetchPauseMods, fetchPercentMods, fetchReadygoMods])

  const getModsForSubmod = (key) => {
    if (key === 'icon_grid') return iconGridMods
    if (key === 'background') {
      // A CSS backdrop and an SSS backdrop are different models — offer only
      // this screen's kind (untagged legacy imports stay visible on both).
      return bgMods.filter((m) => !m.source || m.source === selectedMenu)
    }
    if (key === 'doors') return doorMods
    if (key === 'pause_screen') return pauseMods
    if (key === 'percent_font') return percentMods
    if (key === 'ready_go') return readygoMods
    return []
  }

  // Pagination for the "Available to Import" mod list. Lives up here (before
  // any conditional return) so the hook order is stable across renders.
  const currentMods = selectedSubmod ? getModsForSubmod(selectedSubmod) : []
  const modsPager = usePagination(currentMods.length, `${selectedMenu}-${selectedSubmod}`)

  const handleInstall = async () => {
    if (!selectedMod) return
    setInstalling(true)
    setInstallMessage('')
    setInstallProgress(null)
    try {
      if (selectedSubmod === 'icon_grid') {
        // Per-icon install with progress
        const plan = await api.post(`/menus/css/icon_grid/install/${selectedMod.id}`)

        const icons = plan.icons
        let installed = 0, errors = []
        for (let i = 0; i < icons.length; i++) {
          setInstallProgress({ current: i + 1, total: icons.length, character: icons[i].character })
          try {
            await api.post(`/menus/css/icon_grid/install/${selectedMod.id}/icon`, icons[i])
            installed++
          } catch { errors.push(icons[i].character) }
        }

        if (installed > 0) {
          playSound('newSkin')
          let msg = `✓ Installed ${installed} icon(s). Rebuild ISO to apply.`
          if (errors.length) msg += ` (${errors.length} failed)`
          setInstallMessage(msg)
          // The backend recorded each icon as it landed (including how many of
          // the planned icons made it); show that record, not a guess.
          const slotKey = `${selectedMenu}:${selectedSubmod}`
          const optimistic = { ...selectedMod, icons_installed: Array(installed).fill(''), icons_total: icons.length }
          setInstalledMods(prev => ({ ...prev, [slotKey]: optimistic }))
          recheckSlots(slotKey)
          api.get('/menus/installed')
            .then((data) => { if (data?.installed?.[slotKey]) setInstalledMods(prev => ({ ...prev, [slotKey]: data.installed[slotKey] })) })
            .catch(() => {})
        } else {
          playSound('error')
          setInstallMessage(`✗ No icons installed`)
        }
      } else {
        let installEndpoint
        if (selectedMenu === 'sss' && selectedSubmod === 'background') {
          installEndpoint = `/menus/sss/background/install/${selectedMod.id}`
        } else if (selectedSubmod === 'background') {
          installEndpoint = `/menus/css/background/install/${selectedMod.id}`
        } else if (selectedSubmod === 'doors') {
          installEndpoint = `/menus/css/doors/install/${selectedMod.id}`
        } else if (selectedSubmod === 'pause_screen') {
          installEndpoint = `/menus/pause/install/${selectedMod.id}`
        } else if (selectedSubmod === 'percent_font' || selectedSubmod === 'ready_go') {
          installEndpoint = `/menus/percent/install/${selectedMod.id}`
        } else {
          installEndpoint = `/menus/css/icon_grid/install/${selectedMod.id}`
        }
        // HUD typeface installs say which tab they came from: one mod can
        // cover both Percent Font and Ready/Go, and the backend reports every
        // slot it recorded.
        const isHudTypeface = selectedSubmod === 'percent_font' || selectedSubmod === 'ready_go'
        const data = await api.post(installEndpoint, isHudTypeface ? { slot: selectedSubmod } : undefined)
        playSound('newSkin')
        setInstallMessage(`✓ ${data.message}`)
        setInstalledMods(prev => ({
          ...prev,
          [`${selectedMenu}:${selectedSubmod}`]: selectedMod,
          ...(data?.installed && typeof data.installed === 'object' ? data.installed : {}),
        }))
        // the old check result describes the file before this install
        recheckSlots(`${selectedMenu}:${selectedSubmod}`,
          ...(isHudTypeface ? ['hud:percent_font', 'hud:ready_go'] : []))
        if (selectedMenu === 'css' && selectedSubmod === 'background') setCssBgCustom(true)
      }
    } catch (err) {
      playSound('error')
      setInstallMessage(`✗ ${err.message}`)
    } finally {
      setInstalling(false)
      setInstallProgress(null)
      setTimeout(() => setInstallMessage(''), 4000)
    }
  }

  const submodTypes = selectedMenu === 'css' ? CSS_SUBMOD_TYPES
    : selectedMenu === 'sss' ? SSS_SUBMOD_TYPES
    : selectedMenu === 'hud' ? HUD_SUBMOD_TYPES : []

  // ── Layout editors (not a normal import flow) ──
  if ((selectedMenu === 'css' || selectedMenu === 'sss') && selectedSubmod === 'layout') {
    const EditorComponent = selectedMenu === 'css' ? CssLayoutEditor : SssLayoutEditor
    return (
      <div className="mex-content" style={{ flexDirection: 'column' }}>
        <div style={{ padding: 'var(--space-2) var(--space-3)', borderBottom: '1px solid var(--color-border-subtle)' }}>
          <button
            className="back-button"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('back'); setSelectedSubmod(null); setSelectedMod(null); setSelectedMenu(null) }}
          >
            &larr; Back to Menus
          </button>
        </div>
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <EditorComponent />
        </div>
      </div>
    )
  }

  // ── Submod type selected → extras-style view ──
  if (selectedMenu && selectedSubmod) {
    const submod = submodTypes.find(s => s.key === selectedSubmod)
    const mods = getModsForSubmod(selectedSubmod)
    const slotKey = `${selectedMenu}:${selectedSubmod}`
    const installedMod = installedMods[slotKey]
    const isCheckedSlot = !!CHECKED_SLOTS[selectedMenu]?.includes(slotKey)
    const verification = slotVerification[slotKey]
    // no check result yet (or none possible): the record, as before
    const display = slotDisplay(installedMod, verification)
    // the record, unless the file check says the slot holds something else
    const shownMod = display.kind === 'mod' ? installedMod : null
    const fileCustom = display.kind === 'custom'
    const isCssBg = selectedMenu === 'css' && selectedSubmod === 'background'
    const showRestoreBg = isCssBg && (!!installedMod || cssBgCustom || fileCustom)
    // pre-check behavior: the background code without a record = custom
    const legacyCustomBg = isCssBg && !verification && !installedMod && cssBgCustom
    const isHudTypefaceSlot = selectedMenu === 'hud'
      && (selectedSubmod === 'percent_font' || selectedSubmod === 'ready_go')
    // offered while the slot holds anything but vanilla (per record or file)
    const showRestoreHud = isHudTypefaceSlot && (!!installedMod || fileCustom)
    const slotNotes = (
      <>
        {display.note ? <span className="menu-mod-meta">{display.note}</span> : null}
        {isCheckedSlot && slotVerifying
          ? <span className="menu-mod-meta">Checking the project file...</span>
          : null}
      </>
    )

    return (
      <div className="mex-content">
        {/* Left sidebar: submod types list (like extras list) */}
        <div className="fighters-list">
          <div className="extras-header">
            <h3>{selectedMenu.toUpperCase()} Mods</h3>
            <button
              className="btn-back-small"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('back'); setSelectedSubmod(null); setSelectedMod(null); setSelectedMenu(null) }}
            >
              ← Back
            </button>
          </div>
          <div className="fighter-items">
            {submodTypes.map(st => (
              <div
                key={st.key}
                className={`fighter-item ${selectedSubmod === st.key ? 'selected' : ''}`}
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setSelectedSubmod(st.key); setSelectedMod(null) }}
              >
                <div className="fighter-content">
                  <div className="fighter-name">{st.name}</div>
                  <div className="fighter-info">
                    <span className="costume-count">
                      {st.key === 'layout' ? 'editor' : `${getModsForSubmod(st.key).length} in vault`}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right panel: Currently in MEX + Available to Import */}
        <div className="costumes-panel">
          {/* Currently in MEX */}
          <div className="costumes-section">
            <div className="costumes-section-header">
              <h3>Currently in MEX</h3>
              {showRestoreHud && (
                <div className="batch-controls">
                  <button
                    className="btn-batch-import btn-batch-delete"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); handleRestoreVanillaHud(selectedSubmod) }}
                    disabled={restoring || installing}
                    title="Put the original Melee HUD textures for this page back into this project"
                  >
                    {restoring ? 'Restoring...' : 'Restore Vanilla'}
                  </button>
                </div>
              )}
              {showRestoreBg && (
                <div className="batch-controls">
                  <button
                    className="btn-batch-import btn-batch-delete"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); handleRestoreVanillaCssBg() }}
                    disabled={restoring || installing}
                    title="Put the original Melee CSS background back into this project"
                  >
                    {restoring ? 'Restoring...' : 'Restore Vanilla Background'}
                  </button>
                </div>
              )}
            </div>
            <div className="costume-list existing">
              {shownMod ? (
                <div className="costume-card existing-costume menu-mod-card">
                  <div className="costume-preview">
                    <InstalledModPreview mod={shownMod} />
                  </div>
                  <div className="costume-info">
                    <h4>{shownMod.name}</h4>
                    {partialIconText(shownMod) ? (
                      <span className="menu-mod-meta">{partialIconText(shownMod)}</span>
                    ) : shownMod.icon_count ? (
                      <span className="menu-mod-meta">{shownMod.icon_count} icons</span>
                    ) : null}
                    {slotNotes}
                  </div>
                </div>
              ) : (
                <div className="costume-card existing-costume vanilla-extra menu-mod-card">
                  <div className="costume-preview">
                    <div className="menu-mod-placeholder">{legacyCustomBg || fileCustom ? 'Custom' : 'Vanilla'}</div>
                  </div>
                  <div className="costume-info">
                    <h4>{legacyCustomBg ? 'Custom background' : fileCustom ? 'Custom (unknown)' : 'Vanilla'}</h4>
                    {slotNotes}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Available to Import */}
          <div className="costumes-section">
            <div className="costumes-section-header">
              <h3>Available to Import</h3>
              <div className="batch-controls">
                {selectedMod && (
                  <button
                    className="btn-batch-import"
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('start'); handleInstall() }}
                    disabled={installing}
                  >
                    {installing ? 'Installing...' : 'Import Selected'}
                  </button>
                )}
                {installMessage && (
                  <span style={{ fontSize: '0.8rem', color: installMessage.startsWith('✓') ? 'var(--color-success, #4caf50)' : 'var(--color-danger, #f44336)' }}>
                    {installMessage}
                  </span>
                )}
              </div>
            </div>
            <div className="costume-list">
              {loading ? (
                <div className="no-costumes menu-mod-loading">
                  <HexagonLoader size={72} decorative />
                  <p>Loading mods…</p>
                </div>
              ) : mods.length === 0 ? (
                <div className="no-costumes">
                  <p>No {submod?.name || 'mods'} in vault. Import some from the Menus vault tab first.</p>
                </div>
              ) : (
                mods.slice(modsPager.start, modsPager.end).map(mod => (
                  <div
                    key={mod.id}
                    className={`costume-card menu-mod-card ${selectedMod?.id === mod.id ? 'selected' : ''}`}
                    onMouseEnter={playHoverSound}
                    onClick={() => { playSound('boop'); setSelectedMod(mod) }}
                  >
                    <div className="costume-preview">
                      {(mod.screenshotUrl || mod.imageUrl) ? (
                        <img
                          src={backendMediaUrl(mod.screenshotUrl || mod.imageUrl)}
                          alt={mod.name}
                          onError={(e) => { e.target.style.display = 'none' }}
                        />
                      ) : (
                        <div className="menu-mod-placeholder">
                          {mod.name?.[0] || '?'}
                        </div>
                      )}
                      <input
                        type="checkbox"
                        className="costume-checkbox"
                        checked={selectedMod?.id === mod.id}
                        readOnly
                      />
                    </div>
                    <div className="costume-info">
                      <h4>{mod.name}</h4>
                      {mod.icon_count ? (
                        <span className="menu-mod-meta">{mod.icon_count} icons</span>
                      ) : null}
                    </div>
                  </div>
                ))
              )}
            </div>
            <PaginationBar pager={modsPager} />
          </div>
        </div>

        {(installing || restoring) && (
          <div className="import-overlay">
            <div className="import-modal import-modal--hexagon">
              <HexagonLoader
                className="import-loader"
                size={104}
                label={restoring ? 'Restoring vanilla' : 'Installing mod'}
                progress={installProgress ? (installProgress.current / installProgress.total) * 100 : null}
                minimumVisibleProgress={6}
              />
              <h3>{restoring ? 'Restoring...' : 'Installing...'}</h3>
              <p className="import-status">
                {installProgress
                  ? `${installProgress.character} (${installProgress.current}/${installProgress.total})`
                  : 'Please wait...'}
              </p>
            </div>
          </div>
        )}
      </div>
    )
  }

  // ── Menu type selected → show submod types in sidebar ──
  if (selectedMenu) {
    return (
      <div className="mex-content">
        <div className="fighters-list">
          <div className="extras-header">
            <h3>{selectedMenu.toUpperCase()} Mods</h3>
            <button
              className="btn-back-small"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('back'); setSelectedMenu(null) }}
            >
              ← Back
            </button>
          </div>
          <div className="fighter-items">
            {submodTypes.map(st => (
              <div
                key={st.key}
                className={`fighter-item`}
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setSelectedSubmod(st.key) }}
              >
                <div className="fighter-content">
                  <div className="fighter-name">{st.name}</div>
                  <div className="fighter-info">
                    <span className="costume-count">{st.key === 'layout' ? 'editor' : `${getModsForSubmod(st.key).length} in vault`}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="costumes-panel">
          <div className="no-selection">
            <p>Select a mod type from the sidebar</p>
          </div>
        </div>
      </div>
    )
  }

  // ── Default: menu type selection (CSS / SSS) ──
  return (
    <div className="mex-content">
      <div className="fighters-list">
        <div className="fighters-header">
          <div className="mode-toggle">
            <button
              className={`mode-toggle-btn ${mode === 'characters' ? 'active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => { if (mode !== 'characters') { playSound('boop'); onModeChange('characters') } }}
            >
              Fighters
            </button>
            <button
              className={`mode-toggle-btn ${mode === 'stages' ? 'active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => { if (mode !== 'stages') { playSound('boop'); onModeChange('stages') } }}
            >
              Stages
            </button>
            <button
              className={`mode-toggle-btn ${mode === 'menus' ? 'active' : ''}`}
              onMouseEnter={playHoverSound}
              onClick={() => { if (mode !== 'menus') { playSound('boop'); onModeChange('menus') } }}
            >
              Menus
            </button>
            <button
              className="mode-music-btn"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); onOpenMenuMusic() }}
              title="Edit menu music"
              aria-label="Edit menu music"
            >
              <MusicIcon size={14} />
            </button>
          </div>
          <span className="fighters-count">{MENU_TYPES.length}</span>
        </div>

        <div className="fighter-items">
          {MENU_TYPES.map(mt => (
            <div
              key={mt.key}
              className="fighter-item"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); setSelectedMenu(mt.key) }}
            >
              <div className="fighter-content" style={{ flex: 1 }}>
                <div className="fighter-name">{mt.short}</div>
                <div className="fighter-info">
                  <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted, #888)' }}>{mt.name}</span>
                </div>
              </div>
              {!mt.noLayout && (
                <button
                  className="sss-action-btn add"
                  style={{ flex: 'none', padding: '0.4rem 0.75rem', fontSize: '0.75rem' }}
                  onMouseEnter={playHoverSound}
                  onClick={(e) => {
                    e.stopPropagation()
                    playSound('boop')
                    setSelectedMenu(mt.key)
                    setSelectedSubmod('layout')
                  }}
                >
                  Edit Layout
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="costumes-panel">
        <div className="no-selection">
          <p>Select a menu type from the sidebar</p>
        </div>
      </div>
    </div>
  )
}
