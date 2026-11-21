import assert from 'node:assert/strict'
import test from 'node:test'

import { clearMonthGamesCache, gamesForMonth } from './tournamentReplays.js'

test('loads every backend-capped page and keys cache by index revision', async () => {
  clearMonthGamesCache()
  const calls = []
  const api = { get: async (_endpoint, { query }) => {
    calls.push(query.offset)
    const all = Array.from({ length: query.month === '2026-01' ? 250 : 0 },
      (_, id) => ({ id }))
    return { games: all.slice(query.offset, query.offset + 200), total: all.length }
  } }
  assert.equal((await gamesForMonth(api, '/replays', '2026-01', 'r1')).length, 250)
  assert.deepEqual(calls, [0, 200])
  await gamesForMonth(api, '/replays', '2026-01', 'r1')
  assert.deepEqual(calls, [0, 200])
  await gamesForMonth(api, '/replays', '2026-01', 'r2')
  assert.deepEqual(calls, [0, 200, 0, 200])
})

test('evicts rejected month requests so a retry can succeed', async () => {
  clearMonthGamesCache()
  let attempts = 0
  const api = { get: async () => {
    attempts += 1
    if (attempts === 1) throw new Error('offline')
    return { games: [{ id: 1 }], total: 1 }
  } }
  await assert.rejects(gamesForMonth(api, '/replays', '2026-02', 'r1'))
  assert.deepEqual(await gamesForMonth(api, '/replays', '2026-02', 'r1'), [{ id: 1 }])
})
