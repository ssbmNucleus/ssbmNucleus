// playback — the pieces of the replay transport that are about TIME rather
// than pixels: playback speed and the 5-second skips (tracker #93). Kept free
// of DOM/canvas imports so the math is testable under plain node.
//
// The players are frame-based, not <video>: the raf loop derives the frame from
// wall-clock since `t0`. Speed therefore scales that derivation, and anything
// that moves the playhead or changes the rate just clears `t0` so the next tick
// re-anchors from the current frame — no drift, no jump.

export const FPS = 60
export const SKIP_FRAMES = 5 * FPS
export const SPEEDS = [0.25, 0.5, 1, 1.5, 2]

// One speed for the session: pick 0.5x once and every replay you open after
// plays at 0.5x until you change it back, like a video app's speed setting.
let rate = 1
export const getRate = () => rate
export function setRate(r) {
  rate = SPEEDS.includes(r) ? r : 1
  return rate
}

export const speedLabel = (r) => `${r}×`

/** Frame to show at wall-clock `t` (ms) when playback was anchored at `t0`. */
export function frameAt(t, t0, lo, r = 1) {
  return lo + Math.floor(((t - t0) / 1000) * FPS * r)
}

/** The `t0` that makes frameAt(t, t0, lo, r) === pos — the re-anchor. */
export function anchorFor(t, pos, lo, r = 1) {
  return t - ((pos - lo) / (FPS * r)) * 1000
}

/** Where a ±5s skip lands, clamped to the playback window [lo, hi]. */
export function skipTarget(pos, dir, lo, hi) {
  return Math.max(lo, Math.min(hi, pos + dir * SKIP_FRAMES))
}

// ── controls ──────────────────────────────────────────────────────────────────
// A second, slimmer row under the transport: the main row is out of width at
// 360px (see the .transport note in template.html), and speed is a setting, not
// a per-second control, so it can live one row down.
const SKIP_ICON = (dir) => `<svg viewBox="0 0 24 24" width="22" height="22" fill="none"
  stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
  ${dir < 0
    ? '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 3.8v3.9h3.9"/>'
    : '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 3.8v3.9h-3.9"/>'}
  <text x="12" y="15.6" text-anchor="middle" font-size="8.5" font-weight="700"
    fill="currentColor" stroke="none" font-family="system-ui, sans-serif">5</text></svg>`

/** HTML for the skip/speed row. `id` prefixes the element ids ('d' / 't'). */
export function playbackRowHtml(id) {
  return `<div class="xport2">
    <button class="iconbtn stepbtn" id="${id}-skip-b" aria-label="Back 5 seconds">${SKIP_ICON(-1)}</button>
    <button class="iconbtn stepbtn" id="${id}-skip-f" aria-label="Forward 5 seconds">${SKIP_ICON(1)}</button>
    <label class="chipsel speedsel" id="${id}-speed-chip">
      <span id="${id}-speed-label">${speedLabel(rate)}</span>
      <select id="${id}-speed" aria-label="Playback speed">
        ${SPEEDS.map((r) => `<option value="${r}"${r === rate ? ' selected' : ''}>${speedLabel(r)}</option>`).join('')}
      </select>
    </label>
  </div>`
}

/** Wire the row. `onSkip(dir)` moves the playhead; `onRate()` re-anchors. */
export function wirePlaybackRow(root, id, { onSkip, onRate }) {
  root.querySelector(`#${id}-skip-b`).addEventListener('click', () => onSkip(-1))
  root.querySelector(`#${id}-skip-f`).addEventListener('click', () => onSkip(1))
  const sel = root.querySelector(`#${id}-speed`)
  const chip = root.querySelector(`#${id}-speed-chip`)
  const label = root.querySelector(`#${id}-speed-label`)
  const paint = () => {
    label.textContent = speedLabel(rate)
    chip.classList.toggle('is-on', rate !== 1)   // slow-mo should never be a surprise
  }
  sel.addEventListener('change', () => {
    setRate(Number(sel.value))
    paint()
    onRate()
  })
  paint()
}
