import { test } from 'node:test'
import assert from 'node:assert/strict'
import { MODE_NAMES, modeCycle, nextMode, startingMode } from './modeCycle.js'

test('the wordmark cycles Nucleus, Tracker, Play and back', () => {
  const cycle = modeCycle({ tracker: true, play: true })
  assert.deepEqual(cycle, ['nucleus', 'nucleome', 'play'])
  assert.equal(nextMode('nucleus', cycle), 'nucleome')
  assert.equal(nextMode('nucleome', cycle), 'play')
  assert.equal(nextMode('play', cycle), 'nucleus')
})

test('a normal release (Play left out) cycles Nucleus and Tracker as before', () => {
  const cycle = modeCycle({ tracker: true, play: false })
  assert.deepEqual(cycle, ['nucleus', 'nucleome'])
  assert.equal(nextMode('nucleus', cycle), 'nucleome')
  assert.equal(nextMode('nucleome', cycle), 'nucleus')
  // a stored mode the build left out goes back to Nucleus
  assert.equal(nextMode('play', cycle), 'nucleus')
})

test('a mode the build gates off is skipped', () => {
  const noTracker = modeCycle({ tracker: false, play: true })
  assert.deepEqual(noTracker, ['nucleus', 'play'])
  assert.equal(nextMode('nucleus', noTracker), 'play')
  assert.equal(nextMode('play', noTracker), 'nucleus')
  // only Nucleus: the wordmark has nowhere to go (App.jsx renders it inert)
  assert.deepEqual(modeCycle({}), ['nucleus'])
  assert.equal(nextMode('nucleus', modeCycle({})), 'nucleus')
})

test('every mode has the name the wordmark tooltip uses', () => {
  assert.deepEqual(MODE_NAMES, { nucleus: 'Nucleus', nucleome: 'Tracker', play: 'Unlocked' })
})

test('a first run opens on Unlocked where the build has it, and on Nucleus where it does not', () => {
  for (const none of [null, undefined, '']) {
    assert.equal(startingMode(none, { tracker: true, play: true }), 'play')
    assert.equal(startingMode(none, { tracker: false, play: true }), 'play')
    assert.equal(startingMode(none, { tracker: true, play: false }), 'nucleus')
    assert.equal(startingMode(none, {}), 'nucleus')
  }
})

test('a remembered mode is kept, and one this build leaves out goes back to Nucleus', () => {
  const all = { tracker: true, play: true }
  assert.equal(startingMode('nucleus', all), 'nucleus')
  assert.equal(startingMode('nucleome', all), 'nucleome')
  assert.equal(startingMode('play', all), 'play')
  assert.equal(startingMode('play', { tracker: true, play: false }), 'nucleus')
  assert.equal(startingMode('nucleome', { tracker: false, play: true }), 'nucleus')
  assert.equal(startingMode('something else', all), 'nucleus')
})
