import test from 'node:test'
import assert from 'node:assert/strict'
import { cancelExportDat, requestExportDat, settleExportDat } from './datUtils.js'

const installViewer = (viewerSend = () => undefined) => {
  globalThis.window = { electron: { viewerSend } }
}

test('sequential exports cannot let an old timeout clear the current request', async () => {
  installViewer()
  const ref = { current: null }
  const first = requestExportDat(ref, 20)
  assert.equal(settleExportDat(ref, { success: true, data: 'first' }), true)
  assert.equal(await first, 'first')

  const second = requestExportDat(ref, 100)
  await new Promise(resolve => setTimeout(resolve, 35))
  assert.notEqual(ref.current, null)
  settleExportDat(ref, { success: true, data: 'second' })
  assert.equal(await second, 'second')
})

test('overlap, cancellation, send rejection, and timeout all settle', async () => {
  installViewer()
  const ref = { current: null }
  const active = requestExportDat(ref, 100)
  await assert.rejects(requestExportDat(ref, 100), /already in progress/)
  settleExportDat(ref, { success: false, error: 'viewer failed' })
  await assert.rejects(active, /viewer failed/)

  const cancelled = requestExportDat(ref, 100)
  assert.equal(cancelExportDat(ref, 'closed'), true)
  await assert.rejects(cancelled, /closed/)

  installViewer(() => Promise.reject(new Error('IPC unavailable')))
  await assert.rejects(requestExportDat(ref, 100), /IPC unavailable/)

  installViewer()
  await assert.rejects(requestExportDat(ref, 5), /timed out/)
  assert.equal(ref.current, null)
  const retry = requestExportDat(ref, 100)
  settleExportDat(ref, { success: true, data: 'retry-data' })
  assert.equal(await retry, 'retry-data')
})

test('correlated pair export ignores old session, old request and single DAT replies', async () => {
  const sent = []
  installViewer(message => { sent.push(message); return true })
  const ref = { current: null }
  const first = requestExportDat(ref, 100, { type: 'exportPaintPair', sessionId: 'current' })
  const command = sent[0]
  const members = [{ memberId: 'popo', data: 'popo' }, { memberId: 'nana', data: 'nana' }]
  for (const mutation of [{ sessionId: 'previous' }, { requestId: 'previous' }, { type: 'exportDat' }]) {
    assert.equal(settleExportDat(ref, { ...command, ...mutation, success: true, members }), false)
    assert.ok(ref.current)
  }
  assert.equal(settleExportDat(ref, { ...command, success: true, members }), true)
  assert.deepEqual(await first, members)
  const next = requestExportDat(ref, 100, { type: 'exportPaintPair', sessionId: 'current' })
  assert.equal(settleExportDat(ref, { ...command, success: true, members }), false)
  settleExportDat(ref, { ...sent[1], success: false, memberId: 'nana', error: 'Serialization failed' })
  await assert.rejects(next, /Nana: Serialization failed/)
})

test('false send result and pair disconnect reject without waiting for a timeout', async () => {
  installViewer(() => false)
  const ref = { current: null }
  await assert.rejects(requestExportDat(ref, 1000, { type: 'exportPaintPair', sessionId: 'session' }), /disconnected/)
  assert.equal(ref.current, null)
  installViewer(() => true)
  const pending = requestExportDat(ref, 1000, { type: 'exportPaintPair', sessionId: 'session' })
  cancelExportDat(ref, 'Viewer disconnected')
  await assert.rejects(pending, /disconnected/)
})
