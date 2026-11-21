import test from 'node:test'
import assert from 'node:assert/strict'
import { SETUP_KIND, setupJobToShow, setupStep } from './setupJob.js'

const job = (fields) => ({ id: 'a', kind: SETUP_KIND, status: 'running', extra: {}, seen: false, ...fields })

test('a reopened wizard shows the setup that kept running after it was closed', () => {
  const running = job({ id: 'b', extra: { phase: 'verifying' } })
  const shown = setupJobToShow([running, { id: 'x', kind: 'vault_restore', status: 'running' }])
  assert.equal(shown, running)
  assert.equal(setupStep(shown), 'verifying')
})

test('the engine\'s complete phase is not the end: Get Started waits for the saved result', () => {
  assert.equal(setupStep(job({ extra: { phase: 'complete' } })), 'copying')
  const done = job({ status: 'done', result: { isoPath: 'C:/melee.iso' } })
  assert.equal(setupStep(done), 'copying')
  assert.equal(setupStep(done, 'a'), 'complete')
})

test('an ended setup stays shown until seen; a dismissed or interrupted one does not', () => {
  assert.equal(setupStep(setupJobToShow([job({ status: 'failed', error: 'x' })])), 'error')
  assert.equal(setupJobToShow([job({ status: 'failed', seen: true })]), null)
  assert.equal(setupJobToShow([job({ status: 'failed' })], { dismissedId: 'a' }), null)
  assert.equal(setupJobToShow([job({ status: 'interrupted' })]), null)
})

test('the setup this wizard started wins, and nothing else stands in for it', () => {
  const older = job({ id: 'old', status: 'failed' })
  assert.equal(setupJobToShow([older], { startedId: 'new' }), null)
  const started = job({ id: 'new' })
  assert.equal(setupJobToShow([started, older], { startedId: 'new' }), started)
})


test('active setup wins over unseen history, while a started id remains authoritative even when seen', () => {
  const done = job({ id: 'done', status: 'done' }), queued = job({ id: 'queued', status: 'queued', seen: true })
  assert.equal(setupJobToShow([done, queued]), queued)
  assert.equal(setupJobToShow([done, queued], { startedId: 'done' }), done)
  assert.equal(setupJobToShow([queued], { startedId: 'queued' }), queued)
  assert.equal(setupJobToShow([queued], { startedId: 'queued', dismissedId: 'queued' }), null)
  assert.equal(setupJobToShow(null), null)
})

test('setup phases map to the wizard without declaring completion from progress alone', () => {
  assert.equal(setupStep(null), null)
  assert.equal(setupStep(job({ status: 'queued' })), 'verifying')
  assert.equal(setupStep(job({ extra: { phase: 'extracting' } })), 'extracting')
  for (const phase of ['copying_characters', 'extracting_sounds', 'complete'])
    assert.equal(setupStep(job({ extra: { phase }, progress: 1 })), 'copying')
  for (const status of ['failed', 'cancelled', 'interrupted']) assert.equal(setupStep(job({ status })), 'error')
  assert.equal(setupStep(job({ status: 'done' }), 'another'), 'copying')
})


test('Try Again preserves the auto-detected ISO displayed by Continue (F-H-1)', async () => {
  const { setupRetryPath } = await import('./setupJob.js')
  assert.equal(setupRetryPath({ isoPath: 'C:/games/melee.iso' }), 'C:/games/melee.iso')
  assert.equal(setupRetryPath(null), '')
  assert.equal(setupRetryPath({ slippiPath: 'Dolphin' }), '')
})
