// The Replays list's rank/stock lookups, driven the way ReplaysPage drives
// them: every render passes the keys it still lacks. Opening months while a
// lookup was out used to fire a new POST per render for every missing key;
// those POSTs held the browser's connections to the backend open (POST /ranks
// fetches slippi.gg one code at a time behind a lock), so the month's own list
// request queued behind them and the month showed nothing.
import test from 'node:test'
import assert from 'node:assert/strict'
import { createBatchLookup } from './batchLookup.js'

const codes = (prefix, n) => Array.from({ length: n }, (_, i) => `${prefix}#${i}`)
const settle = () => new Promise((resolve) => setImmediate(resolve))

function harness({ batchSize = 50, fail = () => false } = {}) {
  const sent = [] // every request, in order
  const pending = []
  const have = {} // what the page has received (its `ranks` state)
  let open = 0
  let maxOpen = 0
  const clock = { t: 0 }
  const lookup = createBatchLookup({
    batchSize,
    retryMs: 30000,
    now: () => clock.t,
    request: (batch) => {
      sent.push(batch)
      open += 1
      maxOpen = Math.max(maxOpen, open)
      return new Promise((resolve, reject) => pending.push({ batch, resolve, reject }))
    },
    onResult: (_batch, data) => Object.assign(have, data),
  })
  // one page render: ask for whatever is still missing
  const render = (rows) => lookup.want(rows.filter((c) => !(c in have)))
  // the backend answers the oldest open request
  const answer = async () => {
    const { batch, resolve, reject } = pending.shift()
    open -= 1
    if (fail(batch)) reject(new Error('Backend unreachable'))
    else resolve(Object.fromEntries(batch.map((c) => [c, { ranked: false }])))
    await settle()
  }
  return { lookup, sent, pending, have, render, answer, clock, maxOpen: () => maxOpen }
}

test('opening months while a lookup is out queues one request, never a pile of duplicates', async () => {
  const h = harness()
  const april = codes('APR', 40)
  const may = codes('MAY', 45)
  const june = codes('JUN', 30)

  h.render(april) // April opens
  h.render([...april, ...may]) // May opens before April's ranks are back
  h.render([...april, ...may, ...june]) // and June
  h.render([...april, ...may, ...june]) // an unrelated re-render

  assert.equal(h.sent.length, 1, 'renders while a lookup is out must not send more')
  while (h.pending.length) {
    await h.answer()
    h.render([...april, ...may, ...june]) // the answer re-renders the page
  }

  assert.equal(h.maxOpen(), 1, 'never more than one lookup request open')
  const asked = h.sent.flat()
  assert.equal(new Set(asked).size, asked.length, 'no code asked twice')
  assert.deepEqual(new Set(asked), new Set([...april, ...may, ...june]))
  assert.ok(h.sent.every((b) => b.length <= 50), 'batches stay within the /ranks cap')
  assert.equal(Object.keys(h.have).length, 115)
})

test('more keys than one batch go out in turn, each batch after the last answer', async () => {
  const h = harness({ batchSize: 50 })
  const rows = codes('X', 120)
  h.render(rows)
  assert.deepEqual(h.sent.map((b) => b.length), [50])
  await h.answer()
  assert.deepEqual(h.sent.map((b) => b.length), [50, 50]) // no re-render needed
  await h.answer()
  await h.answer()
  assert.deepEqual(h.sent.map((b) => b.length), [50, 50, 20])
  assert.equal(Object.keys(h.have).length, 120)
})

test('a failed batch is not re-sent on every render, and later keys still go out', async () => {
  const h = harness({ fail: (batch) => batch.includes('A#0') })
  const a = codes('A', 3)
  h.render(a)
  await h.answer() // fails
  h.render(a)
  h.render(a)
  assert.equal(h.sent.length, 1, 'a down backend must not become a request loop')
  h.render([...a, ...codes('B', 2)])
  assert.deepEqual(h.sent.at(-1), ['B#0', 'B#1'])
})

test('a failed batch goes again once the retry window has passed and the page asks', async () => {
  let down = true
  const h = harness({ fail: () => down })
  const a = codes('A', 3)
  h.render(a)
  await h.answer() // fails: backend briefly unreachable
  h.clock.t += 10000
  h.render(a)
  assert.equal(h.sent.length, 1, 'still inside the retry window')
  down = false
  h.clock.t += 25000
  assert.equal(h.sent.length, 1, 'no retry by itself; only when the page asks')
  h.render(a) // paging back, reopening the month, or any re-render
  assert.deepEqual(h.sent.at(-1), a)
  await h.answer()
  assert.equal(Object.keys(h.have).length, 3, 'the transient failure did not leave the rows blank')
})

test('after stop, a late answer is dropped and nothing more is sent', async () => {
  const h = harness()
  h.render(codes('A', 60))
  h.lookup.stop()
  await h.answer()
  h.render(codes('A', 60))
  assert.deepEqual(h.have, {})
  assert.equal(h.sent.length, 1)
})
