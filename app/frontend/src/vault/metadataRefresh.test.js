import test from 'node:test'
import assert from 'node:assert/strict'
import { createMetadataRefresh } from './metadataRefresh.js'

function fixture() {
  const requests = [], catalogs = [], loading = [], errors = []
  const refresh = createMetadataRefresh({
    read: () => new Promise((resolve, reject) => requests.push({ resolve, reject })),
    setMetadata: value => catalogs.push(value), setLoading: value => loading.push(value),
    onError: (...args) => errors.push(args),
  })
  return { requests, catalogs, loading, errors, refresh }
}

test('pre-delete metadata cannot resurrect a deleted costume', async () => {
  const f = fixture(), old = f.refresh(), fresh = f.refresh()
  f.requests[1].resolve({ metadata: { characters: { Luigi: { skins: [] } } } })
  await fresh
  f.requests[0].resolve({ metadata: { characters: { Luigi: { skins: [{ id: 'deleted' }] } } } })
  await old
  assert.deepEqual(f.catalogs, [{ characters: { Luigi: { skins: [] } } }])
  assert.deepEqual(f.loading, [false])
})

test('late response or transport failure cannot replace a same-ID reimport', async () => {
  const f = fixture(), old = f.refresh(), fresh = f.refresh()
  const reimported = { characters: { Luigi: { skins: [{ id: 'same', color: 'New' }] } } }
  f.requests[1].resolve({ metadata: reimported }); await fresh
  f.requests[0].reject(new Error('old connection closed')); await old
  assert.deepEqual(f.catalogs, [reimported]); assert.deepEqual(f.errors, [])
})

test('latest transport failure clears catalog; backend failure preserves it', async () => {
  const f = fixture(), first = f.refresh()
  f.requests[0].reject(new Error('offline')); await first
  const next = f.refresh()
  f.requests[1].reject(Object.assign(new Error('backend failed'), { data: {} })); await next
  assert.deepEqual(f.catalogs, [{ characters: {} }])
  assert.equal(f.errors.length, 2)
})
