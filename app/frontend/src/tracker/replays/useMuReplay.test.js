import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule, hookHarness, deferred, flush } from '../../../../../tests/frontend/hookHarness.mjs'

function fixture(enabled = true) {
  const h = hookHarness(), posts = [], gets = [], alerts = [], records = new Map()
  let status = { success: true, available: true, reason: null }
  const api = {
    get: async (path) => { gets.push(path); if (status instanceof Error) throw status; return status },
    post: (path, body) => { const reply = deferred(); posts.push({ path, body, ...reply }); return reply.promise },
  }
  const loaded = loadModule(new URL('./useMuReplay.js', import.meta.url), {
    react: h.react, '../../shared/transport/api': { api },
    '../../shared/jobs/useJobs': { useJob: (id) => records.get(id) || null },
    '../../shared/ui/appDialogs': { appAlert: (message) => alerts.push(message) },
  })
  const render = () => h.render(() => loaded.useMuReplay(enabled))
  return { render, posts, gets, alerts, records, h, setStatus: (next) => { status = next }, loaded }
}

test('Play off: nothing is asked and no action is offered', async () => {
  const f = fixture(false)
  assert.equal(f.render(), null); await flush()
  assert.deepEqual(f.gets, []); f.h.unmount()
})

test('a replay row sends only its indexed path and hears how the viewer ended', async () => {
  const f = fixture()
  f.render(); await flush()
  const view = f.render()
  assert.equal(view.available, true); assert.deepEqual(f.gets, ['/api/play/replay'])
  const start = view.watch({ id: 'g1', path: 'C:\\Slippi\\Game.slp', players: [] })
  f.posts[0].resolve({ job_id: 'j1' }); await start
  assert.deepEqual(f.posts.map((p) => [p.path, p.body]), [['/api/play/replay', { path: 'C:\\Slippi\\Game.slp' }]])
  f.records.set('j1', { status: 'running' }); f.render()
  assert.deepEqual(f.alerts, [])
  f.records.set('j1', { status: 'done', result: { outcome: 'crashed', message: 'The game crashed: CRASH at melee_game.dll+0x275301.' } })
  f.render(); f.render()
  assert.deepEqual(f.alerts, ['The game crashed: CRASH at melee_game.dll+0x275301.'])   // said once
  f.h.unmount()
})

test('unavailable says why, a refused start is shown, and a backend without Play offers nothing', async () => {
  const f = fixture()
  f.setStatus({ success: true, available: false, reason: 'This Nucleus Unlocked cannot play replays.' })
  f.render(); await flush()
  assert.deepEqual({ ...f.render(), watch: undefined, refresh: undefined },
    { available: false, reason: 'This Nucleus Unlocked cannot play replays.', watch: undefined, refresh: undefined })
  const start = f.render().watch({ path: 'C:\\x.slp' })
  f.posts[0].reject(new Error('That replay is not in Tracker.')); await start; await flush()
  assert.deepEqual(f.alerts, ['That replay is not in Tracker.'])
  assert.equal(f.gets.length, 2)                                   // asked again after a refusal
  f.setStatus(new Error('404')); f.render().refresh(); await flush()
  assert.equal(f.render(), null); f.h.unmount()
})

test('endedBadly: a quit or a running viewer is quiet', () => {
  const f = fixture()
  const { endedBadly } = f.loaded
  assert.equal(endedBadly(null), null)
  assert.equal(endedBadly({ status: 'running' }), null)
  assert.equal(endedBadly({ status: 'done', result: { outcome: 'quit', message: 'Closed.' } }), null)
  assert.equal(endedBadly({ status: 'done', result: { outcome: 'disc_error', message: 'The game could not open the replay.' } }),
    'The game could not open the replay.')
  assert.equal(endedBadly({ status: 'failed', error: "Your Melee ISO can't be used" }), "Your Melee ISO can't be used")
})
