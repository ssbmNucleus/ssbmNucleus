import { api, authenticatedFetch } from '../../shared/transport/api.js'
import { animCandidates } from './meleeRender.js'
import { flightPoseState } from './koFlight.js'
import { registerStageDataLoader, registerFighterDataLoader, registerItemDataLoader, registerHitDataLoader, ensureStageData, ensureReplayFighterData, ensureReplayItemData, ensureReplayHitData } from './stageData.js'

// Vite emits one collision + simulator chunk per stage. Node audits use disk.
try {
  const stages = import.meta.glob('./data/stages/*.json', { import: 'default' })
  registerStageDataLoader(id => stages[`./data/stages/${id}.json`]?.() ?? null)
  const fighters = import.meta.glob('./data/fighters/*.json', { import: 'default' })
  registerFighterDataLoader(id => fighters[`./data/fighters/${id}.json`]?.() ?? null)
  const items = import.meta.glob('./data/items/*.json', { import: 'default' })
  registerItemDataLoader(id => items[`./data/items/${id}.json`]?.() ?? null)
  const hits = import.meta.glob('./data/hits/*.json', { import: 'default' })
  registerHitDataLoader(id => hits[`./data/hits/${id}.json`]?.() ?? null)
} catch { /* Native Node has no Vite glob; its host supplies the disk loader. */ }

const API = '/api/nucleome/lite'
const packs = new Map()
const MAX_PACKS = 8
let charmapsPromise

export function pythonDeriverEnabled(storage) {
  try {
    return (storage ?? globalThis.localStorage)?.getItem('watchLite.deriver') === 'python'
  } catch { return false } // storage can be disabled in a browser preview
}

function animationNeeds(bundle, charmaps) {
  const needed = new Map()
  function add(cids, states) {
    for (let i = 0; i < (cids?.length || 0); i++) {
      const cid = cids[i], state = states?.[i]
      if (cid == null) continue
      if (!needed.has(cid)) needed.set(cid, new Set())
      // the mapped name AND its stand-in, so the renderer's fallback pose
      // (throw victims, Yoshi's shield, ...) has frames to draw
      if (state != null) for (const name of animCandidates(charmaps, cid, state)) needed.get(cid).add(name)
      // a star or screen KO draws DamageFall (koFlight)
      const ko = flightPoseState(state)
      if (ko != null) for (const name of animCandidates(charmaps, cid, ko)) needed.get(cid).add(name)
    }
  }
  const f = bundle.frames
  for (let i = 0; i < (f.cid?.length || 0); i++) add(f.cid[i], f.state?.[i])
  for (const follower of f.fol || []) add(follower.cid, follower.state)
  return needed
}

// Reuse the renderer's exact action/animation/special precedence, including
// transforms and Nana. Keep complete animation cycles, only dropping names.
export function narrowAnimations(bundle, charmaps, fullPacks) {
  const anim = {}
  for (const [cid, names] of animationNeeds(bundle, charmaps)) {
    anim[cid] = {}
    for (const name of names) {
      if (Object.hasOwn(fullPacks[cid] || {}, name)) anim[cid][name] = fullPacks[cid][name]
    }
  }
  return anim
}

export function mergeConversions(bundle, conversions) {
  const start = bundle.meta.start_frame, end = start + bundle.meta.n - 1
  return { ...bundle, conversions: bundle.meta.players.length !== 2 ? {} :
    Object.fromEntries(Object.entries(conversions || {}).map(([port, rows]) =>
      [port, rows.filter(c => c.end_frame >= start && c.start_frame <= end)])) }
}

/** The renderer's charmaps; a failed request is forgotten so the next call
 * asks again. */
export function getCharmaps() {
  if (!charmapsPromise) {
    charmapsPromise = api.get(`${API}/charmaps`).catch(error => {
      charmapsPromise = null
      throw error
    })
  }
  return charmapsPromise
}

function getPack(cid) {
  let pending = packs.get(cid)
  if (pending) packs.delete(cid) // refresh the LRU position
  else {
    pending = api.get(`${API}/pack/${cid}`).catch(error => {
      if (packs.get(cid) === pending) packs.delete(cid)
      throw error
    })
  }
  packs.set(cid, pending)
  if (packs.size > MAX_PACKS) packs.delete(packs.keys().next().value)
  return pending
}

async function derive(bytes, options) {
  let worker
  try {
    worker = new Worker(new URL('./liteDeriver/worker.js', import.meta.url), { type: 'module' })
  } catch {
    const { deriveFromSlp } = await import('./liteDeriver/index.js')
    return deriveFromSlp(bytes, options)
  }
  return new Promise((resolve, reject) => {
    const fail = error => { worker.terminate(); reject(error) }
    worker.onmessage = ({ data }) => {
      worker.terminate()
      if (data.error) {
        const error = new Error(data.error.message)
        error.name = data.error.name || 'Error'
        reject(error)
      } else resolve(data.bundle)
    }
    worker.onerror = event => fail(new Error(event.message || 'Replay worker failed'))
    worker.onmessageerror = () => fail(new Error('Replay worker returned unreadable data'))
    try { worker.postMessage({ bytes, options }, [bytes]) } catch (error) { fail(error) }
  })
}

/** Local replays derive finalized TRUE frames. */
export async function loadLiteClip({ gameId, start, end, clipRef }) {
  const clip = await loadClip({ gameId, start, end, clipRef })
  await Promise.all([ensureStageData(clip?.bundle?.meta?.stage), ensureReplayFighterData(clip?.bundle), ensureReplayItemData(clip?.bundle),
    ensureReplayHitData(clip?.bundle)])
  return clip
}

async function loadClip({ gameId, start, end, clipRef }) {
  if (pythonDeriverEnabled()) {
    return clipRef
      ? api.get(`${API}/clip-ref/${encodeURIComponent(clipRef)}`)
      : api.get(`${API}/clip/${gameId}`, { query: { start, end } })
  }
  if (clipRef) {
    const resolved = await api.get(`${API}/clip-ref/${encodeURIComponent(clipRef)}/resolve`)
    gameId = resolved.game_id; start = resolved.start_frame; end = resolved.end_frame
  }
  if (!Number.isSafeInteger(Number(gameId)) || Number(gameId) < 1) throw new Error('Invalid game id')

  const [derived, conversions, charmaps] = await Promise.all([
    (async () => {
      const response = await authenticatedFetch(api.url(`${API}/slp/${gameId}`))
      if (!response.ok) throw new Error(`Replay unavailable (HTTP ${response.status})`)
      // Match the old route: a clip requires both bounds, otherwise whole game.
      return derive(await response.arrayBuffer(), start != null && end != null ? { start, end } : {})
    })(),
    // A peppi parse failure must not prevent the JS parser playing a replay.
    api.get(`${API}/conversions/${gameId}`, { query: { conversions: 1 } }).catch(() => ({})),
    getCharmaps().catch(() => null),
  ])
  if (!derived?.meta || derived.meta.n < 2) throw new Error('Clip frames out of range for this game')
  const bundle = mergeConversions(derived, conversions)
  if (!charmaps) return { bundle, anim: {}, available: false }
  const fullPacks = Object.fromEntries(await Promise.all(
    [...animationNeeds(bundle, charmaps).keys()].map(async cid => [cid, await getPack(cid).catch(() => ({}))]),
  ))
  return { bundle, anim: narrowAnimations(bundle, charmaps, fullPacks),
    available: Object.values(fullPacks).some(pack => Object.keys(pack).length > 0) }
}
