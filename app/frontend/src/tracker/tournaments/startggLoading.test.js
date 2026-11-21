import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

// Exercise the actual service with only its external edge client/storage/clock
// boundary replaced. No Supabase session, network request or real cache is used.
let fixtureId = 0
async function service() {
  const source = await readFile(new URL('./startgg.js', import.meta.url), 'utf8')
  const boundary = "import { invokeEdgeFunction } from '../../shared/account/account.js'"
  assert.ok(source.includes(boundary))
  const stub = `
    export const fixture = { storage: new Map(), waits: [], invoke: () => { throw Error('Unexpected request') } };
    const invokeEdgeFunction = (...args) => fixture.invoke(...args);
    const localStorage = {
      getItem: key => fixture.storage.get(key) || null,
      setItem: (key, value) => fixture.storage.set(key, value),
      removeItem: key => fixture.storage.delete(key),
    };
    const setTimeout = (callback, ms) => fixture.waits.push({ callback, ms });
  `
  return import(`data:text/javascript,${encodeURIComponent(source.replace(boundary, stub) + `\n// fixture ${fixtureId++}`)}`)
}
const tick = async () => { await Promise.resolve(); await Promise.resolve() }
const page = (n, total = 2) => ({ player_id: 7, gamer_tag: 'Fixture', total,
  total_pages: total, sets: [{ id: n, completed_at: 100 - n, event: { game: 1 } }] })

test('first page is visible and persisted before the polite backfill delay; duplicate mounts share the sync', async () => {
  const { fixture, syncStartggSets, getCachedStartggData } = await service()
  const requests = [], firstProgress = [], secondProgress = []
  fixture.invoke = async (_name, args) => { requests.push(args.page); return page(args.page) }
  const first = syncStartggSets('fixture', { onProgress: p => firstProgress.push(p) })
  await tick()
  assert.equal(firstProgress[0].sets.length, 1)
  assert.equal(firstProgress[0].partial, true)
  assert.deepEqual(requests, [1])
  assert.equal(fixture.waits[0].ms, 700)
  assert.equal(getCachedStartggData('fixture').sets.sets.length, 1)
  const second = syncStartggSets('fixture', { onProgress: p => secondProgress.push(p) })
  assert.equal(first, second)
  assert.equal(secondProgress[0].sets.length, 1)
  fixture.waits.shift().callback()
  const completed = await first
  assert.deepEqual(requests, [1, 2])
  assert.equal(completed.sets.length, 2)
  assert.equal(completed.partial, false)
  assert.equal(completed.stale, false)
  assert.ok(completed.syncedAt > 0)
})

test('a later page failure preserves the displayed first page as stale recoverable history', async () => {
  const { fixture, syncStartggSets, getCachedStartggData } = await service()
  fixture.invoke = async (_name, args) => {
    if (args.page === 2) throw new Error('Offline during backfill')
    return page(1)
  }
  const pending = syncStartggSets('fixture')
  await tick()
  fixture.waits.shift().callback()
  const result = await pending
  assert.equal(result.stale, true)
  assert.equal(result.partial, true)
  assert.deepEqual(result.sets.map(s => s.id), [1])
  assert.deepEqual(getCachedStartggData('fixture').sets.sets.map(s => s.id), [1])
})

test('slug caches stay separate and a fresh history performs no request', async () => {
  const { fixture, syncStartggSets, getCachedStartggData } = await service()
  fixture.storage.set('nucleus.startgg.sets.saved', JSON.stringify({
    sets: { 1: page(1).sets[0] }, syncedAt: Date.now(), backfillDone: true, total: 1,
  }))
  assert.equal((await syncStartggSets('saved')).sets.length, 1)
  assert.equal(getCachedStartggData('other').sets, null)
  assert.equal(fixture.waits.length, 0)
})

test('an eight-page cold history paints before all 4900ms of scheduled rate-limit gaps', async () => {
  const { fixture, syncStartggSets } = await service()
  fixture.invoke = async (_name, args) => page(args.page, 8)
  let visible = null, waited = 0
  const pending = syncStartggSets('fixture', { onProgress: value => { visible = value } })
  await tick()
  assert.equal(visible.sets.length, 1)
  assert.equal(waited, 0)
  for (let i = 0; i < 7; i += 1) {
    const delay = fixture.waits.shift()
    waited += delay.ms
    delay.callback()
    await tick()
  }
  assert.equal((await pending).sets.length, 8)
  assert.equal(waited, 4900)
})
