import { useEffect, useRef, useState, useCallback } from 'react'
import { GIFEncoder, quantize, applyPalette } from 'gifenc'
import { BACKEND_URL } from '../../shared/config/config'
import { loadLiteClip } from './liteClipLoader'
import { createRenderer } from './meleeRender'
import { stateLabel, moveName, controllerSVG } from './meleeReadout'
import { esc, urlId } from './liteHtml'
import {
  P, pcolor, getCharmaps, stepCamera, viewFromCam, paintFrame,
  drawRandall, paintHudCanvas,
} from './litePaint'
import './WatchLiteModal.css'

const API = `${BACKEND_URL}/api/nucleome`
const TERM = { stock_drop: '#ffcc45', reversal: '#b06bff', timeout: '#5b6478', game_end: '#3a3f52' }
const CAT_NAME = ['neutral', 'airborne', 'attacking', 'shielding', 'captured', 'ledge', 'dead']

// Two clip sources: a local game window (gameId+start/end) or a tool-minted
// ref (clipRef, Randall).
export default function WatchLiteClip({ gameId, start, end, clipRef, title, subtitle, showPanel, onExpand }) {
  const canvasRef = useRef(null)
  const seekRef = useRef(null)
  const panelRef = useRef(null)
  const inputRef = useRef(null)
  const hudRef = useRef(null)
  const tlRef = useRef(null)
  const stateRef = useRef({ cam: {} })
  const [status, setStatus] = useState('loading')
  const [playing, setPlaying] = useState(true)
  const [gif, setGif] = useState(null)   // null | {pct} | 'done'

  const liveName = useCallback((i) => {
    const s = stateRef.current
    const form = s.bundle.frames.form && s.bundle.frames.form[i]
    if (form) { const c = form[s.pi]; if (c === 'S') return 'Sheik'; if (c === 'Z') return 'Zelda' }
    return s.bundle.meta.players[i].char_name
  }, [])

  // Character identity renders as a stock icon everywhere in this panel, not
  // as a name. Follows Zelda/Sheik transforms the same way liveName does
  // (external char ids: 18 = Zelda, 19 = Sheik).
  const liveChar = useCallback((i) => {
    const s = stateRef.current
    const form = s.bundle.frames.form && s.bundle.frames.form[i]
    if (form) { const c = form[s.pi]; if (c === 'S') return 19; if (c === 'Z') return 18 }
    return s.bundle.meta.players[i].char
  }, [])

  const liveIcon = useCallback((i) => {
    const costume = stateRef.current.bundle.meta.players[i].costume ?? 0
    return `<img class="wl-nmicon" src="${API}/stock/${urlId(liveChar(i))}/${urlId(costume)}" alt="" onerror="this.style.visibility='hidden'"/>`
  }, [liveChar])

  const activeConv = useCallback((sf) => {
    const s = stateRef.current
    let act = null
    for (const a of ['0', '1']) for (const c of (s.bundle.conversions[a] || [])) {
      if (sf >= c.start_frame && sf <= c.end_frame &&
          (!act || (c.end_frame - c.start_frame) < (act.end_frame - act.start_frame))) {
        act = { ...c, actor: +a }
      }
    }
    return act
  }, [])

  const paintPanel = useCallback((idx) => {
    const s = stateRef.current
    if (!panelRef.current || !s.bundle) return
    const f = s.bundle.frames, meta = s.bundle.meta, sf = meta.start_frame + idx
    s.pi = idx
    const act = activeConv(sf)
    const col = (i) => {
      const mv = moveName(f.move[i][idx], meta.attack_names)
      const dir = (f.dir && f.dir[i]) ? f.dir[i][idx] : 1
      const col_i = pcolor(s.bundle, i)
      const role = act ? (act.actor === i
        ? `<div class="wlp-role" style="color:${col_i}">▶ converting</div>`
        : '<div class="wlp-role" style="color:#ff5470">◀ being comboed</div>') : ''
      return `<div class="wlp-col wlp-col--${i}">
        <div class="wlp-nm" style="color:${col_i}">${liveIcon(i)} <span class="wlp-face">${dir < 0 ? '◀' : '▶'}</span></div>
        <div class="wlp-st">${esc(stateLabel(f.state[i][idx]))}</div>
        <div class="wlp-mv">${mv ? 'last hit: ' + esc(mv) : '—'}</div>
        ${role}
      </div>`
    }
    const mm = Math.floor(Math.max(0, sf) / 3600), ss = (Math.max(0, sf) / 60) % 60
    const html =
      `<div class="wlp-time">f${sf} · ${mm}:${ss.toFixed(1).padStart(4, '0')}</div>
       <div class="wlp-cols">${meta.players.map((_, i) => col(i)).join('')}</div>`
    if (panelRef.current.__h !== html) { panelRef.current.innerHTML = html; panelRef.current.__h = html }
  }, [liveIcon, activeConv])

  // controllers live in their OWN fixed-height box so the variable-row panel
  // below doesn't jump as rows change.
  const paintInputs = useCallback((idx) => {
    const s = stateRef.current
    if (!inputRef.current || !s.bundle) return
    const f = s.bundle.frames
    const col = (i) => `<div class="wl-inputcol">
      <div class="wl-inputnm" style="color:${pcolor(s.bundle, i)}">${liveIcon(i)}</div>
      ${controllerSVG(
        f.btn ? f.btn[i][idx] : 0,
        f.joyx ? f.joyx[i][idx] : 0, f.joyy ? f.joyy[i][idx] : 0,
        f.cstickx ? f.cstickx[i][idx] : 0, f.csticky ? f.csticky[i][idx] : 0)}
    </div>`
    const html = s.bundle.meta.players.map((_, i) => col(i)).join('')
    if (inputRef.current.__h !== html) { inputRef.current.innerHTML = html; inputRef.current.__h = html }
  }, [liveIcon])

  const paintHud = useCallback((idx) => {
    const s = stateRef.current
    if (!hudRef.current || !s.bundle) return
    const f = s.bundle.frames, meta = s.bundle.meta, sf = meta.start_frame + idx
    const NP = meta.players.length
    const card = (i) => {
      const p = meta.players[i]
      const name = p.tag || p.code || liveName(i)
      const stk = Math.max(0, Math.min(4, f.stk[i][idx]))
      const col = pcolor(s.bundle, i)
      const dots = Array.from({ length: stk }).map(() => `<i style="background:${col}"></i>`).join('')
      return `<div class="wl-hudcard ${NP === 2 ? 'wl-hudcard--' + i : ''}">
        <img class="wl-hud-icon" src="${API}/stock/${urlId(p.char)}/${urlId(p.costume ?? 0)}" alt="" onerror="this.style.visibility='hidden'"/>
        <span class="wl-hud-who"><b>${esc(name)}</b></span>
        <span class="wl-hud-stocks">${dots}</span>
        <span class="wl-hud-pct">${Math.round(f.pct[i][idx])}<b>%</b></span>
      </div>`
    }
    let html
    if (NP === 2) {                              // 1v1: cards + the exchange banner
      const act = activeConv(sf)
      let banner
      if (act) {
        const a = act.actor, ev = act.evidence
        const chain = ev.move_chain || ev.opener   // the WHOLE combo, not one move
        banner = `${liveIcon(a)} <b style="color:${P[a]}">converting</b> · <span style="color:#35d0be">${esc(chain)}</span> · ${esc(ev.hits)} hits · ${esc(ev.damage)}%${ev.killed ? ' → <b style="color:#ffcc45">KO</b>' : ''}`
      } else {
        const c0 = f.cat[0][idx], c1 = f.cat[1][idx]
        if (c0 === 4 && c1 !== 4) banner = `${liveIcon(1)} <b style="color:${P[1]}">in advantage</b>`
        else if (c1 === 4 && c0 !== 4) banner = `${liveIcon(0)} <b style="color:${P[0]}">in advantage</b>`
        else banner = `<span style="color:#7b8497">neutral — ${CAT_NAME[c0]} vs ${CAT_NAME[c1]}</span>`
      }
      html = card(0) + `<div class="wl-hudbanner">${banner}</div>` + card(1)
    } else {                                     // doubles / FFA: just the fighter cards
      html = meta.players.map((_, i) => card(i)).join('')
    }
    // Only touch the DOM when something actually changed — re-inserting the
    // <img> stock icon every frame thrashes the main thread (looks like lag).
    if (hudRef.current.__h !== html) { hudRef.current.innerHTML = html; hudRef.current.__h = html }
  }, [liveName, liveIcon, activeConv])

  const drawTimeline = useCallback((idx) => {
    const s = stateRef.current, cv = tlRef.current
    if (!cv || !s.bundle) return
    // the conversion timeline is a 1v1 notion — hide it for doubles/FFA
    if (s.bundle.meta.players.length !== 2) { cv.style.display = 'none'; return }
    cv.style.display = ''
    const dpr = Math.max(1, window.devicePixelRatio || 1)
    const tw = Math.round(cv.clientWidth * dpr), th = Math.round(cv.clientHeight * dpr)
    if (cv.width !== tw || cv.height !== th) { cv.width = tw; cv.height = th }
    const ctx = cv.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    const w = cv.clientWidth, h = cv.clientHeight, meta = s.bundle.meta
    ctx.clearRect(0, 0, w, h)
    const fx = (sf) => (sf - meta.start_frame) / Math.max(1, meta.n - 1) * w
    const laneH = (h - 6) / 2
    for (const a of ['0', '1']) {
      const top = a === '0' ? 2 : 4 + laneH
      ctx.fillStyle = a === '0' ? '#141a28' : '#12161f'; ctx.fillRect(0, top, w, laneH)
      for (const c of (s.bundle.conversions[a] || [])) {
        const x0 = fx(c.start_frame), x1 = Math.max(x0 + 2, fx(c.end_frame))
        ctx.fillStyle = TERM[c.evidence.termination] || '#555'
        ctx.globalAlpha = c.certainty === 'inferred' ? 0.5 : 0.9
        ctx.fillRect(x0, top + 1, x1 - x0, laneH - 2); ctx.globalAlpha = 1
      }
      // lane label: the player's stock icon (fallback to the char name until
      // the image finishes loading — the timeline redraws every frame anyway)
      if (!s.tlIcons) {
        s.tlIcons = meta.players.map((pl) => {
          const im = new Image()
          im.src = `${API}/stock/${pl.char}/${pl.costume ?? 0}`
          return im
        })
      }
      const im = s.tlIcons[+a]
      if (im && im.complete && im.naturalWidth) {
        ctx.drawImage(im, 3, top + 1, laneH - 2, laneH - 2)
      } else {
        ctx.fillStyle = P[+a]; ctx.font = '9px system-ui'; ctx.textAlign = 'left'
        ctx.fillText(meta.players[+a].char_name, 4, top + 9)
      }
    }
    const px = fx(meta.start_frame + idx)
    ctx.strokeStyle = '#35d0be'; ctx.lineWidth = 1.5
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, h); ctx.stroke()
  }, [])

  // The canvas (stage + fighters) repaints every animation frame for smooth
  // motion; the DOM overlays (HUD / inputs / panel / timeline) are heavier and
  // only need ~18 fps, so the loop passes overlays=false on most frames.
  const draw = useCallback((idx, snap, overlays = true) => {
    const s = stateRef.current, cv = canvasRef.current
    if (!s.bundle || !cv) return
    const dpr = Math.max(1, window.devicePixelRatio || 1)
    stepCamera(s.cam, s.bundle.frames, idx, snap)
    const view = viewFromCam(s.cam, cv.clientWidth, cv.clientHeight)
    const ctx = cv.getContext('2d')
    paintFrame(ctx, s.bundle, s.anim, s.renderer, idx, view, dpr)
    if (s.bundle.meta.stage === 8) drawRandall(ctx, s.bundle.meta.start_frame + idx, view, dpr)
    if (overlays) {
      if (showPanel) { paintInputs(idx); paintPanel(idx); paintHud(idx) }
      drawTimeline(idx)
    }
  }, [showPanel, paintInputs, paintPanel, paintHud, drawTimeline])

  const loop = useCallback((t) => {
    const s = stateRef.current
    if (!s.bundle || !s.playing) return
    if (!s.last) s.last = t
    // clamp dt: after a stall (GC, tab throttle) a huge delta would teleport the
    // playhead and read as a stutter — cap the step at ~3 frames.
    const dt = Math.min(0.05, (t - s.last) / 1000); s.last = t
    s.pos = (s.pos + dt * 60) % s.bundle.meta.n
    const idx = Math.floor(s.pos)
    const ov = !s.lastOv || (t - s.lastOv) >= 55   // ~18 fps overlay refresh
    if (ov) s.lastOv = t
    try { draw(idx, false, ov) } catch { /* a single bad frame must not kill playback */ }
    if (seekRef.current) seekRef.current.value = String(idx)
    s.raf = requestAnimationFrame(loop)
  }, [draw])

  const setRunning = useCallback((run) => {
    const s = stateRef.current
    s.playing = run && !!s.bundle
    setPlaying(s.playing)
    if (s.playing) { s.last = 0; s.raf = requestAnimationFrame(loop) }
    else if (s.raf) cancelAnimationFrame(s.raf)
  }, [loop])

  const onScrub = useCallback((e) => {
    const s = stateRef.current
    if (!s.bundle) return
    setRunning(false)
    s.pos = +e.target.value
    draw(Math.floor(s.pos), true)
  }, [draw, setRunning])

  const seekTo = useCallback((clientX) => {
    const s = stateRef.current, cv = tlRef.current
    if (!s.bundle || !cv) return
    const r = cv.getBoundingClientRect()
    const fr = Math.round((clientX - r.left) / cv.clientWidth * (s.bundle.meta.n - 1))
    setRunning(false)
    s.pos = Math.max(0, Math.min(s.bundle.meta.n - 1, fr))
    if (seekRef.current) seekRef.current.value = String(s.pos)
    draw(s.pos, true)
  }, [draw, setRunning])

  // Frame-exact stepping for the trailer capture (capture-lite-combo.mjs):
  // real-time playback can't be screen-recorded without stutter/drift, so the
  // capture pauses and walks frames one by one, screenshotting each. Dev only.
  useEffect(() => {
    if (!import.meta.env.DEV) return undefined
    window.__wlStep = (idx, snap) => {
      const s = stateRef.current
      if (!s.bundle) return null
      setRunning(false)
      const i = Math.max(0, Math.min(s.bundle.meta.n - 1, idx))
      s.pos = i
      if (seekRef.current) seekRef.current.value = String(i)
      draw(i, !!snap, true)
      return { n: s.bundle.meta.n, startFrame: s.bundle.meta.start_frame }
    }
    return () => { delete window.__wlStep }
  }, [draw, setRunning])

  // ---- GIF export ----
  const exportGif = useCallback(async () => {
    const s = stateRef.current
    if (!s.bundle || gif) return
    setRunning(false)
    setGif({ pct: 0 })
    const n = s.bundle.meta.n
    const W = 480, H = 270, dpr = 1
    const off = document.createElement('canvas'); off.width = W; off.height = H
    const ctx = off.getContext('2d')
    const cam = {}
    // ~20-30 fps source -> lighter gif; for very long clips (a full game can be
    // 8000+ frames) widen the stride so the encode stays bounded (~900 frames).
    const step = Math.max(n > 900 ? 3 : 2, Math.ceil(n / 900))
    const enc = GIFEncoder()
    const delay = Math.round((step / 60) * 1000)
    try {
      for (let i = 0; i < n; i += step) {
        stepCamera(cam, s.bundle.frames, i, i === 0)
        const view = viewFromCam(cam, W, H)
        paintFrame(ctx, s.bundle, s.anim, s.renderer, i, view, dpr)
        if (s.bundle.meta.stage === 8) drawRandall(ctx, s.bundle.meta.start_frame + i, view, dpr)
        paintHudCanvas(ctx, s.bundle, i, W, H)
        const { data } = ctx.getImageData(0, 0, W, H)
        const palette = quantize(data, 256)
        const index = applyPalette(data, palette)
        enc.writeFrame(index, W, H, { palette, delay })
        if ((i / step) % 6 === 0) {
          setGif({ pct: Math.round((i / n) * 100) })
          await new Promise((r) => setTimeout(r, 0))
        }
      }
      enc.finish()
      const blob = new Blob([enc.bytes()], { type: 'image/gif' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `${(title || 'clip').replace(/[^\w-]+/g, '_')}.gif`
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 4000)
      setGif('done'); setTimeout(() => setGif(null), 1500)
    } catch {
      setGif(null)
    }
  }, [gif, setRunning, title])

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    Promise.all([
      getCharmaps().catch(() => null),
      loadLiteClip({ gameId, start, end, clipRef }),
    ]).then(([cm, clip]) => {
      if (cancelled) return
      const s = stateRef.current
      if (!clip.bundle || clip.bundle.meta.n < 2) { setStatus('error'); return }
      s.bundle = clip.bundle; s.anim = clip.anim
      s.renderer = (cm && clip.available) ? createRenderer(cm) : null
      s.cam = {}; s.pos = 0
      const cv = canvasRef.current
      const dpr = Math.max(1, window.devicePixelRatio || 1)
      cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr
      if (seekRef.current) { seekRef.current.max = String(s.bundle.meta.n - 1); seekRef.current.value = '0' }
      setStatus(s.renderer ? 'ready' : 'dots')
      draw(0, true)
      setRunning(true)
    }).catch(() => { if (!cancelled) setStatus('error') })
    return () => {
      cancelled = true
      const s = stateRef.current
      if (s.raf) cancelAnimationFrame(s.raf)
      s.playing = false
    }
  }, [gameId, start, end, clipRef, draw, setRunning])

  // Clips mounted while hidden (display:none coach tab, restored chats) size
  // their canvas to 0 and stay black. Re-size + repaint whenever the stage
  // actually gains real dimensions.
  useEffect(() => {
    const cv = canvasRef.current
    if (!cv || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => {
      const s = stateRef.current
      if (!s.bundle || !cv.clientWidth) return
      const dpr = Math.max(1, window.devicePixelRatio || 1)
      const w = Math.round(cv.clientWidth * dpr)
      const h = Math.round(cv.clientHeight * dpr)
      if (cv.width === w && cv.height === h) return
      cv.width = w
      cv.height = h
      // the playhead is fractional while playing (and after a click pause);
      // paint its whole frame, as the loop does. A fractional index reads
      // undefined rows and the snapped camera stays NaN for good.
      draw(Math.floor(s.pos || 0), true)
    })
    ro.observe(cv)
    return () => ro.disconnect()
  }, [draw])

  const gifLabel = gif && gif !== 'done' ? `Exporting… ${gif.pct || 0}%`
    : gif === 'done' ? 'Saved ✓' : '⬇ Export GIF'

  const body = (
    <div className="wl-clip">
      <div className="wl-clip-stage" onClick={() => setRunning(!playing)}>
        <canvas ref={canvasRef} className="wl-canvas" />
        {showPanel && <div ref={hudRef} className="wl-hud" />}
        {onExpand && (
          <button className="wl-expand" title="Fullscreen"
                  onClick={(e) => { e.stopPropagation(); onExpand({ gameId, start, end, clipRef, title }) }}>⛶</button>
        )}
        {status === 'loading' && <div className="wl-note">rendering…</div>}
        {status === 'error' && <div className="wl-note wl-err">clip unavailable</div>}
        {status !== 'loading' && status !== 'error' && !playing && !gif && <div className="wl-play-badge">▶</div>}
        {status === 'dots' && <div className="wl-badge">dot mode</div>}
      </div>
      <div className="wl-clip-bar">
        <button className="wl-mini" onClick={() => setRunning(!playing)}
                disabled={status === 'loading' || status === 'error'}
                aria-label={playing ? 'Pause' : 'Play'}>{playing ? '❚❚' : '▶'}</button>
        <input ref={seekRef} className="wl-seek" type="range" min="0" max="0"
               defaultValue="0" onInput={onScrub}
               onMouseDown={() => setRunning(false)} aria-label="Seek" />
        {!showPanel && (
          <button className="wl-mini wl-gif" onClick={exportGif}
                  disabled={!!gif || status === 'loading' || status === 'error'}
                  title="Export this clip as a GIF">GIF</button>
        )}
      </div>
      <canvas ref={tlRef} className="wl-clip-tl"
              onMouseDown={(e) => seekTo(e.clientX)} title="conversions — click to seek" />
    </div>
  )

  if (!showPanel) return body
  return (
    <div className="wl-clip-withpanel">
      {body}
      <div className="wl-side">
        <button className="wl-gifbig" onClick={exportGif}
                disabled={!!gif || status === 'loading' || status === 'error'}
                title="Save this clip as a GIF">{gifLabel}</button>
        <div ref={inputRef} className="wl-inputbox" />
        <div ref={panelRef} className="wl-panel" />
      </div>
    </div>
  )
}
