import test from 'node:test'
import assert from 'node:assert/strict'
import { subscribeUpdateStatus } from './useUpdateStatus.js'

function fixture() {
  let listener, resolve, reject, unsubscribed = 0
  const order = [], statuses = []
  const bridge = {
    onUpdateAvailable: callback => { order.push('subscribe'); listener = callback; return () => unsubscribed++ },
    getUpdateStatus: () => { order.push('snapshot'); return new Promise((yes, no) => { resolve = yes; reject = no }) },
  }
  const cleanup = subscribeUpdateStatus(bridge, value => statuses.push(value), () => 123)
  return { order, statuses, cleanup, emit: value => listener(value), resolve: value => resolve(value),
    reject: error => reject(error), unsubscribed: () => unsubscribed }
}

test('listener is installed before the initial snapshot request', async () => {
  const f = fixture(); assert.deepEqual(f.order, ['subscribe', 'snapshot'])
  const status = { update: { version: '0.8.2' }, checkedAt: 1, error: null }
  f.resolve(status); await Promise.resolve(); assert.deepEqual(f.statuses, [status]); f.cleanup()
})

test('an old empty snapshot cannot hide a newer update event', async () => {
  const f = fixture(); f.emit({ version: '0.8.2' });
  f.resolve({ update: null, checkedAt: null, error: null }); await Promise.resolve()
  assert.deepEqual(f.statuses, [{ update: { version: '0.8.2' }, checkedAt: 123, error: null }]); f.cleanup()
})

test('a null event clears an old update and fences a late populated snapshot', async () => {
  const f = fixture(); f.emit(null); f.resolve({ update: { version: '0.8.2' } }); await Promise.resolve()
  assert.deepEqual(f.statuses, [{ update: null, checkedAt: 123, error: null }]); f.cleanup()
})

test('unmount ignores late snapshots/events and unsubscribes once', async () => {
  const f = fixture(); f.cleanup(); f.emit({version:'0.8.2'}); f.resolve({update:{version:'0.8.2'}})
  await Promise.resolve(); assert.deepEqual(f.statuses, []); assert.equal(f.unsubscribed(), 1)
})

test('snapshot failure does not prevent later update events', async () => {
  const f = fixture(); f.reject(new Error('bridge gone')); await Promise.resolve(); await Promise.resolve()
  f.emit({ version: '0.8.2' }); assert.equal(f.statuses[0].update.version, '0.8.2'); f.cleanup()
})

test('a browser without the desktop bridge has no update side effects', async () => {
  const statuses = []; const cleanup = subscribeUpdateStatus(undefined, value => statuses.push(value))
  await Promise.resolve(); cleanup(); assert.deepEqual(statuses, [])
})
