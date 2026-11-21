import { test } from 'node:test'
import assert from 'node:assert/strict'
import { startDolphinPreview } from './dolphinPreview.js'
const flush = () => new Promise(r => setTimeout(r, 8))
function fixture(extra = {}) {
  const calls = [], states = []
  const track = { stop() { calls.push('stop') }, addEventListener(name, cb) { this[name] = cb } }
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] }
  const video = { readyState: 2, videoWidth: 640, srcObject: null, play: async () => {} }
  const bridge = {
    dolphinCapturePrepare: async () => ({ supported: true, found: true, leaseId: 'lease1', sourceId: 'window:123:0' }),
    dolphinCaptureCheck: async id => { calls.push(['check', id]); return { active: true } },
    dolphinCaptureRelease: async id => { calls.push(['release', id]) },
    dolphinCaptureSeparate: async id => { calls.push(['separate', id]); return { active: true } }
  }
  const options = { bridge, video, mediaDevices: { getUserMedia: async args => { calls.push(args); return stream } },
    onState: state => states.push(state), startupMs: 50, mediaMs: 30, heartbeatMs: 20, ...extra }
  return { calls, states, track, stream, video, bridge, options }
}
test('first decoded frame precedes native presentation; stop releases exact session and tracks', async () => {
  const f = fixture(); f.video.readyState = 0
  const preview = startDolphinPreview(f.options); await flush()
  assert.equal(f.calls.some(c => c[0] === 'check'), false)
  preview.stop(); await flush()
  assert.equal(f.video.srcObject, null)
  assert.ok(f.calls.includes('stop'))
  assert.deepEqual(f.calls.filter(c => Array.isArray(c)), [['release', 'lease1']])
})
test('media arriving after unmount is stopped without presentation', async () => {
  let resolve
  const f = fixture({ mediaDevices: { getUserMedia: () => new Promise(r => { resolve = r }) } })
  const preview = startDolphinPreview(f.options); await flush(); preview.stop(); resolve(f.stream); await flush()
  assert.ok(f.calls.includes('stop')); assert.equal(f.video.srcObject, null)
  assert.equal(f.calls.some(c => c[0] === 'check'), false)
})
test('live capture uses exact source and no audio; ended track restores same session', async () => {
  const f = fixture(); const preview = startDolphinPreview(f.options); await flush()
  assert.equal(f.states.at(-1).status, 'live')
  assert.equal(f.calls[0].audio, false)
  assert.equal(f.calls[0].video.mandatory.chromeMediaSourceId, 'window:123:0')
  f.track.ended(); await flush()
  assert.equal(f.states.at(-1).status, 'separate'); assert.ok(f.calls.includes('stop'))
  preview.stop()
})
test('first-frame timeout stops capture and restores window', async () => {
  const f = fixture({ mediaMs: 10 }); f.video.readyState = 0
  const preview = startDolphinPreview(f.options); await new Promise(r => setTimeout(r, 25))
  assert.equal(f.states.at(-1).status, 'separate'); assert.ok(f.calls.includes('stop')); preview.stop()
})
test('ownership loss stops current stream; startup cancellation does not pop out unrelated run', async () => {
  const f = fixture(); f.bridge.dolphinCaptureCheck = async () => ({ active: false })
  const preview = startDolphinPreview(f.options); await flush()
  assert.equal(f.states.at(-1).status, 'separate'); preview.stop()
  const g = fixture(); g.bridge.dolphinCapturePrepare = async () => ({ found: false })
  const waiting = startDolphinPreview(g.options); await flush(); waiting.stop(); await flush()
  assert.equal(g.calls.length, 0)
})

test('disposed failing preview does not publish state after delayed restoration', async () => {
  const f = fixture(); let restore
  f.bridge.dolphinCaptureSeparate = () => new Promise(r => { restore = r })
  const preview = startDolphinPreview(f.options); await flush()
  f.track.ended(); await flush()
  preview.stop(); const count = f.states.length
  restore({ active: true }); await flush()
  assert.equal(f.states.length, count)
})

test('repeated explicit popout can reopen the current owned window after lease release', async () => {
  const f = fixture(); const preview = startDolphinPreview(f.options); await flush()
  await preview.popout(); await preview.popout()
  assert.deepEqual(f.calls.filter(c => c[0] === 'separate'), [['separate', 'lease1'], ['separate', undefined]])
  preview.stop()
})
test('paused images remain live without new frames while ownership stays valid', async t => {
  let time = 100
  t.mock.method(Date, 'now', () => time)
  const f = fixture({ heartbeatMs: 1 }); f.track.muted = false
  const preview = startDolphinPreview(f.options); await flush()
  time += 11000; await flush()
  assert.equal(f.states.at(-1).status, 'live'); preview.stop()
})

test('chat card rejects a different session before media capture and cannot pop it out', async () => {
  const f = fixture({ expectedSessionId: 'old-session' })
  const preview = startDolphinPreview(f.options); await flush()
  assert.equal(f.calls.some(c => c.audio === false), false)
  assert.match(f.states.at(-1).message, /another session/)
  await preview.popout()
  assert.equal(f.calls.some(c => c[0] === 'separate'), false)
  preview.stop()
})
test('sustained muted source fails even if the process still owns its window', async t => {
  let time = 100
  t.mock.method(Date, 'now', () => time)
  const f = fixture({ heartbeatMs: 1 }); f.track.muted = true
  const preview = startDolphinPreview(f.options); await flush()
  time += 11000; await flush()
  assert.equal(f.states.at(-1).status, 'separate'); preview.stop()
})

test('the live state carries where the game sits in the frame, and follows a resized window', async () => {
  const client = { x: 1, y: 31, width: 640, height: 480, frameWidth: 642, frameHeight: 512 }
  const f = fixture({ heartbeatMs: 5 })
  f.bridge.dolphinCapturePrepare = async () => ({ supported: true, found: true, leaseId: 'lease1', sourceId: 'window:123:0', client })
  let checked = { active: true, client }
  f.bridge.dolphinCaptureCheck = async () => checked
  const preview = startDolphinPreview(f.options); await flush()
  assert.deepEqual(f.states.at(-1), { status: 'live', message: '', client })
  const count = f.states.length
  await flush()
  assert.equal(f.states.length, count, 'an unchanged window publishes nothing new')
  checked = { active: true, client: { ...client, y: 40, height: 472 } }
  await flush(); await flush()
  assert.equal(f.states.at(-1).client.y, 40)
  checked = { active: true }
  await flush(); await flush()
  assert.equal(f.states.at(-1).client.y, 40, 'a check without geometry keeps the last known crop')
  preview.stop()
})
