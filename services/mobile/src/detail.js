// detail — the game page: a slide-up overlay with the Watch Lite player stuck
// to the top (it keeps playing while you browse) and, below it, the matchup
// summary and every combo in the game. Tap a combo to loop its window; share
// the whole game or one combo as a self-contained artifact.
import {
  paintFrame, stepCamera, viewFromCam, paintHudCanvas, drawRandall, pcolor,
} from '../../../app/frontend/src/tracker/replays/litePaint'
import { createRenderer } from '../../../app/frontend/src/tracker/replays/meleeRender'
import { charName, stageName, formatDuration, moveName } from '../../../app/frontend/src/shared/data/meleeNames'
import {
  fetchClip, fetchCharmaps, ensurePacks, combosForGame, hudIcons,
  cachedRank, fetchRanks, comboFrame,
} from './api'
import { paintOverlays, overlaysSheet } from './overlays'
import { shareLink } from './share'
import { matchCard } from './matchcard'
import {
  getRate, frameAt, anchorFor, skipTarget, playbackRowHtml, wirePlaybackRow,
} from './playback'
import { el, esc, stockSrc, stockFallback, stageSrc, shortDate, num } from './ui'

const SHARE_ICON = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 3v13M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg>`

// Real icons, not text glyphs — ⏸/▶ render as emoji on iOS and read as slop.
export const PLAY_ICON = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
  <path d="M8 5.5v13a1 1 0 0 0 1.54.84l10-6.5a1 1 0 0 0 0-1.68l-10-6.5A1 1 0 0 0 8 5.5z"/></svg>`
export const PAUSE_ICON = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
  <rect x="6" y="5" width="4.4" height="14" rx="1.4"/>
  <rect x="13.6" y="5" width="4.4" height="14" rx="1.4"/></svg>`
// Frame step: the bar-and-triangle everyone already reads as "step". Drawn at
// roughly 2/3 the height of the theater's prev/next skip glyphs, which are the
// same silhouette — in the theater row all four sit side by side, and at full
// size the only thing telling them apart was the button background. Smaller and
// lighter also happens to be the honest reading: a smaller jump.
export const STEP_BACK_ICON = `<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
  <rect x="5.8" y="7" width="2.2" height="10" rx="1"/>
  <path d="M17 7.4v9.2a1 1 0 0 1-1.55.83l-6.9-4.6a1 1 0 0 1 0-1.66l6.9-4.6A1 1 0 0 1 17 7.4z"/></svg>`
export const STEP_FWD_ICON = `<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
  <path d="M7 7.4v9.2a1 1 0 0 0 1.55.83l6.9-4.6a1 1 0 0 0 0-1.66l-6.9-4.6A1 1 0 0 0 7 7.4z"/>
  <rect x="16" y="7" width="2.2" height="10" rx="1"/></svg>`

// Tap fires once; hold repeats. Notes on the shape of this, all load-bearing:
//   · activation is pointerdown, not click, so the repeat can start before the
//     finger lifts — which also means there must be NO click listener or every
//     tap would step twice;
//   · keyboard activation is therefore handled explicitly, and preventDefault
//     on the keydown suppresses the synthetic click that would double-step;
//   · the release listeners live on `window`: a finger that slides off a 34px
//     button before lifting never delivers pointerup to the button, and the
//     repeat would run forever.
const HOLD_DELAY = 400, HOLD_RATE = 1000 / 12

export function holdRepeat(btn, fire) {
  let delay = 0, timer = 0
  const stop = () => {
    clearTimeout(delay); clearInterval(timer); delay = 0; timer = 0
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
  }
  btn.addEventListener('pointerdown', (e) => {
    if (e.button > 0) return
    e.preventDefault()          // no focus ring drag, no text selection, no 300ms tap
    stop()
    fire()
    delay = setTimeout(() => { timer = setInterval(fire, HOLD_RATE) }, HOLD_DELAY)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
  })
  btn.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return
    e.preventDefault()
    fire()
  })
}

// keep the slider's filled portion in sync (CSS paints up to --p)
export function syncSeek(seek) {
  const min = Number(seek.min) || 0
  const max = Number(seek.max) || 1
  const p = max > min ? ((Number(seek.value) - min) / (max - min)) * 100 : 0
  seek.style.setProperty('--p', `${p}%`)
}

const PRE_ROLL = 30, POST_ROLL = 45

// ── conversion timeline ───────────────────────────────────────────────────────
// The desktop strip (WatchLiteClip.jsx drawTimeline): one lane per player, each
// conversion a block coloured by how it ended, half-lit when the detector only
// inferred it. Two departures the phone forces:
//   · it spans the CURRENT playback window, not the whole clip, so it stays in
//     register with the scrubber sitting directly above it (picking a combo
//     shrinks both together);
//   · seeking runs on pointer events with capture, because a finger dragging a
//     26px strip leaves it constantly and mouse-style listeners would drop the
//     drag the moment it did.
const TERM = { stock_drop: '#ffcc45', reversal: '#a78bfa', timeout: '#5b6478', game_end: '#3a3f52' }
const TERM_OTHER = '#4b5568'
const LANE_BG = ['rgba(255,255,255,.055)', 'rgba(255,255,255,.03)']
const PLAYHEAD = '#38e07c'   // --accent; canvas can't read the token

function rr(c, x, y, w, h, r) {
  if (c.roundRect) { c.beginPath(); c.roundRect(x, y, w, h, r); c.fill() }
  else c.fillRect(x, y, w, h)
}

/** Wire a `.convtl` canvas. `onSeek(frame)` gets a window-relative frame index.
 * Returns { draw(bundle, idx, lo, hi, icons) } — call it from the player's own
 * draw so the playhead tracks playback. */
export function convTimeline(cv, onSeek) {
  const ctx = cv.getContext('2d')
  const dpr = Math.max(1, window.devicePixelRatio || 1)
  let cur = null    // window/bundle the lanes were baked for
  let base = null   // baked lanes; only the playhead is repainted per frame

  const seekFrom = (clientX) => {
    if (!cur) return
    const r = cv.getBoundingClientRect()
    const t = Math.min(1, Math.max(0, (clientX - r.left) / (r.width || 1)))
    onSeek(Math.round(cur.lo + t * (cur.hi - cur.lo)))
  }
  cv.addEventListener('pointerdown', (e) => {
    if (cv.setPointerCapture) cv.setPointerCapture(e.pointerId)
    seekFrom(e.clientX)
  })
  cv.addEventListener('pointermove', (e) => {
    if (cv.hasPointerCapture && cv.hasPointerCapture(e.pointerId)) seekFrom(e.clientX)
  })

  function bake(bundle, lo, hi, icons) {
    const w = cv.clientWidth, h = cv.clientHeight
    if (!w || !h) return false           // laid out inside a hidden panel
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr)
    if (!base) base = document.createElement('canvas')
    base.width = cv.width; base.height = cv.height
    const b = base.getContext('2d')
    b.setTransform(dpr, 0, 0, dpr, 0, 0)
    b.clearRect(0, 0, w, h)
    const sf0 = bundle.meta.start_frame ?? -123
    const span = Math.max(1, hi - lo)
    const fx = (sf) => ((sf - sf0 - lo) / span) * w
    const laneH = (h - 3) / 2
    for (const a of ['0', '1']) {
      const top = a === '0' ? 1 : 2 + laneH
      b.fillStyle = LANE_BG[+a]
      rr(b, 0, top, w, laneH, 3)
      for (const c of (bundle.conversions[a] || [])) {
        const x0 = Math.max(0, fx(c.start_frame))
        const x1 = Math.min(w, Math.max(fx(c.start_frame) + 2, fx(c.end_frame)))
        if (x1 <= 0 || x0 >= w) continue
        b.fillStyle = TERM[(c.evidence || {}).termination] || TERM_OTHER
        b.globalAlpha = c.certainty === 'inferred' ? 0.5 : 0.95
        rr(b, x0, top + 1, Math.max(2, x1 - x0), laneH - 2, 2)
        b.globalAlpha = 1
      }
      // lane label: the player's stock icon, a colour dot until it loads
      const im = icons && icons[+a]
      if (im && im.complete !== false && (im.naturalWidth == null || im.naturalWidth)) {
        b.drawImage(im, 3, top + 1, laneH - 2, laneH - 2)
      } else {
        b.fillStyle = pcolor(bundle, +a)
        b.beginPath(); b.arc(3 + laneH / 2, top + laneH / 2, Math.max(2, laneH / 2 - 3), 0, 7); b.fill()
      }
    }
    return true
  }

  return {
    draw(bundle, idx, lo, hi, icons) {
      // 1v1 notion, and v1 bundles have no detector output at all — in both
      // cases the strip removes itself rather than drawing empty furniture
      const convs = bundle && bundle.conversions
      const on = !!(convs && bundle.meta.players.length === 2
        && ((convs['0'] || []).length + (convs['1'] || []).length))
      cv.hidden = !on
      if (!on) { cur = null; return }
      if (!cur || cur.bundle !== bundle || cur.lo !== lo || cur.hi !== hi
          || cur.icons !== icons || cur.w !== cv.clientWidth || cur.h !== cv.clientHeight) {
        if (!bake(bundle, lo, hi, icons)) return
        cur = { bundle, lo, hi, icons, w: cv.clientWidth, h: cv.clientHeight }
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, cv.width, cv.height)
      ctx.drawImage(base, 0, 0)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const px = Math.min(cur.w - 1, Math.max(1,
        ((idx - lo) / Math.max(1, hi - lo)) * cur.w))
      ctx.strokeStyle = PLAYHEAD; ctx.lineWidth = 1.5
      ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, cur.h); ctx.stroke()
    },
  }
}

let active = null

export function closeDetail(animated = true) {
  if (!active) return
  const a = active
  active = null
  a.playing = false
  if (a.raf) cancelAnimationFrame(a.raf)
  if (a.ac) a.ac.abort()
  document.body.classList.remove('no-scroll')
  if (animated) {
    a.root.classList.add('is-leaving')
    setTimeout(() => a.root.remove(), 240)
  } else {
    a.root.remove()
  }
}

// "U-Tilt → U-Tilt → Fair ×2" — the desktop card's sequence line
export function seqLabel(moves) {
  return (moves || [])
    .map((m) => moveName(m.move_id) + (m.hits > 1 ? ` ×${m.hits}` : ''))
    .join(' → ')
}

function frameLabel(startFrame, metaStartFrame) {
  const sec = Math.max(0, (startFrame - metaStartFrame) / 60)
  const m = Math.floor(sec / 60)
  const ss = Math.floor(sec % 60)
  return `${m}:${String(ss).padStart(2, '0')}`
}

export function openDetail(g, opts = {}) {
  closeDetail(false)
  // The permanent per-game snapshot wins over the live cache: an old replay
  // shows the rank they WERE, and a stamped game never needs Slippi again.
  const snap = g.ranks || {}
  const rankOf = (code) => snap[String(code || '').toUpperCase()] || cachedRank(code)
  const me = g.user_port != null ? (g.players || []).find((p) => p.port === g.user_port) : (g.players || [])[0]
  const op = g.user_port != null ? (g.players || []).find((p) => p.port !== g.user_port) : (g.players || [])[1]
  const title = `${charName(me?.character)} vs ${charName(op?.character)}`

  const root = el(`<div class="detail">
    <div class="dhead frosted">
      <button class="iconbtn" id="d-back" aria-label="Back">‹</button>
      <div class="titles">${matchCard(g, rankOf)}</div>
      <button class="iconbtn" id="d-share" aria-label="Share game" disabled>${SHARE_ICON}</button>
    </div>
    <div class="dscroll">
      <div class="dplayer">
        <canvas class="dcanvas"></canvas>
        ${/* These used to float over the top-right corner, directly on top of
              player two's name, percent and stocks. The transport is inside
              the player, so it survives fullscreen and collides with nothing. */''}
        <div class="transport">
          ${/* The three frame controls are one group so the pair hugs play/pause
                instead of spreading on the row's gap — at 360px the scrubber
                needs every pixel the buttons don't take. */''}
          <div class="tgrp">
            <button class="iconbtn stepbtn" id="d-step-b" aria-label="Step back one frame">${STEP_BACK_ICON}</button>
            <button class="iconbtn playbtn" id="d-play" aria-label="Pause">${PAUSE_ICON}</button>
            <button class="iconbtn stepbtn" id="d-step-f" aria-label="Step forward one frame">${STEP_FWD_ICON}</button>
          </div>
          <input id="d-seek" class="seek" type="range" min="0" max="1" value="0" step="1" aria-label="Scrub">
          <button class="iconbtn fsbtn" id="d-hud" aria-label="Overlays"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 8h10M18 8h2M4 16h4M12 16h8"/><circle cx="16" cy="8" r="2"/><circle cx="10" cy="16" r="2"/></svg></button>
          <button class="iconbtn fsbtn" id="d-full" aria-label="Fullscreen"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3"/></svg></button>
        </div>
        ${playbackRowHtml('d')}
        ${/* Under the scrubber and INSIDE .dplayer, so the fullscreen takeover
              carries it along with the transport. */''}
        <canvas class="convtl" id="d-tl" aria-label="Conversion timeline" hidden></canvas>
        <div class="dwindow" id="d-window" hidden>
          <span id="d-window-label"></span>
          <button class="linkish" id="d-window-clear">Watch full game</button>
        </div>
        <p class="dstatus" id="d-status">loading clip…</p>
      </div>
      <div class="dbody">
        <div class="dcombos section">
          <header class="section-head"><h3>Combos in this game</h3><span id="d-combo-count"></span></header>
          <div class="dcombo-list"><p class="spin">loading…</p></div>
        </div>
        <div style="height: 32px"></div>
      </div>
    </div>
  </div>`)
  document.body.appendChild(root)
  document.body.classList.add('no-scroll')

  // ranks arrive after the header renders; redraw it once they do
  const codes = (g.players || []).map((p) => p.code).filter(Boolean)
  if (codes.length) {
    fetchRanks(codes).then((grew) => {
      if (grew && active === s) {
        root.querySelector('.titles').innerHTML = matchCard(g, rankOf)
      }
    }).catch(() => {})
  }

  const s = {
    root, playing: false, raf: 0, pos: 0, cam: {}, t0: null,
    bundle: null, anim: null, renderer: null, lo: 0, hi: 0, n: 1,
    // every window listener this sheet adds hangs off this signal — without
    // it each open pinned its whole state (bundle, renderer) forever
    ac: new AbortController(),
  }
  active = s

  const cv = root.querySelector('.dcanvas')
  const ctx = cv.getContext('2d')
  const seek = root.querySelector('#d-seek')
  const playBtn = root.querySelector('#d-play')
  const status = root.querySelector('#d-status')
  const shareBtn = root.querySelector('#d-share')
  const windowBar = root.querySelector('#d-window')
  const windowLabel = root.querySelector('#d-window-label')
  const dpr = Math.max(1, window.devicePixelRatio || 1)

  root.querySelector('#d-back').addEventListener('click', () => closeDetail())

  const size = () => { cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr }

  // Fullscreen: a CSS takeover (works everywhere, rotates with the phone for
  // real landscape viewing) + the native Fullscreen API where it exists.
  const player = root.querySelector('.dplayer')
  const fsBtn = root.querySelector('#d-full')
  const setFull = (on) => {
    player.classList.toggle('is-full', on)
    if (on && player.requestFullscreen) player.requestFullscreen().catch(() => {})
    else if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {})
    requestAnimationFrame(() => { size(); if (s.bundle) draw(s.pos, true) })
  }
  fsBtn.addEventListener('click', () => setFull(!player.classList.contains('is-full')))
  root.querySelector('#d-hud').addEventListener('click', () => {
    overlaysSheet(() => { if (s.bundle) draw(s.pos, true) })
  })
  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && player.classList.contains('is-full')) setFull(false)
  })

  function draw(idx, snap) {
    stepCamera(s.cam, s.bundle.frames, idx, snap)
    const view = viewFromCam(s.cam, cv.clientWidth, cv.clientHeight)
    paintFrame(ctx, s.bundle, s.anim, s.renderer, idx, view, dpr)
    // Yoshi's Story: Randall rides his platform, mascot duties intact
    if (s.bundle.meta.stage === 8) {
      drawRandall(ctx, (s.bundle.meta.start_frame ?? -123) + idx, view, dpr)
    }
    // HUD scaled to the canvas — the export-tuned default is unreadable at 3x
    const hudScale = Math.max(1, cv.width / 500)
    paintHudCanvas(ctx, s.bundle, idx, cv.width, cv.height, hudScale, s.icons)
    paintOverlays(ctx, s.bundle, idx, cv.width, cv.height, hudScale, s.icons)
    tl.draw(s.bundle, idx, s.lo, s.hi, s.icons)
  }

  function loop(t) {
    if (!s.playing || active !== s) return
    if (s.t0 == null) s.t0 = anchorFor(t, s.pos, s.lo, getRate())
    let idx = frameAt(t, s.t0, s.lo, getRate())
    if (idx > s.hi) { idx = s.lo; s.t0 = t }
    if (idx !== s.pos) {
      s.pos = idx
      seek.value = String(idx)
      syncSeek(seek)
      draw(idx, false)
    }
    s.raf = requestAnimationFrame(loop)
  }
  const setPlaying = (on) => {
    s.playing = on
    s.t0 = null
    playBtn.innerHTML = on ? PAUSE_ICON : PLAY_ICON
    if (on) s.raf = requestAnimationFrame(loop)
    else if (s.raf) cancelAnimationFrame(s.raf)
  }
  playBtn.addEventListener('click', () => setPlaying(!s.playing))
  seek.addEventListener('input', () => {
    setPlaying(false)
    s.pos = Number(seek.value)
    syncSeek(seek)
    draw(s.pos, true)
  })

  // One frame at a time. Stepping stops playback first — the raf loop derives
  // pos from wall-clock, so a step taken while running would be overwritten on
  // the next tick. Clamped to the window because the scrubber and the timeline
  // are both drawn in window coordinates. snap=false, not true: the camera then
  // advances by exactly the same easing tick playback would have applied, so
  // holding step looks like slow motion rather than a series of jump cuts.
  function step(d) {
    if (active !== s || !s.bundle) return
    if (s.playing) setPlaying(false)
    const next = Math.max(s.lo, Math.min(s.hi, s.pos + d))
    if (next === s.pos) return
    s.pos = next
    seek.value = String(next)
    syncSeek(seek)
    draw(next, false)
  }
  holdRepeat(root.querySelector('#d-step-b'), () => step(-1))
  holdRepeat(root.querySelector('#d-step-f'), () => step(1))
  // ±5s and speed (#93). Unlike a frame step, a skip keeps playing — that is
  // what "back 5 seconds" means in every video app. Clearing t0 re-anchors the
  // wall-clock loop on the new frame (and on a new rate) at its next tick.
  wirePlaybackRow(root, 'd', {
    onSkip(dir) {
      if (active !== s || !s.bundle) return
      s.pos = skipTarget(s.pos, dir, s.lo, s.hi)
      s.t0 = null
      seek.value = String(s.pos)
      syncSeek(seek)
      draw(s.pos, true)
    },
    onRate() { s.t0 = null },
  })
  // Arrow keys, for anyone on a keyboard. The seek input handles its own arrows
  // (and already moves one frame per press), so it is left alone.
  window.addEventListener('keydown', (e) => {
    if (active !== s || !s.bundle) return
    const t = e.target
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
    if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1) }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(1) }
  }, { signal: s.ac.signal })

  const tl = convTimeline(root.querySelector('#d-tl'), (frame) => {
    if (!s.bundle) return
    setPlaying(false)
    s.pos = Math.max(s.lo, Math.min(s.hi, frame))
    seek.value = String(s.pos)
    syncSeek(seek)
    draw(s.pos, true)
  })

  function setWindow(lo, hi, label) {
    s.lo = Math.max(0, Math.min(s.n - 1, lo))
    s.hi = Math.max(s.lo, Math.min(s.n - 1, hi))
    seek.min = String(s.lo)
    seek.max = String(s.hi)
    s.pos = s.lo
    seek.value = String(s.lo)
    syncSeek(seek)
    windowBar.hidden = !label
    if (label) windowLabel.textContent = label
    if (s.bundle) { draw(s.lo, true); setPlaying(true) }
  }
  root.querySelector('#d-window-clear').addEventListener('click', () => {
    root.querySelectorAll('.dcombo-cell.is-active').forEach((r) => r.classList.remove('is-active'))
    setWindow(0, s.n - 1, null)
  })

  // ── combos list ──
  const comboHost = root.querySelector('.dcombo-list')
  const countEl = root.querySelector('#d-combo-count')
  let combos = []

  function windowFor(c) {
    const sf = s.bundle?.meta?.start_frame ?? -123
    return [comboFrame(s.clip, c.start_frame) - sf - PRE_ROLL,
      comboFrame(s.clip, c.end_frame) - sf + POST_ROLL]
  }

  function drawCombos() {
    if (!combos.length) {
      comboHost.innerHTML = '<p class="footnote">No combos detected in this game.</p>'
      countEl.textContent = ''
      return
    }
    countEl.textContent = `${num(combos.length)}`
    const sf = s.bundle?.meta?.start_frame ?? -123

    // One column per player. A single stacked list gave no clue who did which
    // combo — the row said "43%" and the mover was whoever you assumed — and
    // the move sequence that was supposed to disambiguate it was ellipsised
    // after four moves anyway. Two columns answer "whose?" by position, so the
    // row itself only has to carry when, how much, and how far.
    const players = (g.players || []).slice(0, 2)
    const cell = (c, i) => `
      <button class="dcombo-cell ${opts.focusStartFrame === c.start_frame && (opts.focusPort == null || opts.focusPort === c.port) ? 'is-active' : ''}" data-i="${i}">
        <span class="dcombo-top">
          <span class="dcombo-dmg">${Math.round(c.damage || 0)}%</span>
          <span class="dcombo-time">${frameLabel(comboFrame(s.clip, c.start_frame), sf)}</span>
        </span>
        <span class="dcombo-sub">
          ${c.start_percent != null
            ? `${Math.round(c.start_percent)}→${Math.round(c.end_percent)}%`
            : `${(c.moves || []).length || c.hits || 0} hits`}
          <span class="dot">·</span>${(c.moves || []).length || c.hits || 0} moves
        </span>
        ${c.true_combo === true || c.did_kill ? `<span class="dcombo-badges">
          ${c.true_combo === true ? '<span class="true-badge">TRUE</span>' : ''}
          ${c.did_kill ? '<span class="kill-badge">KILL</span>' : ''}
        </span>` : ''}
        <span class="dcombo-share" data-share="${i}" role="button" aria-label="Share combo">${SHARE_ICON}</span>
      </button>`

    if (players.length !== 2) {           // doubles, or a game with no roster
      comboHost.innerHTML = `<div class="dcombo-col">${combos.map(cell).join('')}</div>`
      return
    }
    comboHost.innerHTML = `<div class="dcombo-cols">${players.map((p) => {
      const mine = combos.map((c, i) => [c, i]).filter(([c]) => c.port === p.port)
      return `<div class="dcombo-col">
        <div class="dcombo-colhead">
          <img src="${stockSrc(p.character, p.costume)}" alt=""
               onerror="${stockFallback(p.character)}">
          <span>${esc(p.name || p.code || charName(p.character))}</span>
          <b>${mine.length}</b>
        </div>
        ${mine.length
          ? mine.map(([c, i]) => cell(c, i)).join('')
          : '<p class="footnote dcombo-none">none</p>'}
      </div>`
    }).join('')}</div>`
  }
  comboHost.addEventListener('click', async (e) => {
    const shareEl = e.target.closest('.dcombo-share')
    if (shareEl) {
      const i = Number(shareEl.dataset.share)
      const c = combos[i]
      if (!c) return
      shareEl.disabled = true
      try {
        // The ordinal is 1-based and indexes `combos`, which is ordered by
        // start_frame -- the same order and the same 4-move filter the public
        // endpoint applies, so /combo/N opens the clip that was shared.
        await shareLink({
          contentHash: g.content_hash,
          game: g,
          combo: i + 1,
          text: `${charName(c.character)} ${Math.round(c.damage || 0)}% combo`
            + `${c.did_kill ? ' (kill)' : ''} — ${title}`,
        })
      } finally { shareEl.disabled = false }
      return
    }
    const row = e.target.closest('.dcombo-cell')
    if (!row || !s.bundle) return
    comboHost.querySelectorAll('.is-active').forEach((r) => r.classList.remove('is-active'))
    row.classList.add('is-active')
    const c = combos[Number(row.dataset.i)]
    const [lo, hi] = windowFor(c)
    setWindow(lo, hi, `Combo · ${Math.round(c.damage || 0)}% · ${frameLabel(comboFrame(s.clip, c.start_frame), s.bundle.meta.start_frame ?? -123)}`)
  })

  shareBtn.addEventListener('click', async () => {
    shareBtn.disabled = true
    try {
      await shareLink({
        contentHash: g.content_hash,
        game: g,
        text: `${title} — ${stageName(g.stage)}, ${shortDate(g.start_at)}`,
      })
    } finally { shareBtn.disabled = false }
  })

  // ── load everything ──
  Promise.all([
    fetchClip(g.content_hash),
    fetchCharmaps(),
    g.id != null ? combosForGame(g.id).catch(() => []) : Promise.resolve([]),
  ]).then(async ([raw, cm, gameCombos]) => {
    if (active !== s) return
    s.clip = raw
    s.bundle = raw.bundle
    s.n = s.bundle.meta.n
    // A clip synced before the v2 deriver carries no item tracks and no stage
    // state, so it plays with no projectiles, FoD platforms parked at rest and
    // Stadium never transforming — and looked identical to a complete one. The
    // desktop never shows this because it re-derives from the .slp on every
    // request; the phone plays whatever blob was uploaded, so it has to say so.
    s.stale = (s.bundle.meta.v || 1) < 2
    hudIcons(s.bundle).then((ic) => { s.icons = ic })
    status.textContent = 'loading characters…'
    s.anim = await ensurePacks(s.bundle)
    if (active !== s) return
    const hasAnims = Object.values(s.anim).some((a) => a && Object.keys(a).length)
    s.renderer = (cm && hasAnims) ? createRenderer(cm) : null

    combos = gameCombos
    drawCombos()

    size()
    status.textContent = !s.renderer
      ? 'no character art for this clip — dots mode'
      : (s.stale ? 'synced before projectile tracking — re-sync from the desktop to add lasers and stage motion' : '')
    shareBtn.disabled = false

    if (opts.focusStartFrame != null) {
      // port too: a trade puts both players' combos on the same start frame,
      // and matching by frame alone could take the other side's end/damage
      const c = combos.find((x) => x.start_frame === opts.focusStartFrame
          && (opts.focusPort == null || x.port === opts.focusPort))
        || { start_frame: opts.focusStartFrame, end_frame: opts.focusEndFrame ?? opts.focusStartFrame + 300, damage: opts.focusDamage }
      const [lo, hi] = windowFor(c)
      setWindow(lo, hi, `Combo · ${Math.round(c.damage || 0)}%`)
    } else {
      setWindow(0, s.n - 1, null)
    }
  }).catch((e) => {
    if (active === s) status.textContent = `could not load clip: ${e.message}`
  })

  window.addEventListener('resize', () => {
    if (active !== s || !s.bundle) return
    size()
    draw(s.pos, true)
  }, { signal: s.ac.signal })
}
