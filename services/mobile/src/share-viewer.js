// share-viewer — the runtime inside a shared artifact. The share file is ONE
// self-contained HTML document (the "claude artifact" model from the design
// doc): viewer code + gzipped data inline, no network, opens anywhere.
//
// Reads window.__SHARE_B64 = base64(gzip(JSON {title, subtitle, bundle, anim,
// charmaps, lo, hi})) and plays it. Kept dependency-light: litePaint +
// meleeRender only.
//
// `mountPlayer` is the player itself, exported because the public /replay/<id>
// page (public-viewer.js) shows the same thing from a URL instead of from an
// inlined blob. Only where the data comes from differs, so only that is
// duplicated -- two renderers would drift, and the drift would be silent.
import {
  paintFrame, stepCamera, viewFromCam, paintHudCanvas, drawRandall,
} from '../../../app/frontend/src/tracker/replays/litePaint'
import { createRenderer } from '../../../app/frontend/src/tracker/replays/meleeRender'
import { paintOverlays } from './overlays'
import { registerStageDataLoader, ensureStageData, registerFighterDataLoader, ensureReplayFighterData, registerItemDataLoader, ensureReplayItemData, registerHitDataLoader, ensureReplayHitData } from '../../../app/frontend/src/tracker/replays/stageData.js'

/** Cloud combos remain ROW-basis. Only phone snapshots are finalized.
 * Same clamp/anchor rule as api.comboFrame; old frames shares pass through. */
export function snapshotComboFrame(bundle, rowFrame) {
  if (!bundle.meta.finalized) return rowFrame
  const { row_fids: rows, row_first: first = bundle.meta.start_frame } = bundle.meta
  if (!rows?.length) throw new Error('share snapshot missing row frame map')
  const index = Math.max(0, Math.min(rows.length - 1, Math.trunc(rowFrame - first)))
  return rows[index]
}

async function decode(b64) {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  const ds = new DecompressionStream('gzip')
  const text = await new Response(new Blob([bytes]).stream().pipeThrough(ds)).text()
  return JSON.parse(text)
}

/** Play a {title, subtitle, bundle, anim, charmaps, lo, hi, stockIcons}
 *  payload into the page's #stage/#seek/#play elements. */
export function mountPlayer(data) {
  const status = document.getElementById('pstatus')
  if (data.title) {
    document.getElementById('title').textContent = data.title
    document.title = data.title
  }
  if (data.subtitle) document.getElementById('subtitle').textContent = data.subtitle

  const bundle = data.bundle
  const renderer = data.charmaps ? createRenderer(data.charmaps) : null
  const cv = document.getElementById('stage')
  const ctx = cv.getContext('2d')
  const seek = document.getElementById('seek')
  const playBtn = document.getElementById('play')
  const dpr = Math.max(1, window.devicePixelRatio || 1)

  const lo = data.lo ?? 0
  const hi = data.hi ?? bundle.meta.n - 1
  const s = { pos: lo, playing: false, raf: 0, cam: {}, t0: null }
  seek.min = String(lo)
  seek.max = String(hi)
  seek.value = String(lo)

  const size = () => { cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr }

  const icons = {}
  for (const [i, uri] of Object.entries(data.stockIcons || {})) {
    if (!uri) continue
    const img = new Image()
    img.onload = () => { icons[i] = img }
    img.src = uri
  }

  function draw(idx, snap) {
    stepCamera(s.cam, bundle.frames, idx, snap)
    const view = viewFromCam(s.cam, cv.clientWidth, cv.clientHeight)
    paintFrame(ctx, bundle, data.anim, renderer, idx, view, dpr)
    if (bundle.meta.stage === 8) {
      drawRandall(ctx, (bundle.meta.start_frame ?? -123) + idx, view, dpr)
    }
    // HUD scale follows the SHORTER proportion of the canvas, not raw width:
    // sized by width alone, a desktop-wide canvas grows the percent readouts
    // into billboards (the scale is in device pixels, so dpr rides along).
    const hudScale = Math.max(1, dpr * Math.min(cv.clientWidth, 1.5 * cv.clientHeight) / 500)
    paintHudCanvas(ctx, bundle, idx, cv.width, cv.height, hudScale, icons)
    // input display / action banner / readout, honouring the same persisted
    // overlaySettings the app uses -- one preference, every player
    paintOverlays(ctx, bundle, idx, cv.width, cv.height, hudScale, icons)
    if (data.onFrame) data.onFrame(idx)
  }

  const PLAY = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.54.84l10-6.5a1 1 0 0 0 0-1.68l-10-6.5A1 1 0 0 0 8 5.5z"/></svg>`
  const PAUSE = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><rect x="6" y="5" width="4.4" height="14" rx="1.4"/><rect x="13.6" y="5" width="4.4" height="14" rx="1.4"/></svg>`
  const syncSeek = () => {
    const p = hi > lo ? ((s.pos - lo) / (hi - lo)) * 100 : 0
    seek.style.setProperty('--p', `${p}%`)
  }

  function loop(t) {
    if (!s.playing) return
    if (s.t0 == null) s.t0 = t - ((s.pos - lo) / 60) * 1000
    let idx = lo + Math.floor(((t - s.t0) / 1000) * 60)
    if (idx > hi) { idx = lo; s.t0 = t }
    if (idx !== s.pos) { s.pos = idx; seek.value = String(idx); syncSeek(); draw(idx, false) }
    s.raf = requestAnimationFrame(loop)
  }
  const setPlaying = (on) => {
    s.playing = on
    s.t0 = null
    playBtn.innerHTML = on ? PAUSE : PLAY
    if (on) s.raf = requestAnimationFrame(loop)
    else if (s.raf) cancelAnimationFrame(s.raf)
  }
  const jump = (idx, snap) => {
    s.pos = Math.max(lo, Math.min(hi, idx))
    seek.value = String(s.pos)
    syncSeek()
    draw(s.pos, snap)
  }
  playBtn.addEventListener('click', () => setPlaying(!s.playing))
  seek.addEventListener('input', () => { setPlaying(false); jump(Number(seek.value), true) })
  // Desktop viewers get the keys every video player has taught their hands:
  // space toggles, arrows frame-step (with shift, a half second).
  window.addEventListener('keydown', (e) => {
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) && e.target !== seek) return
    if (e.key === ' ') { e.preventDefault(); setPlaying(!s.playing) }
    else if (e.key === 'ArrowRight') { e.preventDefault(); setPlaying(false); jump(s.pos + (e.shiftKey ? 30 : 1), false) }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); setPlaying(false); jump(s.pos - (e.shiftKey ? 30 : 1), true) }
  })
  window.addEventListener('resize', () => { size(); draw(s.pos, true) })

  size()
  status.textContent = ''
  draw(lo, true)
  setPlaying(true)
  // enough handle for a host page to bolt on frame steps, a timeline, an
  // overlay toggle -- without reaching into the loop
  return {
    jump,
    setPlaying,
    pos: () => s.pos,
    playing: () => s.playing,
    icons,
    redraw: () => draw(s.pos, true),
  }
}

async function main() {
  const status = document.getElementById('pstatus')
  let data
  try {
    data = await decode(window.__SHARE_B64)
  } catch (e) {
    status.textContent = `could not open this share: ${e.message}`
    return
  }
  // Downloaded artifacts have no asset origin. Only their separately fetched
  // template includes the tables, preserving offline playback without adding
  // them to either the phone app or public replay runtime.
  if (typeof __INLINE_STAGE_DATA__ !== 'undefined') {
    registerStageDataLoader(id => __INLINE_STAGE_DATA__[id] || null)
  }
  // The artifact carries only its own clip's fighter tables (share.js).
  registerFighterDataLoader(id => data.fighters?.[id] || null)
  registerItemDataLoader(id => data.items?.[id] || null)
  // and its fighters' hit spark tables (older artifacts have none: no sparks)
  registerHitDataLoader(id => data.hits?.[id] || null)
  await Promise.all([ensureStageData(data.bundle.meta.stage), ensureReplayFighterData(data.bundle), ensureReplayItemData(data.bundle),
    ensureReplayHitData(data.bundle)])
  mountPlayer({ title: data.title || 'Shared replay', ...data })
}

// Only the legacy self-contained artifact page inlines __SHARE_B64. The
// public share runtime (public-viewer.js) imports mountPlayer from this
// module, which used to run main() too — atob(undefined) painted
// "could not open this share" over the loading status on EVERY public page
// load until the real runtime overwrote it.
if (window.__SHARE_B64) main()
