import test from 'node:test'
import assert from 'node:assert/strict'
import { orderSaveStarted, orderSaveSettled, orderSavesPending, waitForOrderSaves } from './orderSaves.js'

test('waiting for order saves resolves only when every pending save has landed', async () => {
  assert.equal(orderSavesPending(), false)
  await waitForOrderSaves()

  orderSaveStarted()
  orderSaveStarted()
  let done = false
  const waiting = waitForOrderSaves().then(() => { done = true })
  orderSaveSettled()
  await Promise.resolve()
  assert.equal(done, false)
  assert.equal(orderSavesPending(), true)

  orderSaveSettled()
  await waiting
  assert.equal(done, true)
  assert.equal(orderSavesPending(), false)
})

test('a settle without a start never drives the count below zero', () => {
  orderSaveSettled()
  assert.equal(orderSavesPending(), false)
  orderSaveStarted()
  assert.equal(orderSavesPending(), true)
  orderSaveSettled()
})


test('all Switch/Close waiters settle together, and the next save starts a new wait', async () => {
  orderSaveStarted()
  let settled = 0
  const waits = [waitForOrderSaves(), waitForOrderSaves()].map(wait => wait.then(() => settled++))
  await Promise.resolve(); assert.equal(settled, 0)
  orderSaveSettled(); await Promise.all(waits); assert.equal(settled, 2)
  orderSaveStarted(); let next = false
  const waiting = waitForOrderSaves().then(() => { next = true })
  await Promise.resolve(); assert.equal(next, false)
  orderSaveSettled(); await waiting; assert.equal(next, true)
})
