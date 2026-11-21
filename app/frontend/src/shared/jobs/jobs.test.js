import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { loadModule, deferred, flush, hookHarness } from '../../../../../tests/frontend/hookHarness.mjs'
import * as storeModule from './jobStore.js'
import * as pass from './passView.js'

function fixture(connected = false) {
  const socket = new EventEmitter(); socket.connected = connected
  const gets = [], posts = []; let connections = 0
  const transport = loadModule(new URL('../transport/socket.js', import.meta.url), {
    'socket.io-client': { io: () => { connections++; return socket } },
    '../config/config': { BACKEND_URL: 'test', BACKEND_TOKEN: 'token' },
  })
  const api = {
    get(path) { const reply = deferred(); gets.push({ path, ...reply }); return reply.promise },
    post(path) { const reply = deferred(); posts.push({ path, ...reply }); return reply.promise },
  }
  const jobs = loadModule(new URL('./jobs.js', import.meta.url), {
    '../transport/api': { __esModule: true, default: api }, '../transport/socket': transport, './jobStore': storeModule,
  })
  return { ...jobs, transport, gets, posts, socket, connections: () => connections }
}
const record = (fields = {}) => ({ id: 'a', kind: 'restore', status: 'running', seq: 1, created_at: 1, ...fields })

test('start installs one shared listener and resyncs on first connect and every reconnect', async () => {
  const f = fixture()
  f.startJobStore(); f.startJobStore()
  assert.equal(f.connections(), 1); assert.equal(f.socket.listenerCount('job'), 1)
  assert.equal(f.gets.length, 0)
  f.socket.emit('connect')
  assert.equal(f.gets[0].path, '/api/jobs')
  f.gets[0].resolve({ jobs: [record()] }); await flush()
  assert.equal(f.jobStore.get('a').status, 'running')
  f.socket.emit('connect')
  f.gets[1].resolve({ jobs: [record({ status: 'done', seq: 2 })] }); await flush()
  assert.equal(f.jobStore.get('a').status, 'done')
  f.socket.emit('job', record({ id: 'b' }))
  assert.equal(f.jobStore.get('b').id, 'b')
})

test('starting after socket connection resyncs; failed sync is retried on reconnect', async () => {
  const f = fixture(true)
  f.startJobStore(); await flush()
  assert.equal(f.gets.length, 1)
  f.gets[0].reject(new Error('offline')); await flush()
  f.socket.emit('connect'); f.gets[1].resolve({ jobs: [record()] }); await flush()
  assert.equal(f.jobStore.active('restore').id, 'a')
})

test('a reconnect to a restarted backend ends the old process\'s unlisted running job', async () => {
  const f = fixture()
  f.startJobStore()
  f.socket.emit('job', record({ owner: { pid: 1, created: 10 } }))
  f.socket.emit('connect')
  f.gets[0].resolve({ jobs: [], owner: { pid: 2, created: 20 } }); await flush()
  assert.equal(f.jobStore.get('a').status, 'interrupted')
})

test('a slow resync cannot overwrite newer socket progress or completion', async () => {
  const f = fixture()
  f.startJobStore(); f.socket.emit('connect')
  f.socket.emit('job', record({ seq: 8, status: 'failed', error: 'disk full' }))
  f.gets[0].resolve({ jobs: [record({ seq: 2 })] }); await flush()
  assert.equal(f.jobStore.get('a').error, 'disk full')
})

test('refresh encodes ids, treats 404 as absent, and preserves transport errors', async () => {
  const f = fixture()
  const missing = f.refreshJob('folder/a b')
  assert.equal(f.gets[0].path, '/api/jobs/folder%2Fa%20b')
  f.gets[0].reject({ status: 404 }); assert.equal(await missing, null)
  const failed = f.refreshJob('a'), error = new Error('offline')
  f.gets[1].reject(error); await assert.rejects(failed, e => e === error)
  const found = f.refreshJob('a'); f.gets[2].resolve({ job: record() })
  assert.equal(await found, f.jobStore.get('a'))
})

test('seen is patched only after acknowledgment; cancellation is scoped to the encoded job id', async () => {
  const f = fixture(); f.jobStore.receive(record({ seen: false }))
  const rejected = f.markJobSeen('a')
  f.posts[0].reject(new Error('offline')); await assert.rejects(rejected, /offline/)
  assert.equal(f.jobStore.get('a').seen, false)
  const seen = f.markJobSeen('a')
  assert.equal(f.posts[1].path, '/api/jobs/a/seen')
  assert.equal(f.jobStore.get('a').seen, false)
  f.posts[1].resolve({}); await seen
  assert.equal(f.jobStore.get('a').seen, true)
  const cancelled = f.cancelJob('a/b')
  assert.equal(f.posts[2].path, '/api/jobs/a%2Fb/cancel')
  f.posts[2].resolve({ stopped: true }); assert.deepEqual(await cancelled, { stopped: true })
})

test('job hooks select by id/kind/status, request only missing ids, and detach on unmount', async () => {
  const f = fixture(), h = hookHarness()
  const hooks = loadModule(new URL('./useJobs.js', import.meta.url), { react: h.react, './jobs': f, './passView': pass })
  f.jobStore.receive(record({ id: 'done', status: 'done', ended_at: 12, created_at: 2 }))
  f.jobStore.receive(record({ id: 'failed', status: 'failed', ended_at: 13, created_at: 3 }))
  f.jobStore.receive(record({ id: 'other', kind: 'export', status: 'done', created_at: 4 }))
  f.jobStore.receive(record())
  let id = 'done'
  const render = () => h.render(() => ({ selected: hooks.useJob(id), active: hooks.useActiveJob('restore'),
    latest: hooks.useLatestJob('restore'), ended: hooks.useJobEndedAt('restore'),
    finished: hooks.useFinishedJobs('restore'), list: hooks.useJobList() }))
  const view = render()
  assert.equal(view.selected.id, 'done'); assert.equal(view.active.id, 'a')
  assert.equal(view.latest.id, 'failed'); assert.equal(view.ended, 13)
  assert.equal(view.finished, 'done'); assert.equal(view.list, f.jobStore.list())
  assert.equal(f.gets.length, 0)
  id = 'missing'; assert.equal(render().selected, null)
  assert.equal(f.gets.length, 1); assert.equal(f.gets[0].path, '/api/jobs/missing')
  f.gets[0].reject({ status: 404 }); await flush()
  render(); assert.equal(f.gets.length, 1)
  id = null; assert.equal(render().selected, null)
  h.unmount()
})

test('useJob with ask off reads the store and its events but asks the backend nothing until ask is on', async () => {
  const f = fixture(), h = hookHarness()
  const hooks = loadModule(new URL('./useJobs.js', import.meta.url), { react: h.react, './jobs': f, './passView': pass })
  let id = 'mine', ask = false
  const render = () => h.render(() => hooks.useJob(id, { ask }))
  assert.equal(render(), null); assert.equal(f.gets.length, 0)
  f.jobStore.receive(record({ id: 'mine', status: 'queued' }))
  assert.equal(render().status, 'queued'); assert.equal(f.gets.length, 0)
  id = 'other'; assert.equal(render(), null); assert.equal(f.gets.length, 0)
  ask = true; render()
  assert.deepEqual(f.gets.map(get => get.path), ['/api/jobs/other'])
  h.unmount()
})

test('useJobEnd ignores history, runs once, and uses the latest callback', () => {
  const f = fixture(), h = hookHarness(), calls = []
  const hooks = loadModule(new URL('./useJobs.js', import.meta.url), { react: h.react, './jobs': f, './passView': pass })
  f.jobStore.receive(record({ status: 'done', ended_at: 1 }))
  let label = 'first'
  const render = () => { const captured = label; h.render(() => hooks.useJobEnd('restore', job => calls.push([captured, job.id]))) }
  render(); assert.deepEqual(calls, [])
  label = 'new'; render()
  f.jobStore.receive(record({ id: 'new', status: 'failed', created_at: 2, ended_at: Date.now() / 1000 + 1 }))
  render(); render(); f.jobStore.patch('new', { seen: true }); render()
  assert.deepEqual(calls, [['new', 'new']]); h.unmount()
})
