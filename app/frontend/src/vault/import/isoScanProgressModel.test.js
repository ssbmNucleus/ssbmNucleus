import test from 'node:test'
import assert from 'node:assert/strict'
import { scanProgressView, elapsedTime } from './isoScanProgressModel.js'

test('legacy zero-preview progress does not show fake work or diagnostic worker text', () => {
  assert.deepEqual(scanProgressView({ status: 'csp', percent: 70,
    message: 'Generating thumbnails 0/0 (×12 workers)' }),
  { title: 'Finishing scan', detail: '', percent: null })
})
test('actual counts override legacy diagnostics and retain zero progress', () => {
  assert.deepEqual(scanProgressView({ status: 'csp', percent: 0, current: 0, total: 3,
    message: 'Generating thumbnails 5/12 (×12 workers)' }),
  { title: 'Preparing previews', detail: '0 of 3 previews', percent: 0 })
})
test('unknown progress and reconnects remain indeterminate', () => {
  assert.equal(scanProgressView({ status: 'custom', percent: 50 }).percent, null)
  assert.equal(scanProgressView({ status: 'scanning', percent: 70, message: 'Reconnecting to scan…' }).percent, null)
})
test('queued custom cancellation describes the operation that must finish', () => {
  assert.deepEqual(scanProgressView({ status: 'custom', current: 1, total: 2 }, { cancelling: true }),
    { title: 'Finishing current import', detail: '', percent: null })
})
test('elapsed time remains readable past a minute and never becomes negative', () => {
  assert.equal(elapsedTime(84000), '1:24')
  assert.equal(elapsedTime(-500), '0:00')
})

test('custom loading uses the selected category names and normalizes legacy DAS messages', () => {
  for (const [key, label] of [['das', 'stage variants'], ['characters', 'custom characters'], ['stages', 'custom stages']]) {
    assert.equal(scanProgressView({ status: 'custom', categories: [key] }).title, `Importing ${label}`)
  }
  assert.equal(scanProgressView({ status: 'custom', message: 'Extracting DAS variants from build.iso…' }).title,
    'Importing stage variants')
  assert.equal(scanProgressView({ status: 'custom', categories: ['stages', 'characters'] }).title,
    'Custom characters & Custom stages')
  assert.equal(scanProgressView({ status: 'custom', categories: ['characters'], message: 'Extracting DAS variants' }).title,
    'Importing custom characters')
})

test('a phase that should be ticking says how long it has been quiet', () => {
  assert.equal(scanProgressView({ status: 'scanning', current: 1, total: 9 },
    { quietFor: 61000 }).detail, 'No new progress for 1:01')
})
test('the silent custom pass is not accused of stalling', () => {
  // No counts to show: reassure rather than warn.
  assert.equal(scanProgressView({ status: 'custom' }, { quietFor: 300000 }).detail,
    'Still working — this can take a few minutes')
  // With counts, the count is the more useful thing to keep showing.
  assert.equal(scanProgressView({ status: 'custom', current: 1, total: 3 },
    { quietFor: 300000 }).detail, 'Import 1 of 3')
})
test('a briefly quiet phase keeps its own detail', () => {
  assert.equal(scanProgressView({ status: 'scanning', current: 1, total: 9 },
    { quietFor: 44999 }).detail, '1 of 9 files')
})
test('cancelling and importing never show the quiet notice', () => {
  assert.equal(scanProgressView({ status: 'scanning', current: 1, total: 9 },
    { quietFor: 300000, cancelling: true }).detail, '')
  assert.equal(scanProgressView({ status: 'csp' },
    { quietFor: 300000, importing: true, count: 4 }).detail, '4 character skins')
})
