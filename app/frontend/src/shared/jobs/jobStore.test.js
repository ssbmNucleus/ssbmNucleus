import test from 'node:test'
import assert from 'node:assert/strict'
import { createJobStore, isNewer, KEEP_ENDED } from './jobStore.js'

const owner = { pid: 1, created: 10 }
const job = (fields) => ({ id: 'a', kind: 'vault_restore', status: 'running', owner, seq: 1, created_at: 1, ...fields })
const emptyStore = () => createJobStore({ fetchJobs: async () => ({ jobs: [], owner }), fetchJob: async () => null })

test('an older event never replaces a newer record', () => {
  const store = emptyStore()
  store.receive(job({ seq: 5, status: 'done' }))
  store.receive(job({ seq: 4, status: 'running' }))
  assert.equal(store.get('a').status, 'done')
})

test('a record from another backend process replaces the old one', () => {
  assert.equal(isNewer(job({ seq: 1, owner: { pid: 2, created: 20 } }), job({ seq: 9 })), true)
})

test('resync fills in a job that ended while the socket was down', async () => {
  const store = createJobStore({
    fetchJobs: async () => ({ jobs: [job({ seq: 3, status: 'failed', error: 'x' })], owner }),
    fetchJob: async () => null,
  })
  store.receive(job({ seq: 2 }))
  let calls = 0
  store.subscribe(() => { calls += 1 })
  await store.resync()
  assert.equal(store.get('a').status, 'failed')
  assert.equal(calls, 1)
})

test('resync ends a dead backend process\'s running job the new backend does not list', async () => {
  const restarted = { pid: 2, created: 20 }
  const store = createJobStore({
    fetchJobs: async () => ({ jobs: [job({ id: 'listed', seq: 4, status: 'interrupted' })], owner: restarted }),
    fetchJob: async () => null,
  })
  store.receive(job({ id: 'memory-only', kind: 'replay_scan' }))  // the old process, never on disk
  store.receive(job({ id: 'listed' }))                             // the new backend recovered it from disk
  store.receive(job({ id: 'just-started', owner: restarted }))     // its event beat the list reply
  store.receive(job({ id: 'ended', status: 'done' }))
  await store.resync()
  assert.equal(store.get('memory-only').status, 'interrupted')
  assert.equal(store.get('memory-only').seen, true)  // quiet: no "stopped when Nucleus closed" notice
  assert.equal(store.active('replay_scan'), null)
  assert.equal(store.get('listed').status, 'interrupted')
  assert.equal(store.get('just-started').status, 'running')
  assert.equal(store.get('ended').status, 'done')
})

test('resync ends nothing when the reply does not name its backend process', async () => {
  const store = createJobStore({ fetchJobs: async () => ({ jobs: [] }), fetchJob: async () => null })
  store.receive(job({ id: 'memory-only' }))
  await store.resync()
  assert.equal(store.get('memory-only').status, 'running')
})

test('active(kind) is the same object until that job changes', () => {
  const store = emptyStore()
  store.receive(job({ seq: 1 }))
  const first = store.active('vault_restore')
  store.receive({ id: 'b', kind: 'export', status: 'running', owner, seq: 2, created_at: 2 })
  assert.equal(store.active('vault_restore'), first)
  store.receive(job({ seq: 3, status: 'done' }))
  assert.equal(store.active('vault_restore'), null)
})

test('patch marks a record seen without a newer seq', () => {
  const store = emptyStore()
  store.receive(job({ status: 'interrupted', seen: false }))
  store.patch('a', { seen: true })
  assert.equal(store.get('a').seen, true)
})

test('a kind that runs every few minutes keeps only its newest ended records', () => {
  const store = emptyStore()
  const scan = (n, status = 'done') => ({ id: `s${n}`, kind: 'replay_scan', status, owner, seq: n, created_at: n })
  store.receive(job({ seq: 1, status: 'done' }))
  store.receive(scan(0, 'running'))
  for (let n = 1; n <= KEEP_ENDED + 5; n += 1) store.receive(scan(n))
  const scans = store.list().filter((record) => record.kind === 'replay_scan')
  assert.equal(scans.filter((record) => record.status === 'done').length, KEEP_ENDED)
  assert.equal(store.get('s1'), null)
  assert.equal(store.get('s0').status, 'running')
  assert.equal(store.latest('replay_scan').id, `s${KEEP_ENDED + 5}`)
  assert.equal(store.get('a').status, 'done')
})


test('snapshots stay stable on invalid, equal and older events, and unsubscribe removes notifications', () => {
  const store = emptyStore()
  let calls = 0
  const off = store.subscribe(() => calls++)
  const initial = store.list()
  store.receive(null); store.receive({ kind: 'restore' }); store.patch('missing', { seen: true })
  assert.equal(store.list(), initial)
  store.receive(job({ seq: 4 }))
  const snapshot = store.list(), current = store.get('a')
  store.receive(job({ seq: 4, status: 'failed' })); store.receive(job({ seq: 1 }))
  assert.equal(store.list(), snapshot); assert.equal(store.get('a'), current); assert.equal(calls, 1)
  off(); store.receive(job({ seq: 5 })); assert.equal(calls, 1)
})

test('pid reuse is a new owner; missing sequence values compare as zero', () => {
  assert.equal(isNewer(job({ owner: { pid: 1, created: 11 }, seq: 0 }), job({ seq: 99 })), true)
  assert.equal(isNewer(job({ seq: undefined }), job({ seq: undefined })), false)
  assert.equal(isNewer(job({ seq: 1 }), job({ seq: undefined })), true)
})

test('kind selectors use creation order, skip active records for lastEnded, and return null when absent', () => {
  const store = emptyStore()
  store.receive(job({ id: 'old', status: 'done', created_at: 1, ended_at: 8 }))
  store.receive(job({ id: 'new', status: 'queued', created_at: 3 }))
  store.receive(job({ id: 'middle', status: 'failed', created_at: 2, ended_at: 9 }))
  assert.equal(store.active('vault_restore').id, 'new')
  assert.equal(store.latest('vault_restore').id, 'new')
  assert.equal(store.lastEnded('vault_restore').id, 'middle')
  for (const method of ['active', 'latest', 'lastEnded']) assert.equal(store[method]('absent'), null)
})

test('refresh returns the newer socket record if its HTTP reply is stale or absent', async () => {
  let reply
  const store = createJobStore({ fetchJobs: async () => null, fetchJob: async () => reply })
  store.receive(job({ seq: 8, status: 'done' }))
  reply = job({ seq: 2 }); assert.equal((await store.refresh('a')).status, 'done')
  reply = null; assert.equal((await store.refresh('a')).status, 'done')
  const before = store.list(); await store.resync(); assert.equal(store.list(), before)
})
