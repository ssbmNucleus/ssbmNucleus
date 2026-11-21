import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { backendMediaUrl } from '../../shared/config/config'
import GameTestCard from './GameTestCard'
import WorkbenchViewer from './WorkbenchViewer'
import { opensFor, viewKey, workbenchTabs } from './workbench'
import './WorkbenchPanel.css'

const OPEN_KEY = 'nucleus_workbench_open'
const readOpen = () => { try { return localStorage.getItem(OPEN_KEY) !== '0' } catch { return true } }
const writeOpen = value => { try { localStorage.setItem(OPEN_KEY, value ? '1' : '0') } catch { /* per-viewer nicety */ } }
const fileUrl = id => backendMediaUrl(`/api/assistant/files/${id}?preview=1`)
const pictureUrl = picture => picture.file ? fileUrl(picture.file.file_id) : backendMediaUrl(picture.image)
// A file name the user attached reads as words in a title: "tung_tung_sahur on Young Link" -> "Tung Tung Sahur on
// Young Link". Only names joined by underscores change; a name already in words stays as it is.
const cap = word => word ? word[0].toUpperCase() + word.slice(1) : word
export const friendlyTitle = title => String(title || '').replace(/\b[a-z0-9]+(?:_+[a-z0-9]+)+\b/gi,
  name => name.split(/_+/).map(cap).join(' '))

/** What a picture dragged out of the workbench carries: the file record the
    message bar attaches as it is, so nothing is uploaded again. */
export const PICTURE_DRAG_TYPE = 'application/x-nucleus-file'

export function useWorkbenchOpen() {
  const [open, setOpen] = useState(readOpen)
  return [open, value => { setOpen(value); writeOpen(value) }]
}

async function copyImage(url) {
  const response = await fetch(url)
  if (!response.ok) throw new Error('The picture could not be read.')
  let blob = await response.blob()
  // The desktop app writes through Electron's own clipboard (any image format,
  // no permission prompt); navigator.clipboard is the browser fallback.
  if (window.electron?.copyImage) return window.electron.copyImage(new Uint8Array(await blob.arrayBuffer()))
  // The clipboard takes PNG everywhere; a preview may arrive as JPEG.
  if (blob.type !== 'image/png') {
    const bitmap = await createImageBitmap(blob)
    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width; canvas.height = bitmap.height
    canvas.getContext('2d').drawImage(bitmap, 0, 0)
    blob = await new Promise((resolve, reject) => canvas.toBlob(png => png ? resolve(png) : reject(new Error('The picture could not be copied.')), 'image/png'))
  }
  await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
}

const dragPicture = picture => event => {
  if (!picture.file) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData(PICTURE_DRAG_TYPE, JSON.stringify(picture.file))
}

/** Beside the chat: the thing Randall is making, as it changes.

    3D is the newest working file in the live viewer; In game is a running game
    test. A model import shows here once it has written its costume file: the
    panel opens on it in 3D, titled with the costume and its fighter (the chat's
    import card shows the steps while it runs). Skin Lab and Stage Lab also have
    Pictures: every render Randall made in this chat to judge his edits, grouped
    by step, newest selected, and the step under way under the title. The panel
    follows along by itself: a new file brings 3D forward, a game test brings In
    game forward, and new pictures only light up their tab so they never pull
    the user away from the model they are turning.

    A picture opens over the whole window (not the panel, which sits inside a
    CSS container that would trap a fixed overlay, so it is portalled to the
    body), right-clicks to copy or attach, and drags onto the message bar. */
export default function WorkbenchPanel({ state, visible, open, onOpenChange, gameTool, chatId, onAttach }) {
  const [tab, setTab] = useState(state.focus || '3d')
  const [pickedKey, setPickedKey] = useState(null)
  const pick = key => setPickedKey(key)
  const [viewing, setViewing] = useState(false)
  const [menu, setMenu] = useState(null)
  const [notice, setNotice] = useState('')
  const [seenPictures, setSeenPictures] = useState(0)
  const followKey = `${state.subject?.key}|${state.focus}|${viewKey(state.model)}|${state.game}`
  const lastFollow = useRef('')
  const arrived = useRef(null)
  const strip = useRef(null)
  const gallery = state.gallery || []
  // The newest picture: the gallery runs oldest first.
  const newestKey = gallery.length ? gallery[gallery.length - 1].key : null
  useEffect(() => {
    if (followKey === lastFollow.current) return
    lastFollow.current = followKey
    if (state.focus) setTab(state.focus)
  }, [followKey, state.focus])
  useEffect(() => {
    const last = arrived.current
    arrived.current = { chat: chatId, arrival: state.arrival || null }
    if (!open && opensFor(last, chatId, state.arrival)) onOpenChange(true)
    // Only a new arrival opens it; `open` and `onOpenChange` are read as they are then.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, state.arrival])
  // New pictures select the newest one, so the panel follows the work as it happens; older ones stay one click away.
  useEffect(() => { setPickedKey(newestKey || null) }, [state.pictures?.seq, newestKey])
  useEffect(() => { if (tab === 'pictures') setSeenPictures(state.pictures?.seq || 0) }, [tab, state.pictures?.seq])
  const index = Math.max(0, gallery.findIndex(picture => picture.key === pickedKey))
  const shown = gallery[index]
  // From the CURRENT pick, not this render's: keys pressed faster than a render (or held) all count.
  const step = delta => { setPickedKey(current => {
    if (!gallery.length) return current
    const at = Math.max(0, gallery.findIndex(picture => picture.key === current))
    return gallery[(at + delta + gallery.length) % gallery.length].key
  }) }
  useEffect(() => {
    if (!viewing && !menu) return undefined
    const keys = event => {
      if (event.key === 'Escape') { event.stopPropagation(); if (menu) setMenu(null); else setViewing(false) }
      else if (viewing && event.key === 'ArrowLeft') { event.preventDefault(); step(-1) }
      else if (viewing && event.key === 'ArrowRight') { event.preventDefault(); step(1) }
    }
    window.addEventListener('keydown', keys, true)
    return () => window.removeEventListener('keydown', keys, true)
  })
  useEffect(() => {
    if (!menu) return undefined
    const close = () => setMenu(null)
    window.addEventListener('mousedown', close)
    window.addEventListener('blur', close)
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('blur', close) }
  }, [menu])
  useEffect(() => {
    strip.current?.querySelector('.is-active')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [pickedKey, tab])
  useEffect(() => {
    if (!notice) return undefined
    const timer = setTimeout(() => setNotice(''), 1800)
    return () => clearTimeout(timer)
  }, [notice])

  if (!state.subject) return null
  if (!open) return <button type="button" className="workbench-reopen" onClick={() => onOpenChange(true)}
    aria-label="Show what Randall is working on" title="Show what Randall is working on">
    {state.step?.running && <span className="assistant-work-pulse" aria-hidden="true"><i /></span>}
    <span>Workbench</span>
  </button>

  const freshPictures = (state.pictures?.seq || 0) > seenPictures && tab !== 'pictures'
  const tabs = workbenchTabs(state)
  // The tab picked, while it can be opened; else the first that can, else the first (3D: it says it has nothing yet).
  const active = tabs.some(([id, , ready]) => id === tab && ready) ? tab
    : (tabs.find(([, , ready]) => ready) || tabs[0] || [tab])[0]
  const openMenu = picture => event => {
    event.preventDefault(); event.stopPropagation()
    pick(picture.key)
    setMenu({ x: Math.min(event.clientX, window.innerWidth - 200), y: Math.min(event.clientY, window.innerHeight - 140), picture })
  }
  const act = fn => event => { event.stopPropagation(); const picture = menu.picture; setMenu(null); fn(picture) }
  const groups = []
  for (const picture of gallery) {
    const last = groups[groups.length - 1]
    if (last?.id === picture.group.id) last.pictures.push(picture)
    else groups.push({ ...picture.group, pictures: [picture] })
  }

  return <aside className="workbench" aria-label="What Randall is working on">
    <header className="workbench-head">
      <div className="workbench-title">
        <strong>{friendlyTitle(state.subject.title)}</strong>
        {state.step && <span className="workbench-step">
          {state.step.running && <span className="assistant-work-pulse" aria-hidden="true"><i /></span>}
          {state.step.label}</span>}
      </div>
      <button type="button" className="workbench-close" aria-label="Hide the workbench" title="Hide"
        onClick={() => onOpenChange(false)}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>
      </button>
    </header>
    <div className="workbench-tabs" role="tablist">
      {tabs.map(([id, label, ready]) => <button key={id} type="button" role="tab" aria-selected={active === id}
        disabled={!ready} className={active === id ? 'is-active' : ''} onClick={() => setTab(id)}>
        {label}{id === 'pictures' && gallery.length > 0 && <span className="workbench-count">{gallery.length}</span>}
        {id === 'pictures' && freshPictures && <i className="workbench-dot" aria-label="new" />}
      </button>)}
    </div>
    <div className="workbench-body">
      {/* The viewer stays mounted behind the other tabs, and behind the other
          app tabs its renderer stays up, paused, so switching back does not
          reload it (WorkbenchViewer: off screen it keeps an idle view). */}
      {state.model && <div className="workbench-pane" hidden={active !== '3d'}>
        <WorkbenchViewer model={state.model} subject={state.subject?.key || ''} active={visible && active === '3d'} />
      </div>}
      {!state.model && active === '3d' && <div className="workbench-empty"><p>Nothing to show in 3D yet.</p></div>}
      {active === 'pictures' && shown && <div className="workbench-pane workbench-pictures">
        <button type="button" className="workbench-picture" onClick={() => setViewing(true)} onContextMenu={openMenu(shown)}
          title="Open full screen. Right-click to copy; drag onto the message bar to point Randall at it.">
          <img src={pictureUrl(shown)} alt={shown.name} draggable={Boolean(shown.file)} onDragStart={dragPicture(shown)} />
        </button>
        <p className="workbench-caption"><span>{shown.name}</span><span>{shown.group.label} · {index + 1} of {gallery.length}</span></p>
        {gallery.length > 1 && <div className="workbench-gallery" ref={strip}>{groups.map(group =>
          <section key={group.id} className="workbench-group">
            <h4>{group.label}{group.subject ? ` · ${friendlyTitle(group.subject)}` : ''}</h4>
            <div className="workbench-strip">{group.pictures.map(picture =>
              <button key={picture.key} type="button" className={picture === shown ? 'is-active' : ''} title={picture.name}
                onClick={() => pick(picture.key)} onDoubleClick={() => { pick(picture.key); setViewing(true) }}
                onContextMenu={openMenu(picture)}>
                <img src={pictureUrl(picture)} alt={picture.name} loading="lazy" draggable={Boolean(picture.file)}
                  onDragStart={dragPicture(picture)} />
              </button>)}</div>
          </section>)}</div>}
      </div>}
      {active === 'game' && gameTool && <div className="workbench-pane workbench-game">
        <GameTestCard tool={gameTool} chatId={chatId} visible={visible} live layout="workbench" />
      </div>}
    </div>
    {viewing && shown && createPortal(<div className="workbench-zoom" role="dialog" aria-label={shown.name}
      onClick={() => setViewing(false)}>
      <header className="workbench-zoom-bar" onClick={event => event.stopPropagation()}>
        <span className="workbench-zoom-name">{shown.name}</span>
        <span className="workbench-zoom-meta">{shown.group.label} · {index + 1} of {gallery.length}</span>
        <button type="button" onClick={() => setViewing(false)} aria-label="Close" title="Close (Esc)">×</button>
      </header>
      {gallery.length > 1 && <button type="button" className="workbench-zoom-nav is-prev" aria-label="Previous picture"
        title="Previous (←)" onClick={event => { event.stopPropagation(); step(-1) }}>‹</button>}
      <img src={pictureUrl(shown)} alt={shown.name} onClick={event => event.stopPropagation()}
        onContextMenu={openMenu(shown)} draggable={Boolean(shown.file)} onDragStart={dragPicture(shown)} />
      {gallery.length > 1 && <button type="button" className="workbench-zoom-nav is-next" aria-label="Next picture"
        title="Next (→)" onClick={event => { event.stopPropagation(); step(1) }}>›</button>}
    </div>, document.body)}
    {menu && createPortal(<div className="context-menu workbench-menu" style={{ top: menu.y, left: menu.x }}
      onMouseDown={event => event.stopPropagation()} role="menu">
      <button type="button" role="menuitem" onClick={act(picture => copyImage(pictureUrl(picture))
        .then(() => setNotice('Picture copied')).catch(err => setNotice(err.message || 'The picture could not be copied.')))}>Copy image</button>
      {onAttach && menu.picture.file && <button type="button" role="menuitem"
        onClick={act(picture => { onAttach(picture.file); setNotice('Attached to your message') })}>Attach to message</button>}
      {!viewing && <button type="button" role="menuitem" onClick={act(() => setViewing(true))}>Open full screen</button>}
    </div>, document.body)}
    {notice && createPortal(<div className="workbench-notice" role="status">{notice}</div>, document.body)}
  </aside>
}
