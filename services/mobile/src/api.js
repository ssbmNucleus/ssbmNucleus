// api — everything that talks to the network, plus the local library cache.
//
// The design inversion that makes this client work: the phone pulls the WHOLE
// game list once (compact meta rows, ~300 B each) and browses/filters/sorts
// locally, exactly like the desktop does over its SQLite index. Only clip
// frame data and animation packs stream on demand.

import {
  cacheForGeneration, cacheValueForGeneration, fetchAccountPages,
  generationFor, replaceToken, tokenFor,
} from './account-generation'
import { deriveClip } from './derive-worker'

// build.py pins immutable stage assets alongside the replay runtime. Resolve
// relative to the page's asset base (also used by public /replay/ pages).
const stageFiles = typeof __STAGE_DATA_FILES__ !== 'undefined' ? __STAGE_DATA_FILES__ : Object.fromEntries(
  [2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 15, 16, 17, 18, 19, 20, 22, 23, 24, 25, 27, 29]
    .map(id => [id, `stages/${id}.json`]),
)
let stageModule
const fighterFiles = typeof __FIGHTER_DATA_FILES__ !== 'undefined' ? __FIGHTER_DATA_FILES__ : Object.fromEntries(
  Array.from({ length: 27 }, (_, id) => [id, `fighters/${id}.json`]),
)
const itemFiles = typeof __ITEM_DATA_FILES__ !== 'undefined' ? __ITEM_DATA_FILES__ : Object.fromEntries(
  Array.from({ length: 256 }, (_, id) => [id, `items/${id}.json`]),
)
// The hit sparks' small per-fighter hitbox tables (every replay).
const hitFiles = typeof __HIT_DATA_FILES__ !== 'undefined' ? __HIT_DATA_FILES__ : Object.fromEntries(
  Array.from({ length: 27 }, (_, id) => [id, `hits/${id}.json`]),
)
async function replayDataModule() {
  if (!stageModule) stageModule = import('../../../app/frontend/src/tracker/replays/stageData.js').then(module => {
    module.registerStageDataLoader(async id => {
      const url = stageFiles[id]
      if (!url) return null
      const response = await fetch(url)
      if (!response.ok) throw new Error(`stage data fetch ${response.status}`)
      return response.json()
    })
    module.registerFighterDataLoader(async id => {
      const url = fighterFiles[id]
      if (!url) return null
      const response = await fetch(url)
      if (!response.ok) throw new Error(`fighter data fetch ${response.status}`)
      return response.json()
    })
    module.registerItemDataLoader(async id => {
      const url = itemFiles[id]
      if (!url) return null
      const response = await fetch(url)
      if (!response.ok) throw new Error(`item data fetch ${response.status}`)
      return response.json()
    })
    module.registerHitDataLoader(async id => {
      const url = hitFiles[id]
      if (!url) return null
      const response = await fetch(url)
      if (!response.ok) throw new Error(`hit data fetch ${response.status}`)
      return response.json()
    })
    return module
  }).catch(error => { stageModule = null; throw error })
  return stageModule
}
export async function ensureClipStageData(stageId, bundle) {
  try {
    const module = await replayDataModule()
    return (await Promise.all([module.ensureStageData(stageId), module.ensureReplayFighterData(bundle, stageId), module.ensureReplayItemData(bundle, stageId),
      module.ensureReplayHitData(bundle)])).every(Boolean)
  } catch { return false }
}

const CFG = window.__VAULT || {}
const FN_READ = `${CFG.supabaseUrl}/functions/v1/vault-read`
const FN_STARTGG = `${CFG.supabaseUrl}/functions/v1/startgg-proxy`
// Public share links: mint (owner) and the page's own read (anyone). Exported
// because share.js mints through it directly -- it is not a vault read.
export const FN_PUBLIC = `${CFG.supabaseUrl}/functions/v1/vault-public`

export const accountGeneration = () => generationFor()
export const getToken = () => tokenFor()
export const setToken = (token) => replaceToken(token)

export async function call(url, payload) {
  const r = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      apikey: CFG.anonKey,
      Authorization: `Bearer ${CFG.anonKey}`,
    },
    body: JSON.stringify(payload),
  })
  const out = await r.json().catch(() => ({}))
  if (!r.ok || out.error) throw new Error(out.error || `HTTP ${r.status}`)
  return out
}

const versionedRead = (payload) => ({
  ...payload,
  ...(['urls', 'list'].includes(payload.action) ? { v: 2 } : {}),
})
export const vaultRead = (payload) => call(FN_READ, { ...versionedRead(payload), token: getToken() })
// startgg-proxy is public (start.gg identity is public data) — no vault token.
export const startgg = (payload) => call(FN_STARTGG, payload)

// ── the library cache ──────────────────────────────────────────────────────
// IndexedDB, one kv store. localStorage caps at ~5 MB which a 20k-game
// library's meta would exceed; IDB holds it comfortably.

const DB_NAME = 'nucleus-vault'
let dbPromise = null

function idb() {
  if (!dbPromise) {
    dbPromise = new Promise((res, rej) => {
      const req = indexedDB.open(DB_NAME, 1)
      req.onupgradeneeded = () => req.result.createObjectStore('kv')
      req.onsuccess = () => res(req.result)
      req.onerror = () => rej(req.error)
    })
  }
  return dbPromise
}

async function kvGet(key) {
  try {
    const db = await idb()
    return await new Promise((res) => {
      const rq = db.transaction('kv').objectStore('kv').get(key)
      rq.onsuccess = () => res(rq.result)
      rq.onerror = () => res(undefined)
    })
  } catch { return undefined }
}

async function kvSet(key, value) {
  try {
    const db = await idb()
    await new Promise((res) => {
      const tx = db.transaction('kv', 'readwrite')
      tx.objectStore('kv').put(value, key)
      tx.oncomplete = res
      tx.onerror = res
    })
  } catch { /* quota/private mode — the session still works from memory */ }
}

export async function cachedLibrary() {
  return cacheValueForGeneration(await kvGet('library'), accountGeneration())
}

/** Crawl the whole vault (id-keyset pages of 1000) and cache it.
 * onPage(count, gamesSoFar) fires after every page. */
export async function fetchLibrary(onPage) {
  const token = getToken()
  const generation = accountGeneration()
  const games = await fetchAccountPages({
    readPage: (payload) => call(FN_READ, versionedRead(payload)), token, generation, onPage,
    isCurrent: (expectedToken, expectedGeneration) =>
      getToken() === expectedToken && accountGeneration() === expectedGeneration,
  })
  const lib = { games, fetched_at: Date.now() }
  kvSet('library', cacheForGeneration(lib, generation))
  return lib
}

// ── combos: a server query, not a cached corpus ────────────────────────────
// Games are pulled whole because their meta is ~300 B a row; combos are not.
// One measured vault holds 246,671 of them — tens of megabytes — so the tab
// asks the server per filter change and pages through the answer, exactly as
// the desktop's CombosPage does. Anything the phone filtered locally would be
// a slice of the library wearing the whole library's numbers.

export const COMBO_PAGE = 50        // rows per request (server caps at 100)

/** One page of the combo library. {filters, sort, dir, limit, offset} -> {combos} */
export async function queryCombos({
  filters, sort, dir, limit = COMBO_PAGE, offset = 0,
} = {}) {
  const out = await vaultRead({
    action: 'combos',
    filters: filters || {},
    sort,
    ...(dir ? { dir } : {}),
    limit,
    offset,
  })
  return { combos: out.combos || [] }
}

/** How many combos match, as its own request. Counting a broad filter is a
 * scan of the whole matching set — seconds — and bundling it with the page
 * made the LIST wait on a number the reader glances at once. Fire and forget:
 * the header fills in when it lands, or stays quiet if it never does. */
export async function countCombos({ filters, sort, dir } = {}) {
  const out = await vaultRead({
    action: 'combos', count_only: true, filters: filters || {}, sort,
    ...(dir ? { dir } : {}),
  })
  return out.total ?? null
}

// Only the FIRST page of ONE query is cached, so the tab paints instantly (and
// offline) on the view it opens on. Keyed by the filter+sort signature: a
// cached page for a different query is not an approximation of this one, it is
// the wrong answer, so it is simply ignored.
const COMBO_PAGE_KEY = 'combos-page1'

export async function cachedComboPage(sig) {
  const hit = await kvGet(COMBO_PAGE_KEY)
  const value = cacheValueForGeneration(hit, accountGeneration())
  return value?.sig === sig ? value : null
}
export function saveComboPage(sig, combos, total) {
  kvSet(COMBO_PAGE_KEY, cacheForGeneration(
    { sig, combos, total, fetched_at: Date.now() }, accountGeneration()))
}

// LEGACY — main.js still pulls a combo corpus into `store.combos` for
// Randall's local tools (randall.js toolListCombos). The Combos tab no longer
// uses either of these; once Randall queries the vault the same way, both this
// pair and the `combos` IDB entry can go.
export async function fetchCombos() {
  const generation = accountGeneration()
  const all = await vaultRead({ action: 'combos', limit: 1000 })
  if (generation !== accountGeneration()) throw new Error('vault account changed during combo refresh')
  const lib = { combos: all.combos || [], fetched_at: Date.now() }
  kvSet('combos', cacheForGeneration(lib, generation))
  return lib
}
export async function cachedCombos() {
  return cacheValueForGeneration(await kvGet('combos'), accountGeneration())
}

// ── clip payloads + animation packs ───────────────────────────────────────

async function gunzipJson(resp) {
  const ds = new DecompressionStream('gzip')
  const text = await new Response(resp.body.pipeThrough(ds)).text()
  return JSON.parse(text)
}

// The build substitutes the content-hashed, same-directory worker filename.
const DERIVE_WORKER_URL = typeof __DERIVE_WORKER_URL__ === 'string'
  ? __DERIVE_WORKER_URL__ : './derive-worker.js'

async function deriveRaw(bytes) {
  try {
    return await new Promise((resolve, reject) => {
      const worker = new Worker(DERIVE_WORKER_URL)
      const finish = (error, result) => {
        clearTimeout(timer)
        worker.terminate()
        error ? reject(error) : resolve(result)
      }
      const timer = setTimeout(() => finish(new Error('replay worker timed out')), 30000)
      worker.onmessage = ({ data }) => {
        if (data?.error) finish(new Error(data.error))
        else if (!data?.bundle?.meta || !data?.rowFids) finish(new Error('invalid replay worker response'))
        else finish(null, data)
      }
      worker.onerror = (event) => {
        event.preventDefault?.()
        finish(new Error(event.message || 'replay worker failed'))
      }
      worker.onmessageerror = () => finish(new Error('replay worker message failed'))
      try {
        // Keep the original for a main-thread retry if loading/cloning fails.
        const copy = bytes.slice()
        worker.postMessage(copy, [copy.buffer])
      } catch (error) { finish(error) }
    })
  } catch {
    // Workers can be disabled or blocked by a stale cache/CSP on a phone.
    return deriveClip(bytes)
  }
}

/** Whole-game derive of raw .slp bytes, off the UI thread when it can be.
 * The phone's vault and the public /replay/ page both play through this. */
export async function deriveSlpBytes(bytes) {
  const result = await deriveRaw(bytes)
  if (!result.bundle.meta.n || !result.rowFids.length) throw new Error('replay has no frames')
  return result
}

// Every Slippi file opens with the UBJSON header `{U\x03raw`. A frames file
// (games uploaded before raw replays) is JSON and opens with `{"`.
const SLP_MAGIC = [0x7b, 0x55, 0x03, 0x72, 0x61, 0x77]
export const isSlp = (bytes) => SLP_MAGIC.every((b, i) => bytes[i] === b)

/** A public share's game as a playable bundle, from its decompressed bytes.
 * A raw .slp is worked out with the same code the vault uses, so a link plays
 * with whatever the viewer can do today. Its combos stay ROW-basis, so the row
 * map rides along in meta exactly as share-viewer's snapshotComboFrame reads it. */
export async function shareBundle(bytes, conversions = null) {
  if (!isSlp(bytes)) {
    const raw = JSON.parse(new TextDecoder().decode(bytes))
    return raw.bundle || raw
  }
  const { bundle, rowFids, firstFrame } = await deriveSlpBytes(bytes)
  bundle.meta.row_fids = rowFids
  bundle.meta.row_first = firstFrame ?? bundle.meta.start_frame
  // TRUE frames, matching this finalized bundle (the vault's rule too).
  bundle.conversions = conversions
  return bundle
}

/** Cloud combo frames are always ROW-basis. Only whole-game raw clips use
 * the finalized timeline; firstFrame anchors rowFids even across rollbacks.
 * Keep the cloud row unchanged (share ordinals/focus matching depend on it). */
export function comboFrame(clip, rowFrame) {
  if (clip?.source !== 'slp' || !clip.bundle.meta.finalized) return rowFrame
  const { rowFids, firstFrame = clip.bundle.meta.start_frame } = clip
  if (!rowFids?.length) throw new Error('raw clip missing row frame map')
  const index = Math.max(0, Math.min(rowFids.length - 1, Math.trunc(rowFrame - firstFrame)))
  return rowFids[index]
}

// LRU, not unbounded: each entry is a whole decompressed multi-MB game
// bundle, and a "Play all" session used to pin every game it ever touched —
// memory pressure -> GC pauses -> the "replays lag sometimes" report. Four
// keeps current + prefetched + a couple of back-swipes resident.
const clipCache = new Map()   // content_hash -> {bundle, source, rowFids?} promise (LRU order)
const CLIP_CACHE_MAX = 4

export function fetchClip(contentHash) {
  if (clipCache.has(contentHash)) {
    const hit = clipCache.get(contentHash)
    clipCache.delete(contentHash)      // re-insert = mark most recently used
    clipCache.set(contentHash, hit)
    return hit
  }
  const promise = (async () => {
    const { urls } = await vaultRead({ action: 'urls', content_hashes: [contentHash] })
    const entry = urls && urls[contentHash]
    // An older server ignores v:2 and still returns a flat frames URL.
    const paths = typeof entry === 'string' ? { frames: entry } : entry
    if (!paths?.slp && !paths?.frames) throw new Error('clip not in vault')
    if (paths.slp) {
      try {
        // Start both reads together. A missing/bad sidecar must not lose
        // playback; null retains the percent-delta overlay fallback.
        const conv = paths.conv ? fetch(paths.conv).then((r) => {
          if (!r.ok) throw new Error(`conversions fetch ${r.status}`)
          return gunzipJson(r)
        }).then((value) => {
          if (!value || !Array.isArray(value['0']) || !Array.isArray(value['1'])) return null
          return value
        }).catch(() => null) : Promise.resolve(null)
        const r = await fetch(paths.slp)
        if (!r.ok) throw new Error(`replay fetch ${r.status}`)
        const bytes = new Uint8Array(await new Response(
          r.body.pipeThrough(new DecompressionStream('gzip')),
        ).arrayBuffer())
        const result = await deriveSlpBytes(bytes)
        // Sidecars are already TRUE frames, matching this finalized bundle.
        result.bundle.conversions = await conv
        return { ...result, source: 'slp' }
      } catch (error) {
        if (!paths.frames) throw error
        // A damaged/unavailable raw object can still have a playable snapshot.
      }
    }
    const r = await fetch(paths.frames)
    if (!r.ok) throw new Error(`clip fetch ${r.status}`)
    const raw = await gunzipJson(r)
    return { bundle: raw.bundle || raw, source: 'frames' }
  })().then(async clip => {
    await ensureClipStageData(clip.bundle.meta.stage, clip.bundle)
    return clip
  }).catch((e) => {
    // An evicted request must not delete a newer request for the same hash.
    if (clipCache.get(contentHash) === promise) clipCache.delete(contentHash)
    throw e
  })
  clipCache.set(contentHash, promise)
  while (clipCache.size > CLIP_CACHE_MAX) {
    clipCache.delete(clipCache.keys().next().value)
  }
  return promise
}

let charmapsPromise = null
export function fetchCharmaps() {
  if (!charmapsPromise) {
    charmapsPromise = fetch('charmaps.json').then((r) => {
      if (!r.ok) throw new Error('charmaps unavailable')
      return r.json()
    }).catch(() => null)
  }
  return charmapsPromise
}

export const prefsGet = () => vaultRead({ action: 'prefs-get' })
export const prefsSet = (prefs) => vaultRead({ action: 'prefs-set', ...prefs })

// Randall's chat threads live in the vault so every paired device sees them.
// Offline-first by design: the phone always works from localStorage and these
// two calls are the reconcile — nothing here blocks sending a message.
export const chatsGet = () => vaultRead({ action: 'chats-get' })
export const chatsPut = (threads, deleted) => vaultRead({
  action: 'chats-put', threads, ...(deleted?.length ? { deleted } : {}),
})

// ── Slippi ranks ──────────────────────────────────────────────────────────
// Ranks come from an UNOFFICIAL slippi.gg endpoint, and one measured library
// holds 2,660 distinct connect codes — an infinite scroll that looked up every
// code it passed would be thousands of calls a day from one phone. So the
// client is deliberately stingy:
//   * a code is asked about AT MOST ONCE per session, hit or miss;
//   * a session asks about at most MAX_RANK_SESSION codes, ever — past that,
//     rows simply show no badge, which is the same thing an unranked player
//     shows and nobody reads as broken.
// The server cache (14 days for opponents) is what makes the rest cheap.

const MAX_RANK_BATCH = 50         // the edge function's own cap
const MAX_RANK_SESSION = 60       // codes one app session may ever look up
const rankCache = new Map()       // CODE -> rank object | null
const rankAskedCodes = new Set()  // asked, answered or not — never asked again

/** Cached rank for a code, or undefined when there is no answer to draw. */
export const cachedRank = (code) => rankCache.get(String(code || '').toUpperCase())

/** Has this session already spent a lookup on this code? A slot whose code is
 * "asked" is settled: no answer is ever coming, so stop collecting it. */
export const rankAsked = (code) => rankAskedCodes.has(String(code || '').toUpperCase())

/** Look up whatever of `codes` this session hasn't already spent a lookup on,
 * within the session budget. Resolves true if anything new arrived. */
export async function fetchRanks(codes) {
  const budget = MAX_RANK_SESSION - rankAskedCodes.size
  if (budget <= 0) return false
  const want = [...new Set(codes
    .filter((c) => c && c.includes('#'))
    .map((c) => c.toUpperCase()))]
    .filter((c) => !rankAskedCodes.has(c))
    .slice(0, budget)
  if (!want.length) return false
  // Spend the budget up front: an overlapping render must not re-ask these,
  // and a failed request must not free them for a retry loop.
  want.forEach((c) => rankAskedCodes.add(c))
  let grew = false
  try {
    for (let i = 0; i < want.length; i += MAX_RANK_BATCH) {
      const batch = want.slice(i, i + MAX_RANK_BATCH)
      const out = await vaultRead({ action: 'ranks', codes: batch })
      for (const c of batch) rankCache.set(c, (out.ranks && out.ranks[c]) || null)
      grew = true
    }
  } catch { /* offline or Slippi down — these codes just stay badge-less */ }
  return grew
}

const stockImgCache = new Map()   // "ext-costume" -> Image promise
export function fetchStockImg(extChar, costume) {
  // same clamp as ui.stockSrc: a modded costume slot has no shipped icon and
  // Pages answers the miss with index.html at 200, not a 404
  const slot = Number.isInteger(Number(costume)) && Number(costume) >= 0
    && Number(costume) <= 5 ? Number(costume) : 0
  const key = `${extChar}-${slot}`
  if (!stockImgCache.has(key)) {
    stockImgCache.set(key, new Promise((res) => {
      const img = new Image()
      img.onload = () => res(img)
      // costume fallback then give up — the HUD draws a colored dot instead
      img.onerror = () => {
        if (img.src.endsWith(`/${extChar}-0.png`) || (costume ?? 0) === 0) res(null)
        else { img.src = `stock/${extChar}-0.png` }
      }
      img.src = `stock/${extChar}-${slot}.png`
    }))
  }
  return stockImgCache.get(key)
}

/** Stock-icon Images for a bundle's players, HUD-ready ({index: Image}). */
export async function hudIcons(bundle) {
  const out = {}
  await Promise.all((bundle.meta.players || []).map(async (p, i) => {
    if (p.char == null) return
    out[i] = await fetchStockImg(p.char, p.costume)
  }))
  return out
}

// One game's combos for the detail sheet. A single game's set is bounded (tens
// of rows), so this asks for all of them and orders them in play order here —
// the server keeps the 1000-row ceiling for game-scoped reads.
export function combosForGame(gameId) {
  return vaultRead({ action: 'combos', game_id: gameId, limit: 1000 })
    .then((out) => (out.combos || [])
      // id tiebreak matches vault-public's /combo/N ordering, so a trade's
      // two same-frame combos number identically here and on share pages
      .sort((a, b) => ((a.start_frame || 0) - (b.start_frame || 0))
        || ((a.id || 0) - (b.id || 0))))
}

const packCache = new Map()   // internal cid -> {animName: frames} promise

export function fetchPack(cid) {
  if (!packCache.has(cid)) {
    packCache.set(cid, fetch(`packs/char-${cid}.json.gz`).then((r) => {
      if (!r.ok) throw new Error(`pack ${cid} unavailable`)
      // Pages serves the pre-gzipped body as-is (Content-Encoding is not set
      // for .gz assets), so inflate explicitly.
      return gunzipJson(r)
    }).then((obj) => obj[String(cid)] || {}).catch(() => ({})))
  }
  return packCache.get(cid)
}

/** Animation object for every character appearing in this bundle's frames,
 * shaped exactly like the desktop clip payload's `anim`: {cid: {name: [...]}} */
export async function ensurePacks(bundle) {
  const cids = new Set()
  for (const row of [...(bundle.frames.cid || []), ...(bundle.frames.fol || []).map(f => f.cid)])
    for (const cid of row || []) if (cid != null) cids.add(cid)
  const anim = {}
  await Promise.all([ensureClipStageData(bundle.meta.stage, bundle), ...[...cids].map(async (cid) => {
    anim[String(cid)] = await fetchPack(cid)
  })])
  return anim
}
