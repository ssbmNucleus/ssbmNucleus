/**
 * MenuKindPane - the right-hand pane of the vault's Menus mode: one kind's
 * header, its card grid, and the kind's editor when one is open.
 *
 * All seven kinds share the list state + card actions (useMenuModList /
 * MenuModCards); the three kinds with editors (icon grids, pause screens,
 * HUD typefaces) open theirs full-width in place of the grid, and the kinds
 * that can start from scratch get a trailing "+" card. `onDetailChange`
 * tells the parent to hide the sidebar while an editor is open.
 *
 * Importing is the vault's floating Import button (auto-detected), so there
 * is no import UI here.
 */
import { useEffect, useRef, useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { appConfirm, appPrompt } from '../../shared/ui/appDialogs'
import { api } from '../../shared/transport/api'
import { useInGameTest } from '../hooks/useInGameTest'
import InGameTestPanel from '../../shared/viewer/InGameTestPanel'
import IconGridDetailView from './IconGridDetailView'
import PauseTextureEditor from './PauseTextureEditor'
import PercentFontEditor from './PercentFontEditor'
import MenuModCards from './MenuModCards'
import useMenuModList from './useMenuModList'

const CameraIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
    <circle cx="12" cy="13" r="4" />
  </svg>
)

export default function MenuKindPane({ kind, refreshKey, expectedCount, onDetailChange, onCountsChanged }) {
  const list = useMenuModList(kind, refreshKey, { onChanged: onCountsChanged })

  // Editors. Only one of these is ever in use per kind.
  const [iconGridModId, setIconGridModId] = useState(null)          // icon_grid
  const [editingMod, setEditingMod] = useState(null)                // pause / percent
  const [draftMode, setDraftMode] = useState(false)
  const [captureTarget, setCaptureTarget] = useState(null)          // pause capture
  const test = useInGameTest()

  const detailOpen = Boolean(iconGridModId || editingMod)
  useEffect(() => { onDetailChange?.(detailOpen) }, [detailOpen, onDetailChange])

  // A finished pause capture saved the screenshot backend-side.
  useEffect(() => {
    if (kind.editor === 'pause' && test.testResult?.captured) {
      list.bumpCache()
      list.refresh()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [test.testResult])

  const apiBase = kind.editor === 'pause' ? '/menus/pause' : '/menus/percent'

  const openEditor = (mod) => {
    if (kind.editor === 'icon_grid') { setIconGridModId(mod.id); return }
    setEditingMod(mod)
    setDraftMode(false)
  }

  const closeEditor = () => {
    setEditingMod(null)
    setDraftMode(false)
    list.bumpCache()
    list.refresh()
    onCountsChanged?.()
  }

  // "+" on kinds without a from-scratch editor: pick a file and send it
  // through the one import pipeline with the kind already decided, so the
  // detector never has to guess (a lone PNG here IS a door).
  const pickInput = useRef(null)
  const [pickBusy, setPickBusy] = useState(false)
  const handlePicked = async (e) => {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (!files.length) return
    setPickBusy(true)
    try {
      const fd = new FormData()
      for (const f of files) fd.append('file', f)
      fd.append('mod_type', kind.create.pick.hint)
      fd.append('duplicate_action', 'skip')
      const data = await api.post('/import/file', fd).catch((err) => err.data || Promise.reject(err))
      if (!data.success) throw new Error(data.error || 'import failed')
      playSound('newSkin')
      list.bumpCache()
      await list.refresh()
      onCountsChanged?.()
    } catch (err) {
      playSound('error')
      alert(`Import failed: ${err.message}`)
    } finally {
      setPickBusy(false)
    }
  }

  // "+" on kinds with an editor creates an uncommitted DRAFT (not in the
  // vault) and drops straight into it. It only lands when the user saves.
  const handleCreate = async () => {
    if (kind.create?.pick) { pickInput.current?.click(); return }
    if (kind.editor === 'icon_grid') {
      // Icon grids have no draft state: the vanilla-seeded grid is a real
      // mod straight away and opens in the per-icon editor.
      setPickBusy(true)
      try {
        const data = await api.post('/menus/css/icon_grid/create', {})
        playSound('newSkin')
        await list.refresh()
        onCountsChanged?.()
        setIconGridModId(data.mod.id)
      } catch (err) {
        playSound('error')
        alert(`Create failed: ${err.data?.error || err.message}`)
      } finally {
        setPickBusy(false)
      }
      return
    }
    try {
      const body = { draft: true }
      if (kind.create?.category) body.category = kind.create.category
      const data = await api.post(`${apiBase}/create`, body)
      playSound('newSkin')
      setEditingMod(data.mod)
      setDraftMode(true)
    } catch (err) {
      alert(`Create failed: ${err.message}`)
    }
  }

  const commitDraft = async () => {
    const mod = editingMod
    if (!mod) return
    const name = await appPrompt(`Name this ${kind.singular.toLowerCase()}:`, {
      title: `Save ${kind.singular}`,
      defaultValue: mod.name || `New ${kind.singular}`,
      confirmText: 'Save',
    })
    if (name === null) return  // cancelled — stay in the editor
    try {
      await api.post(`${apiBase}/${mod.id}/save`, { name: name.trim() || mod.name })
      playSound('newSkin')
      closeEditor()
    } catch (err) {
      alert(`Save failed: ${err.message}`)
    }
  }

  const discardDraft = async () => {
    const mod = editingMod
    if (!mod) return
    if (!await appConfirm(`Discard this unsaved ${kind.singular.toLowerCase()}?`, {
      title: 'Discard Draft',
      confirmText: 'Discard',
    })) return
    try { await api.post(`${apiBase}/${mod.id}/discard`) } catch { /* best effort */ }
    playSound('back')
    closeEditor()
  }

  const handleCapture = (mod) => {
    setCaptureTarget(mod)
    test.capturePauseScreenshot({ modId: mod.id, name: mod.name })
  }

  // ── editors take the whole pane ─────────────────────────────────────────
  if (kind.editor === 'icon_grid' && iconGridModId) {
    return (
      <IconGridDetailView
        modId={iconGridModId}
        onBack={() => { setIconGridModId(null); list.refresh() }}
        onModUpdated={(updated) => {
          list.setMods((prev) => prev.map((m) => (m.id === updated.id ? { ...m, ...updated } : m)))
        }}
      />
    )
  }
  if (kind.editor === 'pause' && editingMod) {
    return (
      <PauseTextureEditor
        mod={editingMod}
        isDraft={draftMode}
        onSaveDraft={commitDraft}
        onDiscardDraft={discardDraft}
        onBack={closeEditor}
      />
    )
  }
  if (kind.editor === 'percent' && editingMod) {
    return (
      <PercentFontEditor
        mod={editingMod}
        mode={kind.key === 'ready_go' ? 'words' : 'glyphs'}
        isDraft={draftMode}
        onSaveDraft={commitDraft}
        onDiscardDraft={discardDraft}
        onBack={closeEditor}
      />
    )
  }

  // ── the cards ───────────────────────────────────────────────────────────
  // While the first fetch is in flight, the sidebar's count (if known) is a
  // better number than the empty list's 0 -- keeps the header from flickering.
  const count = list.loading && expectedCount !== undefined ? expectedCount : list.mods.length
  return (
    <div className="menu-kind-pane">
      <div className="menu-kind-header">
        <div className="menu-kind-title">
          <h2>{kind.label}</h2>
          <span className="menu-kind-count">{count} mod{count === 1 ? '' : 's'}</span>
        </div>
      </div>

      {kind.editor === 'pause' && captureTarget && (test.testingInGame || test.testResult || test.testError) && (
        <div className="vault-panel-box">
          <InGameTestPanel
            test={test}
            onStart={() => test.capturePauseScreenshot({ modId: captureTarget.id, name: captureTarget.name })}
            label="Capture Pause Screenshot"
          />
        </div>
      )}

      <MenuModCards
        kind={kind}
        mods={list.mods}
        loading={list.loading}
        expectedCount={expectedCount}
        cacheBust={list.cacheBust}
        onOpen={kind.editor ? openEditor : undefined}
        onRename={list.rename}
        onReplaceImage={list.replaceImage}
        onExport={list.exportMod}
        onDelete={list.remove}
        extraActions={kind.editor === 'pause' ? (mod) => [{
          key: 'capture',
          label: 'Capture',
          icon: <CameraIcon />,
          title: "Capture a live in-game pause screenshot as this mod's preview",
          disabled: test.testingInGame,
          onClick: () => handleCapture(mod),
        }] : undefined}
        cardExtra={kind.sceneToggle ? (mod) => (
          <label
            className="mmod-toggle"
            title="Also install the background's camera, lighting, and fog settings. Turn off if the background looks wrong on a different screen."
          >
            <input
              type="checkbox"
              checked={!!mod.includeScene}
              onChange={() => list.patch(mod, { includeScene: !mod.includeScene }).catch((err) => alert(`Update failed: ${err.message}`))}
            />
            Scene settings
          </label>
        ) : undefined}
        createCard={kind.create ? {
          label: pickBusy ? 'Importing…' : kind.create.label,
          title: kind.create.title,
          onClick: handleCreate,
        } : undefined}
      />
      {kind.create?.pick && (
        <input
          ref={pickInput}
          type="file"
          accept={kind.create.pick.accept}
          multiple={!!kind.create.pick.multiple}
          style={{ display: 'none' }}
          onChange={handlePicked}
        />
      )}
    </div>
  )
}
