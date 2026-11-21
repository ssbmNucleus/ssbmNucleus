import test from 'node:test'
import assert from 'node:assert/strict'
import { handleViewerControlMessage } from './viewerMessages.js'

test('generic command errors and failed loads report errors without replacing current animation or edits', () => {
  const errors = []
  const state = { symbol: 'Wait1', frame: 12, frameCount: 60, playing: false, speed: 0.5,
    paint: { 'nana:0': 'edited-pixels' } }
  const callbacks = { onError: error => errors.push(error), onAnimationFrame: update => Object.assign(state, update) }
  for (const message of [
    { type: 'commandError', command: 'camera', error: 'Queue full' },
    { type: 'commandError', command: 'loadAnim' },
    { type: 'animLoaded', symbol: 'Attack11', frameCount: 0, success: false },
    { type: 'animLoaded', symbol: 'Attack11', error: 'Animation missing' }
  ]) assert.equal(handleViewerControlMessage(message, callbacks), true)
  assert.deepEqual(state, { symbol: 'Wait1', frame: 12, frameCount: 60, playing: false, speed: 0.5,
    paint: { 'nana:0': 'edited-pixels' } })
  assert.equal(errors.length, 4)
  assert.equal(errors[0], 'Queue full')
  assert.match(errors[1], /loadAnim/)
  assert.match(errors[2], /current animation is unchanged/)
  assert.equal(errors[3], 'Animation missing')
})

test('authoritative animation ticks replace playback fields, including paused, zero and reverse speed', () => {
  const state = { frame: 10, frameCount: 60, playing: true, speed: 1 }
  const callbacks = { onError: assert.fail, onAnimationFrame: update => Object.assign(state, update) }
  handleViewerControlMessage({ type: 'animFrame', frame: 0, frameCount: 120, playing: false, speed: -0.5 }, callbacks)
  assert.deepEqual(state, { frame: 0, frameCount: 120, playing: false, speed: -0.5 })
  handleViewerControlMessage({ type: 'animFrame', frame: 12.5 }, callbacks)
  assert.deepEqual(state, { frame: 12.5, frameCount: 120, playing: false, speed: -0.5 })
  handleViewerControlMessage({ type: 'animFrame', frame: NaN, frameCount: -1, playing: 'false', speed: Infinity }, callbacks)
  assert.deepEqual(state, { frame: 12.5, frameCount: 120, playing: false, speed: -0.5 })
})

test('successful and legacy animation loads remain available for pose handling; additive acknowledgements are ignored', () => {
  for (const message of [
    { type: 'animLoaded', success: true }, { type: 'animLoaded', symbol: 'Wait1' },
    { type: 'visibilitySet', visible: false }, { type: 'resized', width: 2048, height: 576 }
  ]) assert.equal(handleViewerControlMessage(message, { onError: assert.fail, onAnimationFrame: assert.fail }), false)
})
