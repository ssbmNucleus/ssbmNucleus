import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { loadModule, flush } from '../../../../../tests/frontend/hookHarness.mjs'

test('late subscribers catch connect and channel cleanup preserves other users of the socket', async () => {
  const socket = new EventEmitter(); socket.connected = true
  const calls = []
  const transport = loadModule(new URL('./socket.js', import.meta.url), {
    'socket.io-client': { io: (...args) => { calls.push(args); return socket } },
    '../config/config': { BACKEND_URL: 'http://127.0.0.1:5000', BACKEND_TOKEN: 'test' },
  })
  let connects = 0, a = 0, b = 0
  const off = transport.subscribe({ connect: () => connects++, job: () => a++, ignored: null })
  const channel = transport.channel().on('job', () => b++)
  await flush()
  assert.equal(connects, 1)
  assert.deepEqual(calls, [['http://127.0.0.1:5000', { auth: { token: 'test' } }]])
  socket.emit('job', {}); assert.deepEqual([a, b], [1, 1])
  channel.disconnect(); socket.emit('job', {}); assert.deepEqual([a, b], [2, 1])
  off(); socket.emit('connect'); socket.emit('job', {})
  assert.equal(connects, 1); assert.equal(a, 2)
})
