// theater — the combo playlist player: queue up the combos you're browsing
// and let them run, one after another, each fetching its game's clip on
// demand (cached per game, and the next clip prefetches while the current
// one plays). Prev/next to skim, share for the one on screen.
import {
  paintFrame, stepCamera, viewFromCam, paintHudCanvas, drawRandall,
} from '../../../app/frontend/src/tracker/replays/litePaint'
import { createRenderer } from '../../../app/frontend/src/tracker/replays/meleeRender'
import { charName, stageName } from '../../../app/frontend/src/shared/data/meleeNames'
import {
  fetchClip, fetchCharmaps, ensurePacks, hudIcons, combosForGame, comboFrame,
} from './api'
import { shareLink } from './share'
import {
  seqLabel, PLAY_ICON, PAUSE_ICON, STEP_BACK_ICON, STEP_FWD_ICON,
  syncSeek, convTimeline, holdRepeat,
} from './detail'
import { paintOverlays } from './overlays'
import {
  getRate, frameAt, anchorFor, skipTarget, playbackRowHtml, wirePlaybackRow,
} from './playback'
import { el, esc } from './ui'

const SHARE_ICON = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 3v13M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg>`

const PRE_ROLL = 30, POST_ROLL = 45

let active = null

export function closeTheater() {
  if (!active) return
  active.playing = false
  if (active.raf) cancelAnimationFrame(active.raf)
  if (active.ac) active.ac.abort()
  if (active.prefetchTimer) clearTimeout(active.prefetchTimer)
  document.body.classList.remove('no-scroll')
  active.root.classList.add('is-leaving')
  const a = active
  active = null
  setTimeout(() => a.root.remove(), 240)
}

export function openTheater(combos, startIdx = 0) {
  if (!combos.length) return
  const root = el(`<div class="detail">
    <div class="dhead frosted">
      <button class="iconbtn" id="t-back" aria-label="Close">‹</button>
      <div class="titles">
        <h2 id="t-title">Combo theater</h2>
        <div class="sub" id="t-sub"></div>
      </div>
      <button class="iconbtn" id="t-share" aria-label="Share combo" disabled>${SHARE_ICON}</button>
    </div>
    <canvas class="dcanvas" style="flex:1 1 auto;height:auto;min-height:0"></canvas>
    <div class="theater-info" id="t-info"></div>
    ${/* Six controls plus a scrubber is the tightest row in the app. The combo
          skips keep the 40px .iconbtn box; the frame steps are the narrower
          34px .stepbtn, and .tgrp closes the gaps between them so the scrubber
          still gets ~110px at 360px wide. */''}
    <div class="transport">
      <div class="tgrp">
        <button class="iconbtn" id="t-prev" aria-label="Previous combo"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M6 5.5v13a1 1 0 0 0 2 0v-13a1 1 0 0 0-2 0zM19.5 6.2v11.6a1 1 0 0 1-1.55.83l-8.5-5.8a1 1 0 0 1 0-1.66l8.5-5.8a1 1 0 0 1 1.55.83z"/></svg></button>
        <button class="iconbtn stepbtn" id="t-step-b" aria-label="Step back one frame">${STEP_BACK_ICON}</button>
        <button class="iconbtn playbtn" id="t-play" aria-label="Pause">${PAUSE_ICON}</button>
        <button class="iconbtn stepbtn" id="t-step-f" aria-label="Step forward one frame">${STEP_FWD_ICON}</button>
        <button class="iconbtn" id="t-next" aria-label="Next combo"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M18 5.5v13a1 1 0 0 1-2 0v-13a1 1 0 0 1 2 0zM4.5 6.2v11.6a1 1 0 0 0 1.55.83l8.5-5.8a1 1 0 0 0 0-1.66l-8.5-5.8a1 1 0 0 0-1.55.83z"/></svg></button>
      </div>
      <input id="t-seek" class="seek" type="range" min="0" max="1" value="0" step="1" aria-label="Scrub">
    </div>
    ${playbackRowHtml('t')}
    <canvas class="convtl" id="t-tl" aria-label="Conversion timeline" hidden></canvas>
    <p class="dstatus" id="t-status" style="padding-bottom:calc(10px + var(--sab))"></p>
  </div>`)
  document.body.appendChild(root)
  document.body.classList.add('no-scroll')

  const s = {
    root, i: startIdx, playing: false, raf: 0, pos: 0, cam: {}, t0: null,
    bundle: null, anim: null, renderer: null, lo: 0, hi: 0, gen: 0,
    ac: new AbortController(), prefetchTimer: 0,
  }
  active = s

  const cv = root.querySelector('.dcanvas')
  const ctx = cv.getContext('2d')
  const seek = root.querySelector('#t-seek')
  const playBtn = root.querySelector('#t-play')
  const status = root.querySelector('#t-status')
  const shareBtn = root.querySelector('#t-share')
  const title = root.querySelector('#t-title')
  const sub = root.querySelector('#t-sub')
  const info = root.querySelector('#t-info')
  const dpr = Math.max(1, window.devicePixelRatio || 1)

  root.querySelector('#t-back').addEventListener('click', closeTheater)

  const size = () => { cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr }

  function draw(idx, snap) {
    stepCamera(s.cam, s.bundle.frames, idx, snap)
    const view = viewFromCam(s.cam, cv.clientWidth, cv.clientHeight)
    paintFrame(ctx, s.bundle, s.anim, s.renderer, idx, view, dpr)
    if (s.bundle.meta.stage === 8) {
      drawRandall(ctx, (s.bundle.meta.start_frame ?? -123) + idx, view, dpr)
    }
    const hudScale = Math.max(1, cv.width / 500)
    paintHudCanvas(ctx, s.bundle, idx, cv.width, cv.height, hudScale, s.icons)
    paintOverlays(ctx, s.bundle, idx, cv.width, cv.height, hudScale, s.icons)
    tl.draw(s.bundle, idx, s.lo, s.hi, s.icons)
  }

  function loop(t) {
    if (!s.playing || active !== s) return
    if (s.t0 == null) s.t0 = anchorFor(t, s.pos, s.lo, getRate())
    const idx = frameAt(t, s.t0, s.lo, getRate())
    if (idx > s.hi) { advance(1); return }   // the playlist part
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
  const tl = convTimeline(root.querySelector('#t-tl'), (frame) => {
    if (!s.bundle) return
    setPlaying(false)
    s.pos = Math.max(s.lo, Math.min(s.hi, frame))
    seek.value = String(s.pos)
    syncSeek(seek)
    draw(s.pos, true)
  })
  root.querySelector('#t-prev').addEventListener('click', () => advance(-1))
  root.querySelector('#t-next').addEventListener('click', () => advance(1))

  // Same contract as detail.js: pause first (the raf loop recomputes pos from
  // wall-clock and would eat the step), clamp to the combo window, and ease the
  // camera by one playback tick rather than snapping it.
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
  holdRepeat(root.querySelector('#t-step-b'), () => step(-1))
  holdRepeat(root.querySelector('#t-step-f'), () => step(1))
  // ±5s within the combo window, and the shared speed setting (#93)
  wirePlaybackRow(root, 't', {
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
  window.addEventListener('keydown', (e) => {
    if (active !== s || !s.bundle) return
    const t = e.target
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
    if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1) }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(1) }
  }, { signal: s.ac.signal })

  function advance(dir) {
    s.i = (s.i + dir + combos.length) % combos.length
    load()
  }

  async function load() {
    const gen = ++s.gen
    const c = combos[s.i]
    const vg = c.vault_games || {}
    setPlaying(false)
    shareBtn.disabled = true
    title.textContent = `${charName(c.character)} vs ${charName(c.opp_character)}`
    sub.textContent = `${s.i + 1} of ${combos.length} · ${stageName(vg.stage)}`
    info.innerHTML = `
      <span class="dcombo-dmg">${Math.round(c.damage || 0)}%</span>
      ${c.true_combo === true ? '<span class="true-badge">TRUE</span>' : ''}
      ${c.did_kill ? '<span class="kill-badge">KILL</span>' : ''}
      <span class="theater-seq">${esc(seqLabel(c.moves) || `${(c.moves || []).length || c.hits || 0} hits`)}</span>`
    status.textContent = 'loading…'
    try {
      const [raw, cm] = await Promise.all([fetchClip(vg.content_hash), fetchCharmaps()])
      if (active !== s || gen !== s.gen) return
      s.bundle = raw.bundle
      s.icons = null
      hudIcons(s.bundle).then((ic) => { if (gen === s.gen) s.icons = ic })
      s.anim = await ensurePacks(s.bundle)
      if (active !== s || gen !== s.gen) return
      const hasAnims = Object.values(s.anim).some((a) => a && Object.keys(a).length)
      s.renderer = (cm && hasAnims) ? createRenderer(cm) : null

      const sf = s.bundle.meta.start_frame ?? -123
      const last = s.bundle.meta.n - 1
      s.lo = Math.max(0, Math.min(last, comboFrame(raw, c.start_frame) - sf - PRE_ROLL))
      s.hi = Math.max(s.lo, Math.min(last, comboFrame(raw, c.end_frame) - sf + POST_ROLL))
      s.pos = s.lo
      s.cam = {}
      seek.min = String(s.lo)
      seek.max = String(s.hi)
      seek.value = String(s.lo)
      size()
      status.textContent = ''
      shareBtn.disabled = false
      draw(s.lo, true)
      setPlaying(true)

      // Prefetch the next combo's game — but not at clip start: the fetch
      // ends in a main-thread gunzip+JSON.parse of a whole-game bundle, a
      // visible hitch. Schedule it for ~2s before this clip ends (min 1s in)
      // so the stall lands at the crossfade where nobody notices.
      const next = combos[(s.i + 1) % combos.length]
      if (next?.vault_games?.content_hash) {
        const clipMs = ((s.hi - s.lo) / 60) * 1000
        if (s.prefetchTimer) clearTimeout(s.prefetchTimer)
        s.prefetchTimer = setTimeout(() => {
          if (active === s && gen === s.gen) {
            fetchClip(next.vault_games.content_hash).catch(() => {})
          }
        }, Math.max(1000, clipMs - 2000))
      }
    } catch (e) {
      if (active !== s || gen !== s.gen) return
      status.textContent = `could not load: ${e.message} — skipping`
      setTimeout(() => { if (active === s && gen === s.gen) advance(1) }, 1200)
    }
  }

  shareBtn.addEventListener('click', async () => {
    const c = combos[s.i]
    const hash = (c?.vault_games || {}).content_hash
    if (!hash) return
    shareBtn.disabled = true
    try {
      // A theater row comes from the global browse query, so it carries no
      // position within its own game -- and /combo/N is exactly that position.
      // Re-reading the game's list is the only way to get the ordinal RIGHT
      // (same filter, same order as the public endpoint); guessing from
      // start_frame would drift the moment a game had a combo the list hides.
      let ordinal = null
      if (c.game_id != null) {
        const all = await combosForGame(c.game_id).catch(() => [])
        const i = all.findIndex((x) => x.id === c.id)
        if (i >= 0) ordinal = i + 1
      }
      await shareLink({
        contentHash: hash,
        combo: ordinal,
        text: `${charName(c.character)} ${Math.round(c.damage || 0)}% combo`
          + `${c.did_kill ? ' (kill)' : ''} vs ${charName(c.opp_character)}`,
      })
    } finally { shareBtn.disabled = false }
  })

  window.addEventListener('resize', () => {
    if (active !== s || !s.bundle) return
    size()
    draw(s.pos, true)
  })

  load()
}
