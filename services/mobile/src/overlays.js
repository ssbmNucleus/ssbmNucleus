// overlays — user-toggleable player overlays for the mobile Watch Lite player,
// ported from the desktop's DOM overlays (WatchLiteClip.jsx paintInputs /
// paintHud / paintPanel) but painted straight onto the canvas so they survive
// burned-in exports and share artifacts. Three independent toggles:
//   inputs  — per-player controller readout (sticks + button pips), bottom corners
//   action  — the desktop paintHud exchange banner, top-middle: prefers
//             bundle.conversions ("converting · chain · N hits · D%"), falls
//             back to cat-4 asymmetry ("in advantage") then "neutral — x vs y"
//   readout — the desktop side panel: per-player action state, last connected
//             move, facing and combo role, plus frame + m:ss.s
// Everything is null-safe against v1 bundles that predate the input rows
// (joyx/joyy/cstickx/csticky/btn) — those simply draw nothing.
import { pcolor } from '../../../app/frontend/src/tracker/replays/litePaint'
import { stateLabel, moveName } from '../../../app/frontend/src/tracker/replays/meleeReadout'
import { sheet, sheetRow } from './ui'

const STORE_KEY = 'nucleus.vault.overlays'

export const overlaySettings = { inputs: false, action: true, readout: false }
try {
  const saved = JSON.parse(localStorage.getItem(STORE_KEY))
  if (saved && typeof saved === 'object') {
    if (typeof saved.inputs === 'boolean') overlaySettings.inputs = saved.inputs
    if (typeof saved.action === 'boolean') overlaySettings.action = saved.action
    if (typeof saved.readout === 'boolean') overlaySettings.readout = saved.readout
  }
} catch { /* private mode / first run */ }

export function setOverlay(key, on) {
  if (!(key in overlaySettings)) return
  overlaySettings[key] = !!on
  try { localStorage.setItem(STORE_KEY, JSON.stringify(overlaySettings)) } catch { /* full/private */ }
}

// GC physical-button bitmask (Slippi Buttons.Physical) — same table the
// desktop uses in frontend/src/tracker/replays/meleeReadout.js (BUTTON_BITS/controllerSVG):
// A=0x100 B=0x200 X=0x400 Y=0x800 Z=0x10 L=0x40 R=0x20.
// Start and the d-pad are in the same bitmask the rest come from (see the
// desktop's meleeReadout), and the bundle has carried them all along — drawing
// them as permanently dead furniture was just an omission here.
const BTN = {
  A: 0x100, B: 0x200, X: 0x400, Y: 0x800, Z: 0x10, L: 0x40, R: 0x20,
  START: 0x1000, DU: 0x8, DD: 0x4, DL: 0x2, DR: 0x1,
}

// canonical GC face colors (desktop controllerSVG's palette); lit = full
// alpha, unlit = a dim ghost of the same color — the real-controller layout
// plus real colors read faster than port-tinted letter pips.
const FACE = { A: '#4bd64c', B: '#ff5470', XY: '#c7ccd8', LR: '#c7ccd8', Z: '#b06bff' }

// bundle.frames.cat codes, desktop's CAT_NAME verbatim (WatchLiteClip.jsx)
const CAT_NAME = ['neutral', 'airborne', 'attacking', 'shielding', 'captured', 'ledge', 'dead']

const cl = (v) => Math.max(-1, Math.min(1, v || 0))

function rr(ctx, x, y, w, h, r) {
  if (ctx.roundRect) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); ctx.fill() }
  else ctx.fillRect(x, y, w, h)
}

/** Call AFTER paintHudCanvas each frame. W/H are real canvas pixels (dpr
 * applied); `scale` multiplies every metric and `icons` is the same
 * {playerIndex: HTMLImageElement} stock-icon map — both the exact
 * conventions paintHudCanvas takes. */
export function paintOverlays(ctx, bundle, idx, W, H, scale = 1, icons = null) {
  if (!ctx || !bundle || !bundle.frames || !bundle.meta || !bundle.meta.players) return
  ctx.save()
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.textBaseline = 'alphabetic'
  if (overlaySettings.action) paintActionBanner(ctx, bundle, idx, W, scale, icons)
  if (overlaySettings.readout) paintReadout(ctx, bundle, idx, W, H, scale, icons)
  if (overlaySettings.inputs) paintInputDisplays(ctx, bundle, idx, W, H, scale)
  ctx.restore()
}

// ---- controller input display ------------------------------------------------

function paintInputDisplays(ctx, bundle, idx, W, H, scale) {
  const f = bundle.frames, NP = bundle.meta.players.length
  const S = scale
  const boxW = 106 * S, boxH = 46 * S, m = 8 * S
  for (let i = 0; i < NP; i++) {
    const jx = f.joyx && f.joyx[i], jy = f.joyy && f.joyy[i]
    if (!jx || !jy) continue                 // old v1 bundle: rows absent -> nothing
    // even ports bottom-left, odd bottom-right; doubles stack a second tier up
    const right = i % 2 === 1
    const x = right ? W - m - boxW : m
    const y = H - m - boxH - (i >> 1) * (boxH + 6 * S)
    const btn = f.btn && f.btn[i]
    drawController(ctx, x, y, boxW, boxH, S, pcolor(bundle, i),
      !!btn, btn ? (btn[idx] || 0) : 0,
      jx[idx], jy[idx],
      f.cstickx && f.cstickx[i] ? f.cstickx[i][idx] : 0,
      f.csticky && f.csticky[i] ? f.csticky[i][idx] : 0)
  }
}

// Everything below is laid out in a 106x46 unit space matching the widget, in
// the arrangement of the controller itself: shoulders across the top with L
// and R at the SAME height and Z tucked against R; the analog stick upper
// left with the d-pad beneath it; the C-stick low and central; and the A
// cluster right, with B low-left of A and Y/X wrapping over its shoulder.
// Getting these relationships right is the whole point — the silhouette is
// what makes it readable at a glance, not the individual dots.
function drawController(ctx, x, y, w, h, S, col, hasBtn, mask, jx, jy, cx, cy) {
  ctx.fillStyle = 'rgba(11,13,19,.62)'
  rr(ctx, x, y, w, h, 10 * S)

  const px = (u) => x + u * S
  const py = (u) => y + u * S

  // main stick: gate ring in the port color, dot at (joyx, joyy)
  const gx = px(23), gy = py(24), gr = 11 * S
  ctx.strokeStyle = col; ctx.globalAlpha = 0.55; ctx.lineWidth = 1.5 * S
  ctx.beginPath(); ctx.arc(gx, gy, gr, 0, 7); ctx.stroke(); ctx.globalAlpha = 1
  ctx.fillStyle = '#dfe4f0'
  ctx.beginPath(); ctx.arc(gx + cl(jx) * 8 * S, gy - cl(jy) * 8 * S, 4.4 * S, 0, 7); ctx.fill()

  // d-pad under the stick, one arm at a time so each lights on its own bit
  const dx = px(23), dy = py(39), arm = 2.1 * S, len = 5.6 * S
  const dpad = (ax, ay, aw, ah, bit) => {
    ctx.globalAlpha = (hasBtn && (mask & bit)) ? 1 : 0.22
    ctx.fillStyle = '#dfe4f0'
    rr(ctx, ax, ay, aw, ah, Math.min(aw, ah) / 2)
  }
  dpad(dx - len, dy - arm, len - arm * 0.2, arm * 2, BTN.DL)
  dpad(dx + arm * 0.2, dy - arm, len - arm * 0.2, arm * 2, BTN.DR)
  dpad(dx - arm, dy - len, arm * 2, len - arm * 0.2, BTN.DU)
  dpad(dx - arm, dy + arm * 0.2, arm * 2, len - arm * 0.2, BTN.DD)
  ctx.globalAlpha = 1

  // c-stick: smaller gate, yellow dot (desktop's c-stick color)
  const kx = px(49), ky = py(32), kr = 8 * S
  ctx.strokeStyle = col; ctx.globalAlpha = 0.35; ctx.lineWidth = 1.5 * S
  ctx.beginPath(); ctx.arc(kx, ky, kr, 0, 7); ctx.stroke(); ctx.globalAlpha = 1
  ctx.fillStyle = '#ffd24a'
  ctx.beginPath(); ctx.arc(kx + cl(cx) * 5 * S, ky - cl(cy) * 5 * S, 3.2 * S, 0, 7); ctx.fill()

  if (!hasBtn) return                      // bundle has no btn rows -> no buttons
  const DIM_A = 0.2
  const circ = (ux, uy, r, color, lit) => {
    ctx.globalAlpha = lit ? 1 : DIM_A
    ctx.fillStyle = color
    ctx.beginPath(); ctx.arc(px(ux), py(uy), r * S, 0, 7); ctx.fill()
  }
  const bar = (ux, uy, bw, bh, color, lit) => {
    ctx.globalAlpha = lit ? 1 : DIM_A
    ctx.fillStyle = color
    rr(ctx, px(ux), py(uy), bw * S, bh * S, (bh / 2) * S)
  }
  // shoulders: L and R level with each other, Z snug to the right of R
  bar(7, 3.5, 19, 5, FACE.LR, mask & BTN.L)
  bar(63, 3.5, 19, 5, FACE.LR, mask & BTN.R)
  bar(85, 3.5, 14, 5, FACE.Z, mask & BTN.Z)
  circ(49, 16, 2.2, '#dfe4f0', mask & BTN.START)   // start/pause, dead centre
  // the A cluster
  circ(76, 25, 7, FACE.A, mask & BTN.A)           // A — big green, centre
  circ(64, 32, 4.5, FACE.B, mask & BTN.B)         // B — red, low and left
  circ(70, 15, 4.2, FACE.XY, mask & BTN.Y)        // Y — over A's left shoulder
  circ(88, 22, 4.2, FACE.XY, mask & BTN.X)        // X — right of A
  ctx.globalAlpha = 1
}

// ---- action / exchange banner ------------------------------------------------

// Shortest conversion overlapping slippi frame sf across both actors — a
// port of WatchLiteClip.jsx's activeConv. The desktop's clip bundles are
// pre-filtered to the window; the PHONE plays whole-game bundles, so the
// arrays carry the entire game's conversions and this runs every painted
// frame. Scan without allocating, memoize the one-frame-ago answer (the
// active conversion rarely changes between frames), and only build the
// result object when it does.
let _convMemo = { bundle: null, conv: null, actor: 0, out: null }
function activeConv(bundle, sf) {
  let conv = null
  let actor = 0
  for (const a of ['0', '1']) {
    for (const c of ((bundle.conversions && bundle.conversions[a]) || [])) {
      if (sf >= c.start_frame && sf <= c.end_frame &&
          (!conv || (c.end_frame - c.start_frame) < (conv.end_frame - conv.start_frame))) {
        conv = c
        actor = +a
      }
    }
  }
  if (!conv) return null
  const m = _convMemo
  if (m.bundle !== bundle || m.conv !== conv || m.actor !== actor) {
    _convMemo = { bundle, conv, actor, out: { ...conv, actor } }
  }
  return _convMemo.out
}

// FALLBACK combo counter for bundles that truly carry no conversions (old
// cached clips): while a player sits in cat 4 (captured/hitstun), walk back
// across the current stun run (tiny gaps allowed for hitlag/tumble flicker,
// hard lookback cap) and count discrete percent jumps. Conservative by design:
// the caller only shows the number at >= 2 hits, otherwise just the state.
// O(lookback) array reads per stunned player per frame — trivial at 60fps.
const MAX_LOOKBACK = 240   // 4s
const MAX_GAP = 10         // frames allowed outside cat 4 without ending the run
function comboHits(f, i, idx) {
  const cat = f.cat && f.cat[i], pct = f.pct && f.pct[i]
  if (!cat || !pct || cat[idx] !== 4) return 0
  let start = idx, gap = 0
  for (let j = idx - 1; j >= 0 && idx - j <= MAX_LOOKBACK; j--) {
    if (cat[j] === 4) { start = j; gap = 0 }
    else if (++gap > MAX_GAP) break
  }
  // baseline one frame before the run so the opening hit counts too
  let hits = 0, last = pct[Math.max(0, start - 1)]
  for (let j = start; j <= idx; j++) {
    const p = pct[j]
    if (p - last >= 1) hits++
    last = p
  }
  return hits
}

// The desktop paintHud exchange banner, canvas edition. 1v1 only — desktop
// hides the banner for doubles/FFA too. Composition matches desktop exactly:
//   conversion active -> [icon] converting · <move_chain||opener> · N hits · D%
//                        (+ " → KO" when evidence.killed)
//   else cat-4 asymmetry -> [icon] in advantage   (attacker's icon + color)
//   else -> neutral — <CAT_NAME[c0]> vs <CAT_NAME[c1]>
// "dair -> dair -> dair -> dair -> dair" is how the detector reports five of
// them, and on a phone that ellipsizes to "dair -> dair -> ..." — which reads
// as a two-hit combo. Collapse runs the way a player says them out loud.
function collapseChain(chain) {
  const parts = String(chain || '').split(' → ').filter(Boolean)
  if (!parts.length) return ''
  const out = []
  for (const m of parts) {
    const last = out[out.length - 1]
    if (last && last.name === m) last.n++
    else out.push({ name: m, n: 1 })
  }
  return out.map((e) => (e.n > 1 ? `${e.name} ×${e.n}` : e.name)).join(' → ')
}

function paintActionBanner(ctx, bundle, idx, W, scale, icons) {
  const f = bundle.frames, meta = bundle.meta
  if (meta.players.length !== 2) return
  const S = scale
  const sf = (meta.start_frame || 0) + idx
  const hasConv = !!bundle.conversions
  const act = hasConv ? activeConv(bundle, sf) : null

  // [text, color, bold] segments, desktop's exact fields and separators
  const TXT = '#cfd5e4', GREY = '#7b8497', TEAL = '#35d0be', GOLD = '#ffcc45'
  let segs, iconIdx = null
  if (act) {
    const ev = act.evidence || {}
    iconIdx = act.actor
    segs = [
      ['converting', pcolor(bundle, act.actor), true],
      [' · ', TXT],
      [collapseChain(ev.move_chain) || String(ev.opener || ''), TEAL],
    ]
    // a conversion record missing its counts would otherwise paint the literal
    // "undefined hits · undefined%" across the banner
    if (ev.hits != null || ev.damage != null) {
      segs.push([` · ${ev.hits ?? '?'} hits · ${ev.damage ?? '?'}%`, TXT])
    }
    if (ev.killed) segs.push([' → ', TXT], ['KO', GOLD, true])
  } else if (f.cat && f.cat[0] && f.cat[1]) {
    const c0 = f.cat[0][idx], c1 = f.cat[1][idx]
    if (c0 === 4 && c1 !== 4) iconIdx = 1
    else if (c1 === 4 && c0 !== 4) iconIdx = 0
    if (iconIdx != null) {
      segs = [['in advantage', pcolor(bundle, iconIdx), true]]
      // no conversions in this bundle at all -> the percent-delta heuristic
      // stands in for the detector's hit count (only when confident)
      if (!hasConv) {
        const hits = comboHits(f, iconIdx === 1 ? 0 : 1, idx)
        if (hits >= 2) segs.push([` · ${hits} hits`, TXT])
      }
    } else {
      segs = [[`neutral — ${CAT_NAME[c0] || c0} vs ${CAT_NAME[c1] || c1}`, GREY]]
    }
  } else return

  // measure (per-segment font: bold segments heavier, like the desktop <b>s)
  const fs = 10.5 * S
  const font = (b) => `${b ? 700 : 600} ${fs}px system-ui, sans-serif`
  const width = () => {
    let tw = 0
    for (const s of segs) { ctx.font = font(s[2]); tw += ctx.measureText(s[0]).width }
    return tw
  }
  const iconBox = iconIdx != null ? 13 * S : 0
  const pad = 8 * S, gap = iconIdx != null ? 5 * S : 0
  let tw = width()
  // a long move_chain can outgrow a phone canvas — ellipsize the chain segment
  const budget = W - 16 * S - iconBox - gap - pad * 2
  while (tw > budget && act && segs[2][0].length > 6) {
    segs[2][0] = segs[2][0].slice(0, -4).trimEnd() + '…'
    tw = width()
  }

  const bh = 18 * S, by = 44 * S   // HUD chips span y 8..38 in scale units
  const bw = tw + iconBox + gap + pad * 2
  const bx = W / 2 - bw / 2
  ctx.fillStyle = 'rgba(11,13,19,.72)'
  rr(ctx, bx, by, bw, bh, 9 * S)

  let cx = bx + pad
  if (iconIdx != null) {
    const im = icons && icons[iconIdx]
    if (im && im.complete !== false && (im.naturalWidth == null || im.naturalWidth)) {
      ctx.drawImage(im, cx, by + (bh - iconBox) / 2, iconBox, iconBox)
    } else {
      ctx.fillStyle = pcolor(bundle, iconIdx)
      ctx.beginPath()
      ctx.arc(cx + iconBox / 2, by + bh / 2, 3.5 * S, 0, 7)
      ctx.fill()
    }
    cx += iconBox + gap
  }
  ctx.textAlign = 'left'
  const ty = by + bh / 2 + fs * 0.34
  for (const s of segs) {
    ctx.font = font(s[2])
    ctx.fillStyle = s[1]
    ctx.fillText(s[0], cx, ty)
    cx += ctx.measureText(s[0]).width
  }
}

// ---- per-frame action readout ------------------------------------------------

// The desktop side panel (WatchLiteClip paintPanel) as canvas furniture, using
// the shared stateLabel/moveName so the phone can never drift from the labels
// the desktop shows. It takes the mid-left / mid-right edges because every
// other margin is already spoken for: HUD chips in the top corners, the
// exchange banner top-middle, the controller displays bottom-corners. The
// frame + time chip goes bottom-middle, between the two controllers.
const ROLE_RED = '#ff5470'

function paintReadout(ctx, bundle, idx, W, H, S, icons) {
  const f = bundle.frames, meta = bundle.meta
  if (!f.state) return                    // nothing to name without action states
  const sf = (meta.start_frame ?? 0) + idx
  const act = (bundle.conversions && meta.players.length === 2)
    ? activeConv(bundle, sf) : null
  const GREY = '#7b8497', DIM = '#9aa3b6'
  const fs = 9.5 * S, lh = 12.5 * S, pad = 6 * S, iconBox = 12 * S, gap = 4 * S
  const font = (b) => `${b ? 700 : 500} ${fs}px system-ui, sans-serif`

  const sides = [[], []]
  for (let i = 0; i < meta.players.length; i++) {
    const row = f.state[i]
    if (!row || row[idx] == null) continue          // port absent from this bundle
    const col = pcolor(bundle, i)
    const dir = (f.dir && f.dir[i]) ? f.dir[i][idx] : 1
    const mv = (f.move && f.move[i]) ? moveName(f.move[i][idx], meta.attack_names) : null
    const lines = [
      [`${dir < 0 ? '◀' : '▶'} ${stateLabel(row[idx])}`, col, true],
      [mv ? `last hit: ${mv}` : '—', mv ? DIM : GREY, false],
    ]
    if (act) {
      lines.push(act.actor === i
        ? ['▶ converting', col, true]
        : ['◀ being comboed', ROLE_RED, true])
    }
    const im = icons && icons[i]
    const icon = (im && im.complete !== false && (im.naturalWidth == null || im.naturalWidth))
      ? im : null
    const ind = icon ? iconBox + gap : 0
    ctx.font = font(true)
    let tw = ind + ctx.measureText(lines[0][0]).width
    for (let k = 1; k < lines.length; k++) {
      ctx.font = font(lines[k][2])
      tw = Math.max(tw, ctx.measureText(lines[k][0]).width)
    }
    // even ports left, odd right — the same side split the input displays and
    // the HUD chips use, so one player's furniture all lands on one edge
    sides[i % 2].push({
      lines, icon, right: i % 2 === 1,
      w: tw + pad * 2, h: lines.length * lh + pad * 2,
    })
  }

  const m = 8 * S, vgap = 6 * S
  for (const list of sides) {
    if (!list.length) continue
    const total = list.reduce((a, c) => a + c.h, 0) + (list.length - 1) * vgap
    // never ride up into the HUD chips / exchange banner (y 8..62 in units)
    let y = Math.max(66 * S, H / 2 - total / 2)
    for (const c of list) {
      const x = c.right ? W - m - c.w : m
      ctx.fillStyle = 'rgba(11,13,19,.72)'
      rr(ctx, x, y, c.w, c.h, 9 * S)
      ctx.textAlign = c.right ? 'right' : 'left'
      const edge = c.right ? x + c.w - pad : x + pad
      for (let k = 0; k < c.lines.length; k++) {
        const [txt, col, bold] = c.lines[k]
        const ty = y + pad + lh * k + fs
        let tx = edge
        if (k === 0 && c.icon) {
          const ix = c.right ? edge - iconBox : edge
          ctx.drawImage(c.icon, ix, ty - fs, iconBox, iconBox)
          tx = c.right ? edge - iconBox - gap : edge + iconBox + gap
        }
        ctx.font = font(bold)
        ctx.fillStyle = col
        ctx.fillText(txt, tx, ty)
      }
      y += c.h + vgap
    }
  }

  // frame + time, desktop's wlp-time verbatim (negative pre-GO frames clamp)
  const mm = Math.floor(Math.max(0, sf) / 3600)
  const ss = (Math.max(0, sf) / 60) % 60
  const label = `f${sf} · ${mm}:${ss.toFixed(1).padStart(4, '0')}`
  ctx.font = `600 ${fs}px ui-monospace, SFMono-Regular, Menlo, monospace`
  const lw = ctx.measureText(label).width
  const bw = lw + pad * 2, bh = 15 * S, bx = W / 2 - bw / 2, by = H - 8 * S - bh
  ctx.fillStyle = 'rgba(11,13,19,.72)'
  rr(ctx, bx, by, bw, bh, 7 * S)
  ctx.textAlign = 'center'
  ctx.fillStyle = '#cfd5e4'
  ctx.fillText(label, W / 2, by + bh / 2 + fs * 0.36)
  ctx.textAlign = 'left'
}

// ---- settings sheet ----------------------------------------------------------

/** Bottom sheet with the overlay toggles. `onChange(key, on)` fires after
 * each toggle persists so the caller can repaint the paused frame. */
export function overlaysSheet(onChange) {
  const sh = sheet('Player overlays')
  const render = () => {
    sh.body.innerHTML = ''
    const rows = [
      ['inputs', 'Input display'],
      ['action', 'Action readout'],
      ['readout', 'State readout'],
    ]
    // label-only rows on purpose: no icon (it rendered as a cramped
    // text-in-a-square) and no sub-line explainers
    for (const [key, label] of rows) {
      const row = sheetRow({ label, checked: overlaySettings[key] })
      row.addEventListener('click', () => {
        setOverlay(key, !overlaySettings[key])
        render()
        if (onChange) onChange(key, overlaySettings[key])
      })
      sh.body.appendChild(row)
    }
  }
  render()
  return sh
}
