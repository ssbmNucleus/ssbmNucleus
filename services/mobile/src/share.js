// share — build a self-contained artifact for a game or a combo window and
// hand it to the OS share sheet (fallback: download).
//
// The artifact is ONE HTML file: viewer runtime baked in at build time, data
// injected here as base64(gzip(json)). Narrowing matters: a share carries only
// the animations its frames actually resolve to (the per-clip slice the vault
// client itself deliberately does NOT use) — a combo share lands around a
// megabyte, a whole game a few, instead of tens.
import { fetchCharmaps, call, getToken, FN_PUBLIC, fetchStockImg, cachedLibrary, accountGeneration, ensureClipStageData } from './api'
import { P as PORT_COLORS } from '../../../app/frontend/src/tracker/replays/litePaint'
import { flightPoseState } from '../../../app/frontend/src/tracker/replays/koFlight'
import { toast } from './ui'

function sliceFrames(bundle, lo, hi) {
  if (lo <= 0 && hi >= bundle.meta.n - 1) return bundle
  const cut = (arr) => (Array.isArray(arr) ? arr.map((row) => (
    Array.isArray(row) || typeof row === 'string' ? row.slice(lo, hi + 1) : row
  )) : arr)
  const frames = {}
  for (const [k, v] of Object.entries(bundle.frames)) frames[k] = cut(v)
  return {
    meta: {
      ...bundle.meta,
      n: hi - lo + 1,
      start_frame: (bundle.meta.start_frame ?? -123) + lo,
    },
    frames,
  }
}

/** Only the animations these frames resolve to, from the full packs. */
function narrowAnim(bundle, anim, renderer) {
  const need = new Map()   // cid -> Set(name)
  const f = bundle.frames
  for (let i = 0; i < f.cid.length; i++) {
    for (let idx = 0; idx < f.cid[i].length; idx++) {
      const cid = f.cid[i][idx]
      // the mapped name and the stand-ins the renderer falls back to
      const names = renderer.candidates ? renderer.candidates(cid, f.state[i][idx])
        : [renderer.animName(cid, f.state[i][idx])]
      // a star or screen KO draws DamageFall (koFlight)
      const ko = flightPoseState(f.state[i][idx])
      if (ko != null) names.push(...(renderer.candidates ? renderer.candidates(cid, ko) : [renderer.animName(cid, ko)]))
      if (!names.length || !names[0]) continue
      if (!need.has(cid)) need.set(cid, new Set())
      for (const name of names) if (name) need.get(cid).add(name)
    }
  }
  const out = {}
  for (const [cid, names] of need) {
    const full = anim[String(cid)] || {}
    out[String(cid)] = {}
    for (const nm of names) if (full[nm]) out[String(cid)][nm] = full[nm]
  }
  return out
}

async function gzipB64(text) {
  const gz = await new Response(
    new Blob([text]).stream().pipeThrough(new CompressionStream('gzip')),
  ).arrayBuffer()
  const bytes = new Uint8Array(gz)
  let bin = ''
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
  }
  return btoa(bin)
}

let tplPromise = null
function fetchTemplate() {
  if (!tplPromise) {
    tplPromise = fetch('share-template.html').then((r) => {
      if (!r.ok) throw new Error('share template unavailable')
      return r.text()
    }).catch((e) => { tplPromise = null; throw e })
  }
  return tplPromise
}

async function dataUri(url) {
  try {
    const r = await fetch(url)
    if (!r.ok) return null
    const blob = await r.blob()
    return await new Promise((res) => {
      const fr = new FileReader()
      fr.onload = () => res(fr.result)
      fr.onerror = () => res(null)
      fr.readAsDataURL(blob)
    })
  } catch { return null }
}

// per-player stock icons for the HUD (~700 B each) — the artifact has no
// network to fetch them from
async function stockDataUris(bundle) {
  const out = {}
  await Promise.all((bundle.meta.players || []).map(async (p, i) => {
    if (p.char == null) return
    out[i] = await dataUri(`stock/${p.char}-${p.costume ?? 0}.png`)
      || await dataUri(`stock/${p.char}-0.png`)
  }))
  return out
}

// Offline artifacts cannot fetch fighter tables; embed only this clip's
// fighters, and only on stages whose simulators read them (~130 KB gz each).
async function fighterTables(bundle) {
  const sd = await import('../../../app/frontend/src/tracker/replays/stageData.js')
  if (!sd.needsFighterData(bundle)) return null
  await ensureClipStageData(bundle.meta.stage, bundle)
  const out = {}
  for (const id of sd.fighterIdsFor(bundle)) {
    const data = sd.fighterDataFor(id)
    if (data) out[id] = data
  }
  return out
}

// The hit sparks' hitbox tables for this clip's fighters (~7 KB each): every
// stage, so an offline artifact draws its hits too. Their sword trails ride
// along; the Beam Sword's (~6 KB more a fighter) only when the clip has one
// (item kind 12).
async function hitTables(bundle) {
  const sd = await import('../../../app/frontend/src/tracker/replays/stageData.js')
  await ensureClipStageData(bundle.meta.stage, bundle)
  const beamSword = (bundle.items || []).some(it => it.t === 12)
  return Object.fromEntries(sd.fighterIdsFor(bundle).flatMap(id => {
    const data = sd.hitDataFor(id)
    if (!data) return []
    const { beam, ...rest } = data
    return [[id, beamSword || !beam ? data : rest]]
  }))
}

async function itemTables(bundle) {
  const sd = await import('../../../app/frontend/src/tracker/replays/stageData.js')
  if (!sd.needsItemData(bundle)) return null
  await ensureClipStageData(bundle.meta.stage, bundle)
  return Object.fromEntries(sd.itemIdsFor(bundle).flatMap(id => {
    const data = sd.itemDataFor(id)
    return data ? [[id, data]] : []
  }))
}

/** shareClip({bundle, anim, renderer, title, subtitle, lo?, hi?}) */
export async function shareClip(opts) {
  const cm = await fetchCharmaps()
  if (!cm || !opts.renderer) { toast('Character data not loaded yet — try again in a moment.'); return }
  const lo = opts.lo ?? 0
  const hi = opts.hi ?? opts.bundle.meta.n - 1

  const sliced = sliceFrames(opts.bundle, lo, hi)
  const anim = narrowAnim(sliced, opts.anim, opts.renderer)
  const payload = {
    title: opts.title, subtitle: opts.subtitle,
    bundle: sliced, anim, charmaps: cm, lo: 0, hi: sliced.meta.n - 1,
    stockIcons: await stockDataUris(sliced),
    fighters: await fighterTables(sliced),
    items: await itemTables(sliced),
    hits: await hitTables(sliced),
  }

  const [tpl, b64] = await Promise.all([
    fetchTemplate(), gzipB64(JSON.stringify(payload)),
  ])
  const html = tpl.replace('"__SHARE_B64__"', JSON.stringify(b64))
  const name = `${(opts.title || 'clip').replace(/[^\w-]+/g, '_').slice(0, 60)}.html`
  // charset matters: the receiver opens this from Files or a chat app with no
  // HTTP headers, and an undeclared encoding mangles every ·, —, and …
  const file = new File([html], name, { type: 'text/html;charset=utf-8' })

  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: opts.title })
      return
    } catch (e) {
      if (e.name === 'AbortError') return   // user closed the sheet
    }
  }
  // fallback: plain download (desktop browsers, older mobiles)
  const url = URL.createObjectURL(file)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

// ── share LINKS ────────────────────────────────────────────────────────────
// The artifact above is a file: self-contained, works offline, but it is
// megabytes and the receiver has to open a download. A link is the thing people
// actually paste into Discord, so it is the default share now; the artifact
// stays for anyone who wants the replay itself rather than a URL.
//
// Minting is idempotent server-side, so pressing share twice is one link, and
// the id survives a lapsed membership — nothing here expires.
const SITE = 'https://ssbmnucleus.net'

const mintsInFlight = new Map()

/** The permanent public URL for a game, minting it on first use. A link is
 * just a database row: the page plays the game's own file (the raw .slp when
 * the vault has it), so nothing is built or uploaded here. */
export async function shareUrl(contentHash, comboOrdinal) {
  const token = getToken(), generation = accountGeneration()
  const key = JSON.stringify([generation, token, contentHash])
  if (!mintsInFlight.has(key)) {
    mintsInFlight.set(key, (async () => {
      const current = () => {
        if (getToken() !== token || accountGeneration() !== generation) {
          throw new Error('vault account changed while sharing')
        }
      }
      const minted = await call(FN_PUBLIC, {
        action: 'mint', token, content_hash: contentHash,
      })
      current()
      return minted
    })().finally(() => { mintsInFlight.delete(key) }))
  }
  const { id } = await mintsInFlight.get(key)
  return comboOrdinal ? `${SITE}/replay/${id}/combo/${comboOrdinal}` : `${SITE}/replay/${id}`
}

// ── the unfurl picture ─────────────────────────────────────────────────────
// A VOD-style thumbnail: the two stock icons, "vs", the connect codes. Drawn
// HERE, at share time, because the client is the one place the icons exist
// next to a canvas -- a server rendering would either ship a rasterizer or
// upscale 24px pixel art into mush. Smoothing off + integer scale keeps the
// pixels square. Fire-and-forget: a share without a picture still shares.
const THUMB_W = 1200
const THUMB_H = 630
const ICON_SCALE = 7          // 24px icons -> 168px, integer so pixels stay pixels

async function drawThumb(players) {
  const ps = players.slice(0, 2)
  const imgs = await Promise.all(ps.map((p) => fetchStockImg(p.character, p.costume)))
  if (!imgs[0] && !imgs[1]) return null      // nothing to show -- skip, no blank card

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

async function pushThumb(id, game, contentHash) {
  try {
    let players = game?.players
    if (!players) {
      // theater rows carry no roster -- the library cache does
      const lib = await cachedLibrary()
      players = (lib?.games || []).find((g) => g.content_hash === contentHash)?.players
    }
    if (!players || players.length < 2) return
    const b64 = await drawThumb(players)
    if (!b64) return
    await call(FN_PUBLIC, { action: 'thumb', token: getToken(), id, png_b64: b64 })
  } catch { /* the link already went out; the picture is a bonus */ }
}

/** Hand a link to the OS share sheet, falling back to the clipboard.
 *  `text` is what rides along in the message — the matchup, so the receiver
 *  sees what they are being sent before they tap it. */
export async function shareLink({ contentHash, combo, text, game }) {
  let url
  try {
    url = await shareUrl(contentHash, combo)
  } catch (e) {
    toast(`Could not create a link: ${e.message}`)
    return
  }
  // Deliberately not awaited -- the share sheet must open in the user's
  // gesture, and the picture upload can lose that race without losing the link.
  pushThumb(url.split('/replay/')[1].split('/')[0], game, contentHash)
  // navigator.share must be called in the same gesture on iOS, but the mint is
  // a round trip -- so a failed/absent share sheet falls back to the clipboard
  // rather than losing the link the user just waited for.
  try {
    if (navigator.share) {
      await navigator.share({ title: text || 'Melee replay', text, url })
      return
    }
  } catch (e) {
    if (e && e.name === 'AbortError') return    // they closed the sheet
  }
  try {
    await navigator.clipboard.writeText(url)
    toast('Link copied')
  } catch {
    toast(url)
  }
}
