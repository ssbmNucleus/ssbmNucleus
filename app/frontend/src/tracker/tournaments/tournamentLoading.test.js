import test from 'node:test'
import assert from 'node:assert/strict'
import { createTournamentLoader } from './tournamentLoading.js'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function fixture(saved = {}) {
  const profile = deferred(), standings = deferred(), history = []
  const events = []
  const loader = createTournamentLoader({
    cached: () => saved,
    profile: () => profile.promise,
    standings: () => standings.promise,
    sets: (slug, options) => { const job = { slug, options, ...deferred() }; history.push(job); return job.promise },
    onProfile: value => events.push(['profile', value]),
    onStandings: value => events.push(['standings', value]),
    onSets: value => events.push(['sets', value]),
    onPhase: value => events.push(['phase', value]),
  })
  return { loader, events, profile, standings, history }
}

test('expired cached history paints immediately while the network is pending', async () => {
  const saved = { sets: { sets: [1], stale: true }, profile: { gamer_tag: 'Known player' } }
  const f = fixture(saved)
  const done = f.loader.load('player')
  assert.deepEqual(f.events.slice(0, 2), [['profile', saved.profile], ['sets', saved.sets]])
  f.history[0].resolve({ sets: [1, 2] })
  await done
})

test('the first history page is published without waiting for other pages, profile or standings', async () => {
  const f = fixture()
  const done = f.loader.load('player')
  f.history[0].options.onProgress({ sets: ['first-page'], partial: true })
  assert.deepEqual(f.events.at(-1), ['sets', { sets: ['first-page'], partial: true }])
  f.history[0].resolve({ sets: ['complete'] })
  await done
  assert.deepEqual(f.events.at(-1), ['phase', 'ready'])
  f.profile.resolve({ gamer_tag: 'Later profile' })
  await Promise.resolve(); await Promise.resolve()
  assert.ok(f.events.some(([kind]) => kind === 'profile'))
})

test('replaced requests cannot overwrite current history or clear its loading state', async () => {
  const f = fixture()
  const old = f.loader.load('old')
  const current = f.loader.load('current')
  f.history[0].options.onProgress({ sets: ['wrong-person'] })
  f.history[0].resolve({ sets: ['wrong-person'] })
  await old
  assert.equal(f.events.some(([kind]) => kind === 'sets'), false)
  f.history[1].resolve({ sets: ['current'] })
  await current
  assert.deepEqual(f.events.at(-2), ['sets', { sets: ['current'] }])
})

test('unmount makes late history, profile and standings callbacks inert', async () => {
  const f = fixture()
  const done = f.loader.load('old')
  f.loader.cancel()
  f.profile.resolve({ gamer_tag: 'old' }); f.standings.resolve({ standings: [1] })
  f.history[0].options.onProgress({ sets: [1] })
  f.history[0].reject(new Error('late network error'))
  await done; await Promise.resolve(); await Promise.resolve()
  assert.deepEqual(f.events, [['phase', 'loading']])
})
