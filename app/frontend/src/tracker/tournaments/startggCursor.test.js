import assert from 'node:assert/strict'
import test from 'node:test'

import { advanceIncrementalCursor, incrementalCursorFor } from './startgg.js'

test('capped incremental windows resume at the first unrequested page', () => {
  const store = { syncedAt: 10_000_000 }
  const cursor = incrementalCursorFor(store)
  assert.equal(cursor.nextPage, 1)
  assert.equal(cursor.updatedAfter, 6400)

  assert.equal(advanceIncrementalCursor(store, cursor, 1, 4), false)
  assert.equal(advanceIncrementalCursor(store, cursor, 2, 4), false)
  assert.equal(advanceIncrementalCursor(store, cursor, 3, 4), false)
  assert.deepEqual(store.incrementalCursor, {
    updatedAfter: 6400, nextPage: 4, totalPages: 4,
  })
  assert.equal(incrementalCursorFor(store).nextPage, 4)

  assert.equal(advanceIncrementalCursor(store, cursor, 4, 4), true)
  assert.equal(store.incrementalCursor, undefined)
})
