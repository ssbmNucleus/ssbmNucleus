import test from 'node:test'
import assert from 'node:assert/strict'
import { interruptedNotice } from './interruptedJobs.js'

test('only unseen interrupted records are shown, with cleanup notes and a fallback label', () => {
  const jobs = [
    { id: 'restore', status: 'interrupted', label: 'Restore', notes: ['Old vault restored.', 'Upload removed.'] },
    { id: 'capture', status: 'interrupted' },
    ...['queued', 'running', 'done', 'failed', 'cancelled'].map(status => ({ id: status, status })),
    { id: 'seen', status: 'interrupted', seen: true },
  ]
  const shown = new Set()
  const notice = interruptedNotice(jobs, shown)
  assert.deepEqual(notice.ids, ['restore', 'capture'])
  assert.equal(notice.message, 'Restore was stopped when Nucleus closed. Old vault restored. Upload removed.\n\nA task was stopped when Nucleus closed.')
  assert.equal(shown.size, 0)
  notice.ids.forEach(id => shown.add(id))
  assert.equal(interruptedNotice(jobs, shown), null)
  assert.equal(interruptedNotice(jobs.map(job => ({ ...job, seen: true })), new Set()), null)
  assert.equal(interruptedNotice([], new Set()), null)
})
