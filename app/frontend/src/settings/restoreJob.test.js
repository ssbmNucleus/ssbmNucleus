import test from 'node:test'
import assert from 'node:assert/strict'
import { restoreOutcome, clearBackupMessage } from './restoreJob.js'

test('a running restore has no outcome, even if progress reached 100 percent', () => {
  for (const job of [null, { status: 'queued' }, { status: 'running', progress: 1 }]) assert.equal(restoreOutcome(job), null)
})

test('merge reports and recovery paths keep the result open; only a plain success reloads', () => {
  const report = { added: 3, skipped: 1 }
  assert.deepEqual(restoreOutcome({ status: 'done', result: { message: 'Merged', report, recovery_path: 'old' } }),
    { outcome: { message: 'Merged', report } })
  assert.deepEqual(restoreOutcome({ status: 'done', result: { message: 'Restored', recovery_path: 'old' } }),
    { outcome: { message: 'Restored', recoveryPath: 'old' } })
  assert.deepEqual(restoreOutcome({ status: 'done' }), { outcome: { message: 'Done!', reloading: true } })
})

test('failed, cancelled and interrupted restores end waiting with an honest error', () => {
  assert.deepEqual(restoreOutcome({ status: 'failed', error: 'disk full' }),
    { message: { text: 'Restore failed: disk full', type: 'error' } })
  assert.equal(restoreOutcome({ status: 'failed' }).message.text, 'Restore failed: Unknown error')
  assert.equal(restoreOutcome({ status: 'cancelled' }).message.text, 'Restore cancelled.')
  assert.match(restoreOutcome({ status: 'interrupted' }).message.text, /stopped when Nucleus closed/)
})

test('a backup timer cannot erase a later restore error or a newer identical success (F-N-6)', () => {
  const created = { text: 'Backup created!', type: 'success' }
  const error = { text: 'Restore failed', type: 'error' }, newer = { ...created }
  assert.deepEqual(clearBackupMessage(created, created), { text: '', type: '' })
  assert.equal(clearBackupMessage(error, created), error)
  assert.equal(clearBackupMessage(newer, created), newer)
})
