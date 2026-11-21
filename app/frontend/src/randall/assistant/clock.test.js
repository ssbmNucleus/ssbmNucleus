import assert from 'node:assert/strict'
import test from 'node:test'
import { onTick } from './clock.js'

test('every clock on screen reads the same tick, once a second, and the tick stops with its last reader', t => {
  t.mock.timers.enable({ apis: ['setInterval', 'Date'], now: 1_000_000 })
  const card = [], bar = []
  const stopCard = onTick(now => card.push(now))
  const stopBar = onTick(now => bar.push(now))
  t.mock.timers.tick(999)
  assert.deepEqual(card, [], 'nothing before the first second')
  t.mock.timers.tick(1)
  t.mock.timers.tick(1000)
  assert.deepEqual(card, [1_001_000, 1_002_000])
  assert.deepEqual(bar, card, 'the card and the status bar get the same value at the same moment')
  stopCard()
  t.mock.timers.tick(1000)
  assert.deepEqual(card, [1_001_000, 1_002_000], 'a card that is gone no longer ticks')
  assert.equal(bar.length, 3)
  stopBar()
  t.mock.timers.tick(5000)
  assert.equal(bar.length, 3)
})
