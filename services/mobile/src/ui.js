// ui — tiny DOM helpers shared by every tab. No framework: the page is one
// esbuild IIFE and the DOM is small enough that innerHTML + delegation wins.

export const esc = (s) => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')

export function el(html) {
  const t = document.createElement('template')
  t.innerHTML = html.trim()
  return t.content.firstElementChild
}

export function toast(msg, ms = 4000) {
  const t = document.getElementById('toast')
  t.textContent = msg
  t.hidden = false
  clearTimeout(t._timer)
  t._timer = setTimeout(() => { t.hidden = true }, ms)
}

// Vanilla ships six costume slots (0-5). A modded build hands out higher ids
// — Pichu on costume 6 in this library — and Pages answers a missing asset
// with the SPA's index.html at 200, so the <img> receives 418KB of HTML, has
// no error to react to, and draws a broken box forever. Never ask for a slot
// that cannot exist.
const MAX_COSTUME = 5
export const stockSrc = (extChar, costume) => {
  const c = Number(costume)
  const slot = Number.isInteger(c) && c >= 0 && c <= MAX_COSTUME ? c : 0
  return `stock/${extChar}-${slot}.png`
}
export const stageSrc = (stageId) => `stage/${stageId}.png`

/** Slippi rank badge for a tier name ("Plat 2" -> the Platinum II icon).
 * Null means "no badge to draw": Pending is a provisional rating, not a rank,
 * and the desktop hides it the same way. Icons ship via build.py. */
export function rankSrc(tier) {
  if (!tier || tier === 'Pending') return null
  if (tier === 'Grandmaster') return 'rank/rank_Grand_Master.svg'
  const [word, num] = String(tier).split(' ')
  const roman = { 1: 'I', 2: 'II', 3: 'III' }[num]
  if (!roman) return null
  return `rank/rank_${word === 'Plat' ? 'Platinum' : word}_${roman}.svg`
}

/** onerror attribute for a stock icon: odd costume ids (modded/corrupt
 * replays) fall back to the character's default color, then hide. */
export const stockFallback = (extChar) =>
  `this.onerror=function(){this.style.visibility='hidden'};this.src='stock/${extChar}-0.png'`

/** "Aug 3" this year, "Aug 3, 2024" otherwise, with time for recency. */
export function shortDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const now = new Date()
  const opts = { month: 'short', day: 'numeric' }
  if (d.getFullYear() !== now.getFullYear()) opts.year = 'numeric'
  return d.toLocaleDateString(undefined, opts)
}

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December']
export function monthLabel(ym) {
  const [y, m] = ym.split('-')
  return `${MONTH_NAMES[Number(m) - 1] || m} ${y}`
}

export const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)
export const num = (v) => (v == null ? '—' : v.toLocaleString())

/** Bottom sheet (the vAMP pattern): backdrop + rounded panel + drag handle,
 * drag-down or backdrop-tap to dismiss. Returns {body, close} — caller fills
 * body and calls close() when an option is picked. */
export function sheet(title) {
  const backdrop = el('<div class="sheet-backdrop"></div>')
  const panel = el(`<div class="sheet">
    <div class="sheet-handle"><i></i></div>
    ${title ? `<div class="sheet-title">${esc(title)}</div>` : ''}
    <div class="sheet-body"></div>
    <button class="sheet-cancel">Cancel</button>
  </div>`)
  document.body.append(backdrop, panel)
  document.body.classList.add('no-scroll')

  let closed = false
  const close = () => {
    if (closed) return
    closed = true
    backdrop.classList.add('is-leaving')
    panel.classList.add('is-leaving')
    document.body.classList.remove('no-scroll')
    setTimeout(() => { backdrop.remove(); panel.remove() }, 220)
  }
  backdrop.addEventListener('click', close)
  panel.querySelector('.sheet-cancel').addEventListener('click', close)

  // drag-to-dismiss: follow the finger down, rubber-band up, release past 80px
  let startY = null
  panel.addEventListener('touchstart', (e) => { startY = e.touches[0].clientY }, { passive: true })
  panel.addEventListener('touchmove', (e) => {
    if (startY == null) return
    const dy = e.touches[0].clientY - startY
    panel.style.transform = `translateY(${dy < 0 ? dy * 0.15 : dy}px)`
  }, { passive: true })
  panel.addEventListener('touchend', (e) => {
    const dy = (e.changedTouches[0].clientY - startY) || 0
    startY = null
    if (dy > 80) close()
    else panel.style.transform = ''
  })

  return { body: panel.querySelector('.sheet-body'), close }
}

/** One tappable sheet row: icon (html), label, sublabel, trailing check. */
export function sheetRow({ icon = '', label, sub = '', checked = false, danger = false }) {
  return el(`<button class="sheet-row ${danger ? 'is-danger' : ''}">
    ${icon ? `<span class="sheet-row-icon">${icon}</span>` : ''}
    <span class="sheet-row-text">
      <span class="sheet-row-label">${esc(label)}</span>
      ${sub ? `<span class="sheet-row-sub">${esc(sub)}</span>` : ''}
    </span>
    ${checked ? '<span class="sheet-row-check">✓</span>' : ''}
  </button>`)
}

/** A chip that is secretly a native <select> — native pickers are the best
 * dropdown UI a phone has, so use them instead of rebuilding IconSelect. */
export function chipSelect({ label, options, value, onChange }) {
  const root = el(`<span class="chipsel" role="button"></span>`)
  const text = document.createElement('span')
  const sel = document.createElement('select')
  sel.appendChild(new Option(label, ''))
  for (const o of options) {
    const opt = new Option(o.count != null ? `${o.label} (${o.count})` : o.label, o.value)
    sel.appendChild(opt)
  }
  sel.value = value ?? ''
  const sync = () => {
    const on = sel.value !== ''
    root.classList.toggle('is-on', on)
    const chosen = options.find((o) => String(o.value) === sel.value)
    text.textContent = on && chosen ? chosen.label : label
  }
  sync()
  sel.addEventListener('change', () => { sync(); onChange(sel.value) })
  root.append(text, sel)
  return root
}
