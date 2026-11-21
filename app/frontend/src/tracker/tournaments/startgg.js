// start.gg profile — the user's own start.gg identity (slug). Their tournament
// results are PUBLIC, so no OAuth: we just need to know who they are, then the
// Stats "Your start.gg" panel pulls their public history via the app token.
// Persisted locally; connect/disconnect from the account page.
import { invokeEdgeFunction } from '../../shared/account/account.js'

const KEY = 'nucleus.startgg.slug'
const listeners = new Set()

/** Accept a full profile URL or a bare slug; return the slug. */
export function parseSlug(input) {
  const s = (input || '').trim()
  if (!s) return ''
  const m = s.match(/start\.gg\/user\/([A-Za-z0-9_-]+)/i)
  if (m) return m[1]
  return s.replace(/[/\s]+$/, '').replace(/^.*\//, '') // last path segment / bare slug
}

export function getStartggSlug() {
  try { return localStorage.getItem(KEY) || '' } catch { return '' }
}

export function setStartggSlug(slug) {
  try {
    if (slug) localStorage.setItem(KEY, slug)
    else localStorage.removeItem(KEY)
  } catch { /* storage unavailable */ }
  listeners.forEach(fn => { try { fn(slug) } catch { /* ignore */ } })
}

export function onStartggChange(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** Resolve a slug to the public start.gg identity (gamertag + PFP) via the
 * Supabase startgg-proxy edge function (which holds the token as a secret — it
 * never ships in the app). Cached for a day — the identity barely changes and
 * the token's rate budget is shared by every user. null if not found / not
 * configured / offline. */
const PROFILE_TTL_MS = 24 * 60 * 60 * 1000

export async function fetchStartggProfile(slug) {
  if (!slug) return null
  const key = `nucleus.startgg.profile.${slug}`
  let cached = null
  try { cached = JSON.parse(localStorage.getItem(key)) } catch { /* no cache */ }
  if (cached && Date.now() - cached.at < PROFILE_TTL_MS) return cached.data
  try {
    const data = await invokeEdgeFunction('startgg-proxy', { slug })
    try { localStorage.setItem(key, JSON.stringify({ at: Date.now(), data })) } catch { /* full */ }
    return data
  } catch {
    return cached ? cached.data : null
  }
}

// ── Tournament data (the free "Your start.gg" panel) ─────────────────────────
// Everything below is cached hard in localStorage: the proxy's start.gg token
// is rate-limited (~80 req/min SHARED across every Nucleus user), so the panel
// must cost ~0 requests on a normal open. Sets sync incrementally (updatedAfter)
// after a capped-but-resumable backfill — each sync also pulls a few older
// pages until the history (or a hard ceiling) is exhausted; standings refresh
// on a TTL. On any network failure we serve the stale cache and say so,
// instead of an empty panel.

const STANDINGS_KEY = (slug) => `nucleus.startgg.standings.${slug}`
const SETS_KEY = (slug) => `nucleus.startgg.sets.${slug}`
const STANDINGS_TTL_MS = 30 * 60 * 1000
const SETS_TTL_MS = 15 * 60 * 1000
const BACKFILL_PAGES = 8       // first sync: up to 8×25 = 200 most recent sets
const RESUME_PAGES = 4         // each later sync quietly deepens the backfill
const BACKFILL_MAX_PAGES = 40  // auto-resume stops at 40×25 = 1000 sets; the
                               // "sync older sets" button can go past it
const INCREMENTAL_PAGES = 3    // later syncs: new/updated sets since last time
const REQUEST_GAP_MS = 700     // be a polite tenant of the shared token

const readJson = (key) => {
  try { return JSON.parse(localStorage.getItem(key)) } catch { return null }
}
const writeJson = (key, value) => {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* storage full/unavailable */ }
}

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms) })

export function incrementalCursorFor(store) {
  return store.incrementalCursor || {
    updatedAfter: Math.floor(store.syncedAt / 1000) - 3600,
    nextPage: 1,
  }
}

export function advanceIncrementalCursor(store, cursor, page, totalPages) {
  cursor.totalPages = totalPages || 1
  cursor.nextPage = page + 1
  const exhausted = page >= cursor.totalPages
  if (exhausted) delete store.incrementalCursor
  else store.incrementalCursor = cursor
  return exhausted
}

/** Fold one proxy page of sets into a sets store (Melee only — the same
 * start.gg profile may enter other games). */
const mergePage = (store, page) => {
  if (page.player_id != null) store.playerId = page.player_id
  if (page.gamer_tag) store.gamerTag = page.gamer_tag
  if (page.total != null) store.total = page.total
  for (const s of page.sets || []) {
    if (s?.event?.game != null && s.event.game !== 1) continue
    if (s?.id == null) continue
    store.sets[s.id] = s
  }
}

/** The public shape of a sets store. `partial` = the backfill hasn't reached
 * the oldest set yet, so career numbers cover sets.length of total. */
const snapshot = (store) => ({
  playerId: store.playerId,
  gamerTag: store.gamerTag,
  total: store.total,
  partial: Boolean(store.incrementalCursor) || (!store.backfillDone && store.total != null
    && Object.keys(store.sets).length < store.total),
  syncedAt: store.syncedAt,
  sets: Object.values(store.sets)
    .sort((a, b) => (b.completed_at || 0) - (a.completed_at || 0)),
})

// A synchronous first paint while expired data refreshes in the background.
// These are the same slug-scoped caches used by the network fallbacks.
export function getCachedStartggData(slug) {
  const prof = readJson(`nucleus.startgg.profile.${slug}`)
  const standings = readJson(STANDINGS_KEY(slug))
  const sets = readJson(SETS_KEY(slug))
  return {
    profile: prof?.data || null,
    standings: standings ? { ...standings, stale: Date.now() - standings.syncedAt >= STANDINGS_TTL_MS } : null,
    sets: sets?.sets ? { ...snapshot(sets), stale: !sets.syncedAt || Date.now() - sets.syncedAt >= SETS_TTL_MS } : null,
  }
}

/** Continue the backfill: fetch up to `count` pages of older sets, picking up
 * after store.pagesFetched and never passing `maxPage`. Mutates the store one
 * page at a time so progress survives a mid-run network failure; flips
 * backfillDone once start.gg says there are no more pages. */
async function backfillOlder(store, slug, count, maxPage = Infinity) {
  // legacy stores (before pagesFetched existed) resume from set-count estimate
  const start = (store.pagesFetched
    || Math.ceil(Object.keys(store.sets).length / 25) || 1) + 1
  let totalPages = null
  for (let page = start; page < start + count && page <= maxPage; page += 1) {
    if (page > start) await sleep(REQUEST_GAP_MS)
    const data = await invokeEdgeFunction('startgg-proxy', { op: 'sets', slug, page })
    mergePage(store, data)
    totalPages = data.total_pages || page
    store.pagesFetched = page
    if (page >= totalPages) break
  }
  if (totalPages != null && store.pagesFetched >= totalPages) store.backfillDone = true
}

/** Recent Melee event placements (max 20, straight from start.gg).
 * Returns { standings, player_id, gamer_tag, syncedAt, stale } — `stale` means
 * the network failed and this is the last good cache. Throws only when there
 * is no cache to fall back on. */
export async function fetchStartggStandings(slug, { force = false } = {}) {
  if (!slug) return null
  const cached = readJson(STANDINGS_KEY(slug))
  if (!force && cached && Date.now() - cached.syncedAt < STANDINGS_TTL_MS) {
    return { ...cached, stale: false }
  }
  try {
    const data = await invokeEdgeFunction('startgg-proxy', { op: 'standings', slug })
    const fresh = { ...data, syncedAt: Date.now() }
    writeJson(STANDINGS_KEY(slug), fresh)
    return { ...fresh, stale: false }
  } catch (err) {
    if (cached) return { ...cached, stale: true }
    throw err
  }
}

/** The player's Melee set history, synced incrementally into localStorage.
 * Returns { playerId, gamerTag, sets (newest first), total, partial, syncedAt,
 * stale }. The first sync backfills the BACKFILL_PAGES most recent pages;
 * every later sync also resumes that backfill a few pages at a time, so a
 * long history fills in over a handful of sessions (up to BACKFILL_MAX_PAGES —
 * the "sync older sets" button goes deeper). `partial` = there are still
 * older sets not synced, so career numbers cover sets.length of total. */
const setSyncs = new Map()

export function syncStartggSets(slug, { force = false, onProgress } = {}) {
  // Mode remounts and StrictMode can request the same public history twice.
  // Share the rate-limited sync, including its latest progressive snapshot.
  let entry = setSyncs.get(slug)
  if (entry) {
    if (onProgress) {
      entry.listeners.add(onProgress)
      if (entry.latest) onProgress(entry.latest)
    }
    return entry.promise
  }
  entry = { listeners: new Set(onProgress ? [onProgress] : []), latest: null }
  setSyncs.set(slug, entry)
  entry.promise = syncSets(slug, { force, onProgress: value => {
    entry.latest = value
    for (const listener of entry.listeners) listener(value)
  } }).finally(() => { if (setSyncs.get(slug) === entry) setSyncs.delete(slug) })
  return entry.promise
}

async function syncSets(slug, { force = false, onProgress } = {}) {
  if (!slug) return null
  const key = SETS_KEY(slug)
  const store = readJson(key) || {
    playerId: null, gamerTag: null, sets: {}, total: null,
    backfillDone: false, syncedAt: 0,
  }
  const publish = () => {
    writeJson(key, store)
    onProgress?.({ ...snapshot(store), stale: false })
  }

  const fresh = store.syncedAt && Date.now() - store.syncedAt < SETS_TTL_MS
  if (!force && fresh && (store.backfillDone || Object.keys(store.sets).length)) {
    return { ...snapshot(store), stale: false }
  }

  try {
    if (!store.syncedAt || !Object.keys(store.sets).length) {
      // First sync: backfill newest -> oldest, capped.
      const first = await invokeEdgeFunction('startgg-proxy', { op: 'sets', slug, page: 1 })
      mergePage(store, first)
      store.pagesFetched = 1
      store.backfillDone = (first.total_pages || 1) <= 1
      publish()
      const pages = Math.min(first.total_pages || 1, BACKFILL_PAGES)
      for (let page = 2; page <= pages; page += 1) {
        await sleep(REQUEST_GAP_MS)
        mergePage(store, await invokeEdgeFunction('startgg-proxy', { op: 'sets', slug, page }))
        store.pagesFetched = page
        publish()
      }
      store.pagesFetched = pages
      store.backfillDone = (first.total_pages || 1) <= BACKFILL_PAGES
    } else {
      // Incremental: only sets created/updated since last sync (minus an hour
      // of slop for sets that were still being reported as we synced).
      const cursor = incrementalCursorFor(store)
      let exhausted = false
      for (let fetched = 0; fetched < INCREMENTAL_PAGES; fetched += 1) {
        const page = cursor.nextPage
        if (fetched > 0) await sleep(REQUEST_GAP_MS)
        store.incrementalCursor = cursor
        const data = await invokeEdgeFunction('startgg-proxy', {
          op: 'sets', slug, page, updatedAfter: cursor.updatedAfter,
        })
        mergePage(store, data)
        exhausted = advanceIncrementalCursor(
          store, cursor, page, data.total_pages || 1)
        writeJson(key, store)
        onProgress?.({ ...snapshot(store), stale: false })
        if (exhausted) break
      }
      // Resume the backfill: a few older pages per sync until the history
      // (or the auto ceiling) is exhausted. Best-effort — a failure here
      // must not throw away the incremental result above.
      if (!store.incrementalCursor && !store.backfillDone
          && (store.pagesFetched || 0) < BACKFILL_MAX_PAGES) {
        try {
          await sleep(REQUEST_GAP_MS)
          await backfillOlder(store, slug, RESUME_PAGES, BACKFILL_MAX_PAGES)
        } catch { /* keep the incremental progress */ }
      }
    }
    // Keep the old checkpoint while capped pages remain. The next sync resumes
    // the exact updatedAfter/page window instead of skipping unseen updates.
    if (!store.incrementalCursor) store.syncedAt = Date.now()
    writeJson(key, store)
    return { ...snapshot(store), stale: false }
  } catch (err) {
    if (Object.keys(store.sets).length || store.syncedAt) {
      return { ...snapshot(store), stale: true }
    }
    throw err
  }
}

/** Pull the NEXT chunk of older set history (the "sync older sets" button) —
 * pages continue from where the backfill stopped, so career numbers deepen
 * a chunk at a time instead of hammering the shared token. */
export async function syncMoreStartggSets(slug, extraPages = BACKFILL_PAGES) {
  if (!slug) return null
  const key = SETS_KEY(slug)
  const store = readJson(key)
  if (!store || store.backfillDone) return null
  try {
    await backfillOlder(store, slug, extraPages) // no ceiling — the user asked
  } finally {
    writeJson(key, store) // pages fetched before a failure still count
  }
  return { ...snapshot(store), stale: false }
}

/** One event's bracket sets, for the in-app bracket view. On-demand only
 * (user clicks "view bracket"), capped at 5 pages (~200 sets), and cached in
 * sessionStorage — a finished bracket never changes, and the shared token
 * budget matters more than a stale in-progress bracket. `phaseGroupIds`
 * scopes big events down to the pools/brackets the player was actually in. */
const EVENT_SETS_PAGE_CAP = 5

export async function fetchStartggEventSets(eventId, { phaseGroupIds = null } = {}) {
  const key = `nucleus.startgg.eventsets.${eventId}.${(phaseGroupIds || []).join('-')}`
  try {
    const cached = JSON.parse(sessionStorage.getItem(key))
    if (cached) return cached
  } catch { /* no cache */ }

  const merged = { event_id: eventId, name: null, total: null, sets: [], partial: false }
  let totalPages = 1
  for (let page = 1; page <= Math.min(totalPages, EVENT_SETS_PAGE_CAP); page += 1) {
    if (page > 1) await sleep(REQUEST_GAP_MS)
    const data = await invokeEdgeFunction('startgg-proxy', {
      op: 'event-sets', eventId, page, phaseGroupIds: phaseGroupIds || undefined,
    })
    totalPages = data.total_pages || 1
    merged.name = data.name ?? merged.name
    merged.total = data.total ?? merged.total
    merged.sets.push(...(data.sets || []))
  }
  merged.partial = totalPages > EVENT_SETS_PAGE_CAP
  try { sessionStorage.setItem(key, JSON.stringify(merged)) } catch { /* full */ }
  return merged
}

/** Drop the cached tournament data for a slug (used on disconnect). */
export function clearStartggCache(slug) {
  try {
    localStorage.removeItem(STANDINGS_KEY(slug))
    localStorage.removeItem(SETS_KEY(slug))
    localStorage.removeItem(`nucleus.startgg.profile.${slug}`)
  } catch { /* storage unavailable */ }
}
