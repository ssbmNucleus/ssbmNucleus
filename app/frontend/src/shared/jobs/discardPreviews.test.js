import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule, flush } from '../../../../../tests/frontend/hookHarness.mjs'
import { ACTIVE, createJobStore } from './jobStore.js'

function fixture(record, fetched = record) {
  const deleted = [], cancelled = []
  const store = createJobStore({ fetchJobs: async () => [], fetchJob: async () => fetched })
  if (record) store.receive(record)
  const { discardPreviews } = loadModule(new URL('./discardPreviews.js', import.meta.url), {
    './jobs': {
      jobStore: store, startJobStore() {}, refreshJob: id => store.refresh(id),
      cancelJob: async id => { cancelled.push(id) },
    },
    './jobStore': { ACTIVE },
    '../transport/api': { api: { delete: async path => { deleted.push(path) } } },
  })
  return { store, deleted, cancelled, discardPreviews }
}
const record = fields => ({ id: 'preview', kind: 'stage_render', status: 'running', seq: 1, ...fields })

test('dismissal cancels an active render and deletes only after its final record', async () => {
  const f = fixture(record())
  f.discardPreviews('preview', '/previews/preview')
  assert.deepEqual(f.cancelled, ['preview'])
  assert.deepEqual(f.deleted, [])
  f.store.receive(record({ status: 'cancelled', seq: 2 }))
  await flush()
  assert.deepEqual(f.deleted, ['/previews/preview'])
  f.store.receive(record({ status: 'cancelled', seq: 3, seen: true }))
  assert.equal(f.deleted.length, 1)
})

test('a completed render can be discarded immediately without cancellation', () => {
  const f = fixture(record({ status: 'done' }))
  f.discardPreviews('preview', '/previews/preview')
  assert.deepEqual(f.cancelled, [])
  assert.deepEqual(f.deleted, ['/previews/preview'])
})

test('a late start response is refreshed when its final event was missed', async () => {
  const f = fixture(null, record({ status: 'done' }))
  f.discardPreviews('preview', '/previews/preview')
  await flush()
  assert.deepEqual(f.deleted, ['/previews/preview'])
})
