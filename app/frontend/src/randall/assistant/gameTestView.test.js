import test from 'node:test'
import assert from 'node:assert/strict'
import { gameTestPhase, gameTestTitle } from './gameTestView.js'

test('the title puts the costume first and its fighter after, in words', () => {
  assert.equal(gameTestTitle('Young Link — Tung Tung Sahur Not Ai'), 'Tung Tung Sahur Not Ai · Young Link')
  assert.equal(gameTestTitle('Goku — costume 2'), 'Costume 2 · Goku')
  assert.equal(gameTestTitle('tung_tung_sahur'), 'Tung Tung Sahur')
  assert.equal(gameTestTitle('Final Destination'), 'Final Destination')
  assert.equal(gameTestTitle(''), '')
})

test('before the first answer it is starting, with Stop available', () => {
  const phase = gameTestPhase({ snapshot: null })
  assert.equal(phase.pill, 'Starting…'); assert.equal(phase.view, 'progress'); assert.equal(phase.canStop, true)
  assert.equal(gameTestPhase({ snapshot: null, stopping: true }).pill, 'Stopping…')
})

test('building shows the plain line and a small whole percentage', () => {
  const phase = gameTestPhase({ snapshot: { running: true,
    status: { stage: 'building', percentage: 6.4, message: 'Importing the Young Link costume...' } } })
  assert.equal(phase.view, 'progress'); assert.equal(phase.tone, 'starting')
  assert.equal(phase.line, 'Importing the Young Link costume…'); assert.equal(phase.percent, 6)
  assert.equal(gameTestPhase({ snapshot: { running: true, status: { stage: 'waiting', percentage: null } } }).percent, null)
})

test('playing is live, shows the game, and names the controller port', () => {
  const phase = gameTestPhase({ snapshot: { running: true, status: { stage: 'playing', percentage: 100, controllerPort: 1,
    message: 'Ready. Use your controller on port 1; press Stop when finished.' } } })
  assert.equal(phase.pill, 'Live'); assert.equal(phase.tone, 'live'); assert.equal(phase.view, 'game')
  assert.equal(phase.line, 'Playing on controller port 1'); assert.equal(phase.percent, null)
  // Loading after the build already has a Dolphin window to show.
  assert.equal(gameTestPhase({ snapshot: { running: true, status: { stage: 'loading', message: 'Preparing...' } } }).view, 'game')
  assert.equal(gameTestPhase({ snapshot: { running: true, status: { stage: 'playing' } }, stopping: true }).pill, 'Stopping…')
})

test('an ended session is one quiet line, never a pass; failures say why', () => {
  const ended = gameTestPhase({ snapshot: { running: false,
    lastEvent: { event: 'test_complete', payload: { success: true, reason: 'Playable preview stopped.' } } } })
  assert.deepEqual([ended.pill, ended.view, ended.line, ended.canStop], ['Ended', 'ended', 'Play session ended.', false])
  const failed = gameTestPhase({ snapshot: { running: false, lastEvent: { event: 'test_error', payload: { error: 'Build failed.' } } } })
  assert.deepEqual([failed.tone, failed.pill, failed.line], ['failed', 'Failed', 'Build failed.'])
  const lost = gameTestPhase({ snapshot: { running: false, lastEvent: { event: 'test_complete', payload: { success: false, reason: 'Dolphin closed.' } } } })
  assert.equal(lost.line, 'Play session failed. Dolphin closed.')
})

test('connection and Stop problems stay visible while the game runs', () => {
  const phase = gameTestPhase({ snapshot: { running: true, status: { stage: 'playing' } },
    error: 'Connection interrupted. Reconnecting; Stop is still available.' })
  assert.match(phase.problem, /Connection interrupted/)
  assert.match(gameTestPhase({ snapshot: null, stopError: 'Could not stop the session: x. Retry Stop.' }).problem, /Retry Stop/)
})
