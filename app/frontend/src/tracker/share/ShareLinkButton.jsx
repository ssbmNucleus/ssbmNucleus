// ShareLinkButton — the desktop end of public replay links. Click mints
// (idempotently, via the backend, which holds the vault token) the permanent
// ssbmnucleus.net URL for a game or combo and copies it (a one-item sheet
// offers Copy link when the clipboard refuses).
// If the game isn't in the cloud vault yet the backend uploads it as part of
// the mint, so the first share of a game is slower than the rest. The unfurl thumbnail is drawn HERE and pushed in the background —
// the same picture the phone draws, for the same reason: the client is the
// one place the stock icons meet a canvas, and a server rendering would
// upscale 24px pixel art into mush.
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../shared/transport/api'
import { P as PORT_COLORS } from '../replays/litePaint'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import ShareNoticeModal, { shareNoticeAcknowledged, acknowledgeShareNotice } from './ShareNoticeModal'
import ShareProblemModal, { shareProblem } from './ShareProblemModal'
import './ShareLinkButton.css'

const API = '/api/nucleome'

// VOD-style thumbnail, mirroring mobile/src/share.js drawThumb: two stock
// icons, "vs", the connect codes. Smoothing off + integer scale keeps the
// pixels square.
const THUMB_W = 1200
const THUMB_H = 630
const ICON_SCALE = 7          // 24px icons -> 168px, integer so pixels stay pixels

// fetch -> blob URL rather than a plain <img> src: the backend is another
// origin, and a cross-origin image TAINTS the canvas — toDataURL then throws
// and the thumbnail silently never uploads. A blob: URL is same-origin.
async function loadImg(url) {
  try {
    const obj = URL.createObjectURL(await api.blob(url))
    try {
      const img = new Image()
      await new Promise((res, rej) => {
        img.onload = res
        img.onerror = rej
        img.src = obj
      })
      return img
    } finally {
      URL.revokeObjectURL(obj)
    }
  } catch { return null }
}

async function drawThumb(players) {
  const ps = (players || []).slice(0, 2)
  if (ps.length < 2) return null
  const imgs = await Promise.all(ps.map((p) =>
    loadImg(`${API}/stock/${p.character}/${p.costume ?? 0}`)))
  if (!imgs[0] && !imgs[1]) return null      // nothing to show — skip, no blank card

  const cv = document.createElement('canvas')
  cv.width = THUMB_W
  cv.height = THUMB_H
  const c = cv.getContext('2d')
  c.fillStyle = '#06150c'
  c.fillRect(0, 0, THUMB_W, THUMB_H)

  const cx = [THUMB_W * 0.3, THUMB_W * 0.7]
  const iconY = 150
  c.imageSmoothingEnabled = false
  imgs.forEach((img, i) => {
    if (!img) return
    const w = (img.naturalWidth || 24) * ICON_SCALE
    const h = (img.naturalHeight || 24) * ICON_SCALE
    c.drawImage(img, cx[i] - w / 2, iconY, w, h)
  })

  c.textAlign = 'center'
  c.fillStyle = '#87958c'
  c.font = "700 60px -apple-system, 'Segoe UI', system-ui, sans-serif"
  c.fillText('vs', THUMB_W / 2, iconY + 108)

  c.font = "700 64px ui-monospace, 'Cascadia Mono', Consolas, monospace"
  ps.forEach((p, i) => {
    c.fillStyle = PORT_COLORS[(p.port ?? i + 1) - 1] || PORT_COLORS[i]
    c.fillText(p.code || p.name || '?', cx[i], iconY + 300)
  })

  // No brand line: the unfurl's own link already says where it goes, and
  // lettering burned into the picture read as ad copy.

  return cv.toDataURL('image/png').split(',')[1]
}

async function pushThumb(id, players) {
  try {
    const b64 = await drawThumb(players)
    if (!b64) return
    await api.post(`${API}/share/thumb`, { id, png_b64: b64 })
  } catch { /* the link is already on the clipboard; the picture is a bonus */ }
}

const ShareIcon = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true"
       stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v13M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" />
  </svg>
)

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" aria-hidden="true"
       stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4.5 12.5l5 5 10-11" />
  </svg>
)

/** Icon chip that shares the game's (or one combo's) public URL. Click mints
 * the link and copies it. Rendered for every row: the mint uploads the game first if it
 * isn't in the vault yet, so "not synced" is no longer a reason to hide this.
 * Combos are the exception — the caller checks `shareable`, because one below
 * the upload length rule can never have a /combo/N page. */
export default function ShareLinkButton({ gameId, comboId = null, players, disabledReason = '', onShared }) {
  const [state, setState] = useState('idle') // idle | notice | busy | menu | copied | failed | problem
  const [error, setError] = useState('')
  const [problem, setProblem] = useState(null) // why the link could not be made (ShareProblemModal)
  const [link, setLink] = useState(null)
  const [menuPos, setMenuPos] = useState(null) // fixed-position anchor
  const timer = useRef(null)
  const boxRef = useRef(null)
  useEffect(() => () => clearTimeout(timer.current), [])

  // Outside click / Escape closes; scrolling RE-ANCHORS the menu to the
  // button (closing on scroll felt broken). If the button leaves the
  // viewport, then we close.
  const menuRef = useRef(null)
  useEffect(() => {
    if (state !== 'menu') return undefined
    const away = (e) => {
      if (boxRef.current?.contains(e.target)) return
      if (menuRef.current?.contains(e.target)) return
      setState('idle')
    }
    const esc = (e) => { if (e.key === 'Escape') setState('idle') }
    let raf = null
    const scroll = () => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = null
        const rect = boxRef.current?.getBoundingClientRect()
        if (!rect || rect.bottom < 0 || rect.top > window.innerHeight) { setState('idle'); return }
        setMenuPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right })
      })
    }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    document.addEventListener('scroll', scroll, true)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', esc)
      document.removeEventListener('scroll', scroll, true)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [state])

  const finish = (s) => {
    setState(s)
    timer.current = setTimeout(() => setState('idle'), 1800)
  }

  const open = async () => {
    if (disabledReason) return
    if (state === 'busy' || state === 'notice' || state === 'problem') return
    if (state === 'menu') { setState('idle'); return }
    playSound('boop')
    // Sharing is free and ungated, but it does put the replay on the public
    // internet, so say so once before the first link this install ever mints.
    if (!shareNoticeAcknowledged()) { setState('notice'); return }
    await mint()
  }

  const confirmNotice = () => {
    acknowledgeShareNotice()
    mint()
  }

  const mint = async () => {
    setState('busy')
    try {
      const body = await api.post(`${API}/share`, { game_id: gameId, combo_id: comboId })
      // Before anything else, deliberately: the link exists as soon as the
      // mint returns, so its unfurl picture should too. Not awaited; it can
      // finish or fail on its own time.
      pushThumb(body.id, players)
      try {
        await navigator.clipboard.writeText(body.url)
        finish('copied')
        return
      } catch { /* clipboard refused: the sheet below offers Copy link */ }
      setLink(body.url)
      onShared?.(body.url)
      const rect = boxRef.current?.getBoundingClientRect()
      setMenuPos(rect ? { top: rect.bottom + 4, right: window.innerWidth - rect.right } : null)
      setState('menu')
    } catch (e) {
      // A dialog, not a tooltip: the reason is usually one click from fixed
      // (link Patreon, join free), and the raw message can be vault JSON.
      setProblem(shareProblem(e.message, e.status, comboId != null ? 'combo' : 'game'))
      setState('problem')
    }
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link)
      playSound('boop')
      finish('copied')
    } catch { finish('failed') }
  }

  const what = comboId != null ? 'combo' : 'game'
  const title = disabledReason || (state === 'failed' ? `Share failed: ${error}`
    : state === 'copied' ? 'Link copied'
      : `Share this ${what}`)
  return (
    <span className="share-link-wrap" ref={boxRef}>
      <button
        type="button"
        className={`share-link-btn ${state === 'copied' ? 'is-copied' : ''} ${state === 'failed' ? 'is-failed' : ''}`}
        title={title}
        aria-label={title}
        aria-expanded={state === 'menu'}
        disabled={state === 'busy' || !!disabledReason}
        onMouseEnter={playHoverSound}
        onClick={open}
      >
        {state === 'copied' ? <CheckIcon /> : state === 'failed' ? '✕' : <ShareIcon />}
      </button>
      {state === 'notice' && (
        <ShareNoticeModal onConfirm={confirmNotice} onCancel={() => setState('idle')} />
      )}
      {state === 'problem' && problem && (
        <ShareProblemModal problem={problem} onClose={() => setState('idle')} onRetry={mint} />
      )}
      {state === 'menu' && createPortal(
        <div className="share-menu" role="menu" ref={menuRef}
          style={{ position: 'fixed', top: menuPos?.top ?? 80, right: menuPos?.right ?? 16 }}>
          <button type="button" className="share-menu-item" role="menuitem" onClick={copy} onMouseEnter={playHoverSound}>
            Copy link
          </button>
        </div>,
        document.body
      )}
    </span>
  )
}
