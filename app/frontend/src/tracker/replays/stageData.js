// Hosts supply transport; painting only reads this cache. Small collision
// tables live in stageCollision.json; simulator tables share each stage's lazy
// pack. Failures can be retried; concurrent requests share one promise.
import CORE from './data/stageCollision.json' with { type: 'json' }

let loader = null
const cached = new Map()
const pending = new Map()
const simConsumers = new Map()
let fighterLoader = null
const fighters = new Map(), fighterPending = new Map()
const bundleFighters = new WeakMap(), contactBundles = new WeakMap()
export const FIGHTER_IDS = Object.freeze(Array.from({ length: 27 }, (_, id) => id))
// Numeric manifest only; hosts fetch the actual tables on demand.
export const ITEM_IDS = Object.freeze([0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,124,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157])
const items = new Map(), itemPending = new Map(), bundleItems = new WeakMap()
let itemLoader = null
export function registerItemDataLoader(fn) { itemLoader = fn }
export function itemDataFor(kind) { return kind == null ? null : items.get(Number(kind)) || null }
export function itemIdsFor(bundle) {
  if (!bundle || typeof bundle !== 'object') return []
  if (!bundleItems.has(bundle)) {
    const ids = new Set((bundle.items || []).map(t => t.t))
    // A projectile destroyed during its constructor's collision pass has
    // no Item Update at all. Its launch motion still demands the tiny table.
    if([6,16].includes(Number(bundle.meta?.stage)))for(const [port,states] of (bundle.frames?.state||[]).entries())for(let i=0;i<states.length;i++){
      const cid=bundle.frames.cid?.[port]?.[i],state=states[i]
      if([0,21].includes(cid)&&[343,344].includes(state))ids.add(cid===0?48:49)
      if(cid===17&&[341,342].includes(state))ids.add(105)
      if(cid===4&&[399,400,431,432,512,513].includes(state))ids.add(state>=500?131:state>=431?132:130)
      if([1,22].includes(cid)&&[342,345].includes(state))ids.add(cid===1?54:55)
      if(cid===4&&[424,427,521,524].includes(state))ids.add(state<500?136:137)
      if(cid===7&&state>=341&&state<=348||cid===4&&state>=467&&state<=474)ids.add(cid===7?79:152)
    }
    // Yoshi's Island also reconstructs Jolts that hit and disappear before
    // their first Item Update. Either the flying parent or ground arc can
    // be absent, so both tiny tables follow the fighter's launch motion.
    if([6,16].includes(Number(bundle.meta?.stage)))for(const [port,states] of (bundle.frames?.state||[]).entries())for(let i=0;i<states.length;i++){
      const cid=bundle.frames.cid?.[port]?.[i]
      if([12,23].includes(cid)&&[341,342].includes(states[i])){ids.add(cid===12?89:91);ids.add(cid===12?90:92)}
      if(cid===4&&[429,430,526,527].includes(states[i])){ids.add(states[i]<500?147:149);ids.add(states[i]<500?148:150)}
      if(cid===8&&[359,363].includes(states[i]))for(const id of [69,70,71,72,73])ids.add(id)
    }
    // Slippi records only the oldest 15 items. Inishie1's 19 material items
    // fill that list before any fighter article can be born. Load only the
    // projectile kinds whose launch motions actually occur in this clip.
    if (Number(bundle.meta?.stage) === 19) {
      for (const [port, states] of (bundle.frames?.state || []).entries()) {
        for (let i = 0; i < states.length; i++) {
          const cid = bundle.frames.cid?.[port]?.[i]
          if(cid===16&&states[i]>=341&&states[i]<=350||cid===4&&states[i]>=500&&states[i]<=509)ids.add(cid===16?112:144)
          if(cid===7&&states[i]>=341&&states[i]<=348||cid===4&&states[i]>=467&&states[i]<=474)ids.add(cid===7?79:152)
          if(cid===8&&[356,357].includes(states[i])){ids.add(66);ids.add(67)}
          if(cid===8&&states[i]>=358&&states[i]<=366)for(const id of [69,70,71,72,73])ids.add(id)
          if([12,23].includes(cid)&&states[i]>=359&&states[i]<=366)ids.add(cid===12?81:82)
          if([12,23].includes(cid)&&[341,342].includes(states[i])){ids.add(cid===12?89:91);ids.add(cid===12?90:92)}
          if(cid===8&&states[i]>=348&&states[i]<=355||cid===4&&states[i]>=435&&states[i]<=442){ids.add(cid===8?68:145);ids.add(cid===8?78:146)}
          if ([0,21].includes(cid) && [343,344].includes(states[i])) ids.add(cid===0?48:49)
          if (cid===17 && [341,342].includes(states[i])) ids.add(105)
          if (cid===4 && [399,400,431,432,512,513].includes(states[i])) ids.add(states[i]>=500?131:states[i]>=431?132:130)
          if (cid===24 && [353,354].includes(states[i]) || cid===4 && [510,511].includes(states[i])) ids.add(cid===24?122:155)
          if ((cid === 1 || cid === 22) && (states[i] === 342 || states[i] === 345)) ids.add(cid === 1 ? 54 : 55)
          if (cid===4 && [424,427,521,524].includes(states[i])) ids.add(states[i]<500?136:137)
          if (cid===4 && [410,412].includes(states[i])) ids.add(151)
          if (cid===4 && [403,406,516,519].includes(states[i])) ids.add(states[i]<500?140:141)
          if (cid===4 && [429,430,526,527].includes(states[i])) {ids.add(states[i]<500?147:149);ids.add(states[i]<500?148:150)}
          if ((cid === 1 || cid === 22) && (states[i] === 348 || states[i] === 351)) ids.add(cid === 1 ? 56 : 57)
          if (cid === 13 && [346,348].includes(states[i])) ids.add(94)
          if (cid === 13 && [349,350,351,352].includes(states[i])) ids.add(95)
          if (cid === 13 && [355,356].includes(states[i])) ids.add(93)
          if ([6,20].includes(cid) && [346,349].includes(states[i])) ids.add(cid===6?64:65)
          if ([6,20].includes(cid) && [350,353].includes(states[i])) ids.add(cid===6?60:61)
          if ([6,20].includes(cid) && [358,359].includes(states[i])) ids.add(cid===6?58:59)
          if (cid===9 && [352,353].includes(states[i])) ids.add(99)
          if (cid===9 && states[i]===359) ids.add(98)
        }
      }
    }
    bundleItems.set(bundle, [...ids].filter(id => ITEM_IDS.includes(id)))
  }
  return bundleItems.get(bundle)
}
export function needsItemData(bundle, stageId = bundle?.meta?.stage) { return [6, 16, 19].includes(Number(stageId)) }
export function ensureItemData(kind) {
  const id = Number(kind)
  if (kind == null || !ITEM_IDS.includes(id)) return Promise.resolve(false)
  if (items.has(id)) return Promise.resolve(true)
  if (itemPending.has(id)) return itemPending.get(id)
  if (typeof itemLoader !== 'function') return Promise.resolve(false)
  const fetchData = itemLoader
  const request = Promise.resolve().then(() => fetchData(id)).then(data => {
    if (data?.kind !== id || !Array.isArray(data.states) || !data.animations) return false
    items.set(id, data)
    return true
  }).catch(() => false).finally(() => itemPending.delete(id))
  itemPending.set(id, request)
  return request
}
export async function ensureReplayItemData(bundle, stageId = bundle?.meta?.stage) {
  if (!needsItemData(bundle, stageId)) return true
  return (await Promise.all(itemIdsFor(bundle).map(ensureItemData))).every(Boolean)
}
export function itemDataReady(bundle) { return itemIdsFor(bundle).every(id => itemDataFor(id) !== null) }

export function registerFighterDataLoader(fn) { fighterLoader = fn }
export function fighterDataFor(cid) { return cid == null ? null : fighters.get(Number(cid)) || null }

// Several action IDs share precisely the same authored table. Numeric
// references keep those copies out of each lazy JSON asset, without rounding
// coordinates or dropping poses. Older expanded packs remain valid.
export function expandFighterData(data) {
  const out={...data}
  for(const key of ['hitboxes','ecb']) {
    const table=out[key]={...data[key]}
    for(const [state,value] of Object.entries(table))if(typeof value==='number') {
      const target=table[value]
      if(!target||typeof target!=='object')throw Error(`Invalid fighter ${key} reference ${state}`)
      table[state]=target
    }
  }
  return out
}

export function ensureFighterData(cid) {
  if (cid == null || !FIGHTER_IDS.includes(Number(cid))) return Promise.resolve(false)
  const id = Number(cid)
  if (fighters.has(id)) return Promise.resolve(true)
  if (fighterPending.has(id)) return fighterPending.get(id)
  if (typeof fighterLoader !== 'function') return Promise.resolve(false)
  const fetchData = fighterLoader
  const request = Promise.resolve().then(() => fetchData(id)).then(data => {
    if (data?.cid !== id || !Number.isFinite(data.weight) || !data.hitboxes || !data.ecb) return false
    fighters.set(id, expandFighterData(data))
    return true
  }).catch(() => false).finally(() => fighterPending.delete(id))
  fighterPending.set(id, request)
  return request
}

// Scan actual frame IDs, including both transform forms and Nana's presence
// mask. CSS IDs are a different enumeration and must not select these files.
export function fighterIdsFor(bundle) {
  if (!bundle || typeof bundle !== 'object') return []
  if (!bundleFighters.has(bundle)) {
    const f = bundle.frames, ids = new Set()
    for (const row of [...(f?.cid || []), ...(f?.fol || []).map(p => p.cid)]) {
      for (const id of row || []) if (id != null) ids.add(id)
    }
    bundleFighters.set(bundle, [...ids])
  }
  return bundleFighters.get(bundle)
}
// The hit sparks' small per-fighter hitbox tables (data/hits/<cid>.json, from
// tools/liteaudit/hit_tables.mjs): every replay, every stage. Hosts register
// the transport; hitSparks.js only reads this cache.
let hitLoader = null
const hits = new Map(), hitPending = new Map()
export function registerHitDataLoader(fn) { hitLoader = fn }
export function hitDataFor(cid) { return cid == null ? null : hits.get(Number(cid)) || null }
export function ensureHitData(cid) {
  if (cid == null || !FIGHTER_IDS.includes(Number(cid))) return Promise.resolve(false)
  const id = Number(cid)
  if (hits.has(id)) return Promise.resolve(true)
  if (hitPending.has(id)) return hitPending.get(id)
  if (typeof hitLoader !== 'function') return Promise.resolve(false)
  const fetchData = hitLoader
  const request = Promise.resolve().then(() => fetchData(id)).then(data => {
    if (data?.cid !== id || !data.states || typeof data.states !== 'object') return false
    hits.set(id, data)
    return true
  }).catch(() => false).finally(() => hitPending.delete(id))
  hitPending.set(id, request)
  return request
}
export async function ensureReplayHitData(bundle) {
  return (await Promise.all(fighterIdsFor(bundle).filter(id => FIGHTER_IDS.includes(Number(id))).map(ensureHitData))).every(Boolean)
}
// Custom (m-ex) fighters have no table; they never block the vanilla ones.
export function hitDataReady(bundle) {
  return fighterIdsFor(bundle).every(id => !FIGHTER_IDS.includes(Number(id)) || hitDataFor(id) !== null)
}

// Only these simulators read fighter weights/hitboxes/ECBs; other stages never
// download the (large) per-fighter tables.
export const FIGHTER_STAGE_IDS = Object.freeze([4, 6, 11, 13, 16, 17, 19])
export function needsFighterData(bundle, stageId = bundle?.meta?.stage) {
  return FIGHTER_STAGE_IDS.includes(Number(stageId))
}
export async function ensureReplayFighterData(bundle, stageId = bundle?.meta?.stage) {
  if (!needsFighterData(bundle, stageId)) return true
  return (await Promise.all(fighterIdsFor(bundle).map(ensureFighterData))).every(Boolean)
}
export function fighterDataReady(bundle) {
  return fighterIdsFor(bundle).every(id => fighterDataFor(id) !== null)
}

// Contact/attack adapters use one column per entity. Preserve the original
// bundle for RNG record ordering; absence stays null, never a fighter at (0,0).
export function fighterFrames(bundle) {
  if (!contactBundles.has(bundle)) {
    const f = bundle.frames, result = { ...f, fol: [] }
    for (const key of ['x','y','air','state','age','cid','dir','pct','pre_state','seed_order']) {
      result[key] = [...(f[key] || []), ...(f.fol || []).map(p => p[key])]
    }
    contactBundles.set(bundle, result)
  }
  return contactBundles.get(bundle)
}
export function supportedFighterHistory(bundle, idx, stage) {
  const n = bundle?.meta?.n, frames = bundle?.frames
  if (Number(bundle?.meta?.stage) !== stage || bundle.meta.start_frame !== -123 ||
      !Number.isInteger(idx) || idx < 0 || idx >= n || !frames?.x?.length) return false
  const f = fighterFrames(bundle)
  return ['x','y','air','state','age','cid'].every(k =>
    f[k]?.length === f.x.length && f[k].every(a => a?.length === n))
}

// Stages with DAT simulator tables (including ports not currently drawn).
export const STAGE_SIM_IDS = Object.freeze([2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 15, 16, 17, 18, 19, 20, 22, 24, 25, 27, 29])

// Initialize data-derived constants only after the table arrives. Registration
// also works after loading, as in Node audits and dynamically imported ports.
export function registerStageSimData(stageId, receive) {
  const id = String(stageId)
  if (!simConsumers.has(id)) simConsumers.set(id, new Set())
  simConsumers.get(id).add(receive)
  const sim = cached.get(id)?.sim
  if (sim) receive(sim)
}

export function registerStageDataLoader(fn) {
  loader = fn
}

export function stageDataFor(stageId) {
  return cached.get(String(stageId)) || null
}

export function ensureStageData(stageId) {
  const id = String(stageId)
  if ((!CORE.stages[id]?.deferred && !STAGE_SIM_IDS.includes(Number(id))) || cached.has(id)) return Promise.resolve(true)
  if (pending.has(id)) return pending.get(id)
  if (typeof loader !== 'function') return Promise.resolve(false)
  const fetchData = loader
  const request = Promise.resolve().then(() => fetchData(Number(id))).then(data => {
    if (!data || typeof data !== 'object') return false
    if (STAGE_SIM_IDS.includes(Number(id)) && (!data.sim || typeof data.sim !== 'object')) return false
    for (const receive of simConsumers.get(id) || []) receive(data.sim)
    cached.set(id, data)
    return true
  }).catch(() => false).finally(() => pending.delete(id))
  pending.set(id, request)
  return request
}
