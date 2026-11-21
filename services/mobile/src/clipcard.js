// clipcard — the replay clip that lives inside a Randall chat bubble: a
// thumbnail-sized 16:9 stage that autoplays one combo window on loop with the
// title beneath it. The desktop's WatchLiteClip (CoachPage reel) is the model.
//
// A transcript can hold dozens of these, and each one is a multi-MB clip fetch
// plus an animation pack, so this version is deliberately stingier than the
// desktop's: nothing is fetched until the card is near the viewport, and the
// rAF loop only runs while the card is actually on screen with the screen on.
// No HUD, no seek bar, no play/pause chrome — the tap target is the whole
// stage and it hands off to the full player.
import {
  paintFrame, stepCamera, viewFromCam, drawRandall,
} from '../../../app/frontend/src/tracker/replays/litePaint'
import { createRenderer } from '../../../app/frontend/src/tracker/replays/meleeRender'
import { fetchClip, fetchCharmaps, ensurePacks, comboFrame } from './api'
import { el, esc } from './ui'

// same context padding the detail page and theater give a combo window
const PRE_ROLL = 30, POST_ROLL = 45

// One visibilitychange listener for every card alive, not one per card:
// randall.js re-renders a thread by replacing innerHTML, which never calls back
// into us, so per-card listeners would pile up on nodes that are already gone.
// Cards that left the document are dropped the next time the screen toggles.
const live = new Set()
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    for (const c of live) {
      if (!c.root.isConnected) { c.destroy(); continue }
      c.sync()
    }
  })
}

/**
 * clipCard({contentHash, lo, hi, title, onExpand}) -> HTMLElement
 *
 * `lo`/`hi` are clip-relative frame indices (what detail.js calls s.lo/s.hi).
 * When the caller only has slippi frame numbers — chips carry combo
 * start_frame/end_frame, and the bundle's start_frame isn't known until the
 * fetch lands — pass `startFrame`/`endFrame` instead and the window is
 * resolved (with pre/post-roll) once the bundle arrives.
 *
 * The returned element carries a `destroy()` for callers that tear down a
 * thread explicitly; forgetting it is safe, the observers stop the loop when
 * the node leaves the document.
 */
export function clipCard({
  contentHash, lo, hi, startFrame, endFrame, title, onExpand,
}) {
  const label = title || 'Replay clip'
  const root = el(`<div class="cc">
    <div class="cc-stage" role="button" tabindex="0"
         aria-label="${esc(label)} — open the full player">
      <canvas class="cc-canvas"></canvas>
      <div class="cc-note">rendering…</div>
    </div>
    <div class="cc-title">${esc(label)}</div>
  </div>`)

  const stage = root.querySelector('.cc-stage')
  const cv = root.querySelector('.cc-canvas')
  const note = root.querySelector('.cc-note')
  const ctx = cv.getContext('2d')

  const s = {
    root, playing: false, visible: false, dead: false, loading: false, loaded: false,
    raf: 0, t0: null, pos: 0, cam: {}, lo: 0, hi: 0,
    bundle: null, anim: null, renderer: null,
  }
  let loadObs = null, visObs = null, ro = null

  // Thumbnails cap at 2x: a modern phone reports dpr 3, and painting a chat
  // full of 3x canvases costs three times the fill rate for detail nobody can
  // see at this size.
  const dprOf = () => Math.min(2, Math.max(1, window.devicePixelRatio || 1))

  function size() {
    if (!cv.clientWidth) return false
    const dpr = dprOf()
    const w = Math.round(cv.clientWidth * dpr)
    const h = Math.round(cv.clientHeight * dpr)
    if (cv.width === w && cv.height === h) return true
    cv.width = w
    cv.height = h
    return true
  }

  function draw(idx, snap) {
    if (!s.bundle || !cv.clientWidth) return
    const dpr = dprOf()
    stepCamera(s.cam, s.bundle.frames, idx, snap)
    const view = viewFromCam(s.cam, cv.clientWidth, cv.clientHeight)
    // one bad frame must never take out the transcript around it
    try {
      paintFrame(ctx, s.bundle, s.anim, s.renderer, idx, view, dpr)
      if (s.bundle.meta.stage === 8) {
        drawRandall(ctx, (s.bundle.meta.start_frame ?? -123) + idx, view, dpr)
      }
    } catch { /* keep playing */ }
  }

  // Time-based stepping, same as detail.js: rAF runs at the display's refresh
  // rate (120 Hz on recent phones) so "one frame per rAF" would play at double
  // speed there. Deriving the index from wall clock also means a pause of any
  // length resumes without a jump — s.t0 is simply recomputed.
  function loop(t) {
    if (!s.playing) return
    if (s.t0 == null) s.t0 = t - ((s.pos - s.lo) / 60) * 1000
    let idx = s.lo + Math.floor(((t - s.t0) / 1000) * 60)
    if (idx > s.hi) { idx = s.lo; s.t0 = t }
    if (idx !== s.pos) {
      s.pos = idx
      draw(idx, false)
    }
    s.raf = requestAnimationFrame(loop)
  }

  // The only place playback starts or stops: offscreen cards and a locked
  // screen must not burn battery painting canvases nobody is looking at.
  function sync() {
    const want = s.loaded && s.visible && !s.dead && !document.hidden
    if (want === s.playing) return
    s.playing = want
    s.t0 = null
    if (want) s.raf = requestAnimationFrame(loop)
    else if (s.raf) { cancelAnimationFrame(s.raf); s.raf = 0 }
  }

  async function load() {
    if (s.loading || s.loaded || s.dead) return
    s.loading = true
    try {
      const [raw, cm] = await Promise.all([fetchClip(contentHash), fetchCharmaps()])
      if (s.dead) return
      // R2 holds the raw viz bundle; the desktop endpoint wraps it as
      // {bundle, anim, available} — normalise either shape.
      s.bundle = raw.bundle || raw
      s.clip = raw
      if (!s.bundle?.meta || s.bundle.meta.n < 2) throw new Error('empty clip')
      s.anim = await ensurePacks(s.bundle)
      if (s.dead) return
      const hasAnims = Object.values(s.anim).some((a) => a && Object.keys(a).length)
      // no charmaps or no packs still plays — litePaint falls back to dots
      s.renderer = (cm && hasAnims) ? createRenderer(cm) : null

      const n = s.bundle.meta.n
      const sf = s.bundle.meta.start_frame ?? -123
      if (startFrame != null) {
        // Chip frames are cloud combo frames (row basis); a raw-derived clip
        // has to translate them onto its finalized timeline first.
        const a = comboFrame(raw, startFrame)
        const b = endFrame != null ? comboFrame(raw, endFrame) : a + 300
        s.lo = Math.max(0, a - sf - PRE_ROLL)
        s.hi = Math.min(n - 1, b - sf + POST_ROLL)
      } else {
        s.lo = Math.max(0, lo ?? 0)
        s.hi = Math.min(n - 1, hi ?? n - 1)
      }
      if (s.hi <= s.lo) { s.lo = 0; s.hi = n - 1 }
      s.pos = s.lo
      s.loading = false
      s.loaded = true
      note.hidden = true
      size()
      draw(s.lo, true)
      sync()
    } catch {
      if (s.dead) return
      s.loading = false
      note.hidden = false
      note.textContent = 'clip unavailable'
      note.classList.add('is-err')
      stage.classList.add('is-dead')
    }
  }

  s.sync = sync
  s.destroy = () => {
    s.dead = true
    s.playing = false
    if (s.raf) cancelAnimationFrame(s.raf)
    s.raf = 0
    if (loadObs) loadObs.disconnect()
    if (visObs) visObs.disconnect()
    if (ro) ro.disconnect()
    live.delete(s)
  }
  root.destroy = s.destroy
  live.add(s)

  // Two observers, two jobs: a generous margin so the clip is already decoded
  // by the time it scrolls in, and a plain in-view test that gates the loop.
  if (typeof IntersectionObserver === 'undefined') {
    s.visible = true
    load()
  } else {
    loadObs = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return
      loadObs.disconnect()
      load()
    }, { rootMargin: '400px 0px' })
    loadObs.observe(root)

    visObs = new IntersectionObserver((entries) => {
      s.visible = entries[entries.length - 1].isIntersecting
      sync()
    })
    visObs.observe(root)

    // A belt-and-braces geometric check one beat later. An observer that gets
    // its first callback while the page isn't being composited reports "not
    // intersecting" and then never fires again until something moves — so a
    // card that IS on screen would sit on "rendering…" forever waiting for a
    // scroll that never comes.
    setTimeout(() => {
      if (s.dead || s.loaded || s.loading || !root.isConnected) return
      const r = root.getBoundingClientRect()
      const onScreen = r.bottom > -400 && r.top < (window.innerHeight || 0) + 400
        && r.width > 0
      if (!onScreen) return
      s.visible = true
      load()
    }, 700)
  }

  // A card built into a bubble that is still detached (or inside a thread the
  // user hasn't switched to yet) measures 0 wide and would stay black; repaint
  // as soon as it gains real dimensions.
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => {
      if (!s.bundle) return
      const before = { w: cv.width, h: cv.height }
      if (!size()) return
      if (cv.width !== before.w || cv.height !== before.h) draw(s.pos, true)
    })
    ro.observe(cv)
  }

  const expand = () => { if (onExpand) onExpand() }
  stage.addEventListener('click', expand)
  stage.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); expand() }
  })

  return root
}

/** Lay out 1..N clip cards under a reply. One clip gets the full bubble width
 * (it's the answer); two or more pair up, which is as many as a phone can show
 * without the fighters becoming unreadable dots. */
export function clipReel(cards) {
  const reel = el(`<div class="cc-reel${cards.length === 1 ? ' is-single' : ''}"></div>`)
  for (const c of cards) reel.appendChild(c)
  return reel
}
