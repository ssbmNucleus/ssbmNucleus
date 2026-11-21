// public-viewer — the runtime behind ssbmnucleus.net/replay/<id>.
//
// The sibling of share-viewer.js: same player, different source. A share
// ARTIFACT carries its data inlined and works offline; a share LINK carries
// nothing and fetches, which is what makes "every replay can have a permanent
// URL" affordable -- a link is one 12-character database row, not a rendered
// multi-megabyte file per game.
//
// Nothing here is authenticated. The id in the URL is the whole capability, so
// this file must never learn about vault tokens: it talks only to the /replay/
// endpoints the Worker exposes, and those accept an id and nothing else.
//
// Assets (packs, charmaps, stock icons) resolve through the document's
// <base href="/replay/_a/">, which the Worker proxies to the vault's Pages
// origin. Same-origin by construction, so no CORS anywhere in the path.
import { mountPlayer, snapshotComboFrame } from './share-viewer'
import { ensurePacks, fetchCharmaps, hudIcons, ensureClipStageData, shareBundle } from './api'
import { charName, stageName, formatDuration } from '../../../app/frontend/src/shared/data/meleeNames'
import { esc, stockSrc } from './ui'
import { matchCard } from './matchcard'
import { convTimeline, holdRepeat } from './detail'
import { overlaySettings, setOverlay } from './overlays'

const CFG = window.__REPLAY || {}
// Same-origin in production (the Worker serves page and data from one host).
// Overridable so the page can be driven against a deployed Worker while the
// runtime itself is served from somewhere else -- which is the only way to
// exercise this file in a browser without the production hostname.
const API = CFG.api || '/replay'

const say = (msg) => {
  const el = document.getElementById('pstatus')
  if (el) el.textContent = msg
}

async function gunzipBytes(resp) {
  const ds = new DecompressionStream('gzip')
  return new Uint8Array(await new Response(resp.body.pipeThrough(ds)).arrayBuffer())
}

async function fetchConversions(id) {
  try {
    const r = await fetch(`${API}/_c/${id}`)
    if (!r.ok) return null
    const value = JSON.parse(new TextDecoder().decode(await gunzipBytes(r)))
    return value && Array.isArray(value['0']) && Array.isArray(value['1']) ? value : null
  } catch {
    return null       // the timeline falls back to its percent heuristic
  }
}

/** "Fox (FOXY#123) vs Marth (ABC#456)" — the matchup, which is what a person
 *  scanning a chat log is actually looking for. */
function matchupOf(game) {
  const ps = game.players || []
  return ps.map((p) => {
    const who = p.code || p.name
    return who ? `${charName(p.character)} (${who})` : charName(p.character)
  }).join(' vs ')
}

// The clip window for /combo/<n>, padded so it opens before the first hit and
// lingers after the last -- a combo cut exactly to its own frames reads as a
// jump cut and hides what set it up.
const PAD_BEFORE = 45
const PAD_AFTER = 60

async function main() {
  if (!CFG.id) return say('this link is missing its id')

  let meta
  try {
    const r = await fetch(`${API}/_d/${CFG.id}`)
    if (r.status === 404) return say('this link has expired or was deleted')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    meta = await r.json()
  } catch (e) {
    return say(`could not open this replay: ${e.message}`)
  }

  const game = meta.game || {}
  const combos = meta.combos || []
  // The ordinal is 1-based in the URL because it is read by humans, and indexes
  // a list ordered by start_frame so /combo/3 means the same clip forever.
  const n = Number(CFG.combo)
  const combo = Number.isInteger(n) && n >= 1 && n <= combos.length ? combos[n - 1] : null
  if (CFG.combo != null && !combo) say('that combo is not in this game — playing the full match')

  document.title = matchupOf(game) || 'Nucleus replay'

  let bundle
  try {
    say('loading replay…')
    const conv = meta.has_conv ? fetchConversions(CFG.id) : Promise.resolve(null)
    const r = await fetch(`${API}/_b/${CFG.id}`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    bundle = await shareBundle(await gunzipBytes(r), await conv)
  } catch (e) {
    return say(`could not load this replay: ${e.message}`)
  }

  say('loading animations…')
  const [anim, charmaps, iconImgs] = await Promise.all([
    ensurePacks(bundle), fetchCharmaps(), hudIcons(bundle), ensureClipStageData(bundle.meta.stage, bundle),
  ])
  // mountPlayer takes stockIcons as URIs (the artifact inlines data URIs) and
  // loads them itself -- handing it the resolved Image objects stringifies to
  // "[object HTMLImageElement]" and every icon silently falls back to a dot.
  const stockIcons = {}
  for (const [i, img] of Object.entries(iconImgs || {})) {
    if (img) stockIcons[i] = img.src
  }
  const last = bundle.meta.n - 1
  // combo frames arrive in the bundle's frame basis (meta.start_frame-anchored,
  // normally -123); the player wants ARRAY INDICES. Every other viewer
  // subtracts start_frame — this page didn't, so every share-link combo
  // opened ~2s (123 rows) early.
  const sf = bundle.meta.start_frame ?? -123
  const lo = combo ? Math.max(0, snapshotComboFrame(bundle, combo.start_frame ?? sf) - sf - PAD_BEFORE) : 0
  const hi = combo
    ? Math.max(Math.min(last, snapshotComboFrame(bundle, combo.end_frame ?? last) - sf + PAD_AFTER), lo)
    : last

  say('')
  // the match card IS the header -- same builder, same look as the app
  const card = document.getElementById('mcard')
  // the game's permanent snapshot first (the rank they were), then whatever
  // the server's cache held -- the page itself never triggers a Slippi lookup
  const snap = game.ranks || {}
  const live = meta.ranks || {}
  const rankOf = (code) => {
    const c = String(code || '').toUpperCase()
    return snap[c] || live[c] || null
  }
  if (card) card.innerHTML = matchCard(game, rankOf)

  let tl = null
  const player = mountPlayer({
    bundle,
    anim,
    charmaps,
    stockIcons,
    lo,
    hi,
    onFrame: (idx) => { if (tl) tl.draw(bundle, idx, lo, hi, iconImgs) },
  })

  const tlEl = document.getElementById('tl')
  if (tlEl) {
    tl = convTimeline(tlEl, (frame) => {
      player.setPlaying(false)
      player.jump(frame, true)
    })
    tl.draw(bundle, player.pos(), lo, hi, iconImgs)
  }
  wireTransport(player)

  renderBelow(game, combos.map((c) => ({ ...c,
    start_frame: snapshotComboFrame(bundle, c.start_frame),
    end_frame: snapshotComboFrame(bundle, c.end_frame),
  })), n, bundle.meta.start_frame ?? -123)
}

/** Frame steps, the overlay cycle, fullscreen -- the app's transport, wired
 *  onto the handle mountPlayer returns. */
function wireTransport(player) {
  const stepb = document.getElementById('stepb')
  const stepf = document.getElementById('stepf')
  if (stepb) holdRepeat(stepb, () => { player.setPlaying(false); player.jump(player.pos() - 1, true) })
  if (stepf) holdRepeat(stepf, () => { player.setPlaying(false); player.jump(player.pos() + 1, false) })

  // The overlay button opens a menu of the three independent toggles — the
  // same three the app's overlays sheet offers, so the share page and the app
  // never drift. (It used to click-CYCLE three presets, which was fine on a
  // phone and inscrutable with a mouse: nothing said what state you were in.)
  const ovl = document.getElementById('ovl')
  if (ovl) {
    const ROWS = [
      ['inputs', 'Input display'],
      ['action', 'Action display'],
      ['readout', 'State display'],
    ]
    const sync = () => ovl.classList.toggle(
      'on', overlaySettings.inputs || overlaySettings.action || overlaySettings.readout)

    const menu = document.createElement('div')
    menu.className = 'ovlmenu'
    menu.hidden = true
    ovl.setAttribute('aria-haspopup', 'menu')
    ovl.setAttribute('aria-expanded', 'false')
    // anchored inside .transport (position:relative in the page CSS), so it
    // sits just above the button on every viewport
    ovl.parentElement.appendChild(menu)

    const render = () => {
      menu.innerHTML = ROWS.map(([key, label]) => `
        <button type="button" class="ovlrow${overlaySettings[key] ? ' on' : ''}"
                role="menuitemcheckbox" aria-checked="${!!overlaySettings[key]}"
                data-k="${key}">
          <span class="ovlrow-txt"><b>${label}</b></span>
          <span class="ovlrow-check" aria-hidden="true"></span>
        </button>`).join('')
    }
    const close = () => {
      menu.hidden = true
      ovl.setAttribute('aria-expanded', 'false')
      document.removeEventListener('pointerdown', onOutside, true)
    }
    const onOutside = (e) => {
      if (menu.contains(e.target) || ovl.contains(e.target)) return
      close()
    }
    menu.addEventListener('click', (e) => {
      const row = e.target.closest('.ovlrow')
      if (!row) return
      setOverlay(row.dataset.k, !overlaySettings[row.dataset.k])
      render()          // menu stays open — toggling one overlay rarely ends there
      sync()
      player.redraw()
    })
    ovl.addEventListener('click', () => {
      if (!menu.hidden) return close()
      render()
      menu.hidden = false
      ovl.setAttribute('aria-expanded', 'true')
      document.addEventListener('pointerdown', onOutside, true)
    })
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !menu.hidden) close()
    })
    sync()
  }

  const fs = document.getElementById('fs')
  const wrap = document.querySelector('.wrap')
  if (fs && wrap) {
    if (!wrap.requestFullscreen) fs.hidden = true    // iOS Safari
    else {
      fs.addEventListener('click', () => {
        if (document.fullscreenElement) document.exitFullscreen()
        else wrap.requestFullscreen()
      })
    }
  }
}

/** The app's game view, below the player: one combo column per player, every
 *  cell a real /combo/<n> URL. A viewer who was sent one clip is usually
 *  curious about the rest of the game -- so this is the same layout the owner
 *  sees in the app, as navigation. */
const clock = (sf, metaStart) => {
  const sec = Math.max(0, (sf - metaStart) / 60)
  return `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`
}

function comboCell(c, ordinal, current, metaStart) {
  const moves = (c.moves || []).length || c.hits || 0
  const on = ordinal === current ? ' is-active' : ''
  const pct = c.start_percent != null
    ? `${Math.round(c.start_percent)}→${Math.round(c.end_percent)}%`
    : `${moves} hits`
  const badges = (c.true_combo === true || c.did_kill)
    ? `<span class="dcombo-badges">${c.true_combo === true ? '<span class="true-badge">TRUE</span>' : ''}${c.did_kill ? '<span class="kill-badge">KILL</span>' : ''}</span>`
    : ''
  return `<a class="dcombo-cell${on}" href="/replay/${CFG.id}/combo/${ordinal}">
    <span class="dcombo-top">
      <span class="dcombo-dmg">${Math.round(c.damage || 0)}%</span>
      <span class="dcombo-time">${clock(c.start_frame, metaStart)}</span>
    </span>
    <span class="dcombo-sub">${pct}<span class="dot"> · </span>${moves} moves</span>
    ${badges}</a>`
}

function renderBelow(game, combos, current, metaStart) {
  const host = document.getElementById('combos')
  if (!host || !combos.length) return
  // only an escape hatch: with nothing selected you ARE watching the full
  // match, and a chip saying so would just be furniture
  const chip = current
    ? `<div class="chiprow"><a class="ccombo" href="/replay/${CFG.id}">View full match</a></div>`
    : ''

  const players = (game.players || []).slice(0, 2)
  let cols
  if (players.length === 2) {
    cols = players.map((p) => {
      const mine = combos.map((c, i) => [c, i + 1]).filter(([c]) => c.port === p.port)
      return `<div class="dcombo-col">
        <div class="dcombo-colhead">
          <img src="${stockSrc(p.character, p.costume)}" alt="">
          <span>${esc(p.name || p.code || charName(p.character))}</span>
          <b>${mine.length}</b>
        </div>
        ${mine.length
    ? mine.map(([c, o]) => comboCell(c, o, current, metaStart)).join('')
    : '<p class="dcombo-none">none</p>'}
      </div>`
    }).join('')
  } else {
    cols = `<div class="dcombo-col">${combos.map((c, i) => comboCell(c, i + 1, current, metaStart)).join('')}</div>`
  }
  host.innerHTML = `${chip}<div class="dcombo-cols">${cols}</div>`
  host.hidden = false
}

main()
